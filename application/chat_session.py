from typing import AsyncIterator
from domain.chat_tree import ChatTree
from domain.role import Role
from application.thread_entry import ThreadEntry
from infrastructure.api_handler import ApiHandler
from infrastructure.chat_tree_store import ChatTreeStore


class ChatSession:
    def __init__(self, tree: ChatTree, api: ApiHandler, store: ChatTreeStore) -> None:
        self._tree = tree
        self._api = api
        self._store = store

    @property
    def tree_id(self) -> str:
        return self._tree.tree_id

    def current_thread(self) -> list[ThreadEntry]:
        if self._tree.current_id is None:
            return []
        nodes = self._tree.thread(self._tree.current_id)
        result: list[ThreadEntry] = []
        for node in nodes:
            siblings = self._tree.siblings_with_self(node.id)
            sibling_count = len(siblings)
            sibling_index = siblings.index(node.id) + 1
            result.append(
                ThreadEntry(
                    node=node,
                    sibling_index=sibling_index,
                    sibling_count=sibling_count,
                )
            )
        return result

    async def send_message(self, msg: str) -> AsyncIterator[str]:
        thread_messages = [
            {"role": str(e.node.role), "content": e.node.content}
            for e in self.current_thread()
        ]
        user_id = self._tree.insert(self._tree.current_id, Role.USER, msg)
        self._tree.set_current(user_id)

        full_response = ""
        async for chunk in self._api.stream(thread_messages, msg):
            full_response += chunk
            yield chunk

        asst_id = self._tree.insert(user_id, Role.ASSISTANT, full_response)
        self._tree.set_current(asst_id)
        self._store.save(self._tree)

    def navigate_to(self, node_id: int) -> None:
        self._tree.set_current(node_id)

    def navigate_to_branch_end(self, node_id: int) -> None:
        """指定ノードから長子を辿って末端まで移動する"""
        current = node_id
        while True:
            children = self._tree.children(current)
            if not children:
                break
            current = children[0]
        self._tree.set_current(current)

    def siblings_of(self, node_id: int) -> list[int]:
        return self._tree.siblings_with_self(node_id)

    @property
    def title(self) -> str:
        return self._tree.title

    def set_title(self, title: str) -> None:
        self._tree.set_title(title)
        self._store.save(self._tree)

    async def generate_title(self) -> str:
        messages = [
            {"role": str(e.node.role), "content": e.node.content}
            for e in self.current_thread()
        ]
        title = await self._api.generate_title(messages)
        self.set_title(title)
        return title

    def delete_tree(self, tree_id: str) -> bool:
        """ツリーを削除する。現在のツリーを削除した場合は新規ツリーに切り替えて True を返す"""
        is_current = tree_id == self._tree.tree_id
        self._store.delete(tree_id)
        if is_current:
            self._tree = self._store.new_tree()
        return is_current

    def list_trees(self) -> list[tuple[str, str]]:
        return self._store.list_trees()

    def load_tree(self, tree_id: str) -> None:
        self._tree = self._store.load(tree_id)

    def new_tree(self) -> None:
        self._tree = self._store.new_tree()

    @property
    def current_model(self) -> str:
        return self._api.model

    def set_model(self, model_id: str) -> None:
        self._api.set_model(model_id)

    async def list_models(self) -> list[str]:
        return await self._api.list_models()
