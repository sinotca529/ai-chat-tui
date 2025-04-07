from chat_tree import ChatTree
from api_handler import ApiHandler
from typing import Generator
from role import Role


class ChatTreeHandler:
    def __init__(self, tree: ChatTree, api_handler: ApiHandler):
        self.api_handler = api_handler
        self._tree = tree
        self._thread_id = self._tree.first_thread_id()

    def send_message(
        self,
        msg: str,
        modified_id: int = None
    ) -> (int, Generator[str, None, None]):
        """OpenAI API にメッセージを送信"""

        # メッセージを改変するなら、スレッドを切り替える
        if modified_id is not None:
            self._thread_id = self._tree.parent(modified_id)

        thread = [
            {"role": e["role"], "content": e["content"]}
            for e in self.current_thread()
        ]
        stream = self.api_handler.send_message(thread, msg)

        user_msg_id = self._tree.insert(self._thread_id, Role.USER, msg)

        def generator():
            response = ""
            for chunk in stream:
                response += chunk
                yield chunk

            self._thread_id = self._tree.insert(
                user_msg_id,
                Role.ASSISTANT,
                response
            )

        return user_msg_id, generator()

    def current_thread(self):
        return self._tree.thread(self._thread_id)

    def get_thread_id(self) -> int:
        return self._thread_id

    def get_tree_id(self) -> int:
        return self._tree.get_tree_id()

    def get_tree(self) -> ChatTree:
        return self._tree
