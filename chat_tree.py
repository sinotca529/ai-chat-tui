from role import Role
import json
import uuid
import sys


class ChatTree:
    def __init__(self, tree_id: str, messages: list[dict]):
        self._tree_id = tree_id
        self.messages = messages

    def insert(self, parent: int, role: Role, msg: str) -> int:
        """ツリーにノードを追加し、追加したノードの id を返す"""
        data = {
            "role": role.role_name(),
            "content": msg,
            "id": len(self.messages),
            "parent": parent,
            "children": [],
            "siblings": [],
        }

        if data["id"] == 0:
            data["parent"] = None
            self.messages.append(data)
            return data["id"]

        # 兄弟ノードを登録
        data["siblings"] = self.messages[parent]["children"][:]  # copy
        self.messages.append(data)

        # data の兄弟ノードに data を兄弟だと認知させる
        for sibling in self.messages[parent]["children"]:
            self.messages[sibling]["siblings"].append(data["id"])

        # data の親に data が子だと認知させる
        self.messages[parent]["children"].append(data["id"])

        return data["id"]

    # def append(self, role: Role, message: str) -> int:
    #     """ツリーの末尾にノードを追加し、追加したノードの id を返す"""
    #     return self.insert(len(self.messages) - 1, role, message)

    def children(self, index: int) -> list[int]:
        return self.messages[index]["children"]

    def parent(self, index: int) -> int:
        return self.messages[index]["parent"]

    def save(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "tree_id": self._tree_id,
                "messages": self.messages,
            }
            print(data, file=sys.stderr)
            json.dump(data, f, ensure_ascii=False, indent=2)

    def first_thread_id(self) -> int:
        """最初のスレッドのIDを取得。 (スレッドID = 葉ノードのID)"""
        if len(self.messages) == 0:
            return None

        id = 0
        while len(self.messages[id]["children"]) > 0:
            id = self.messages[id]["children"][0]

        return id

    def thread(self, thread_id: int) -> list[dict]:
        """指定したスレッドのメッセージを取得."""
        if thread_id is None:
            return []

        rev_index_list = [thread_id]
        while self.messages[thread_id]["parent"] is not None:
            thread_id = self.messages[thread_id]["parent"]
            rev_index_list.append(thread_id)

        return [self.messages[i] for i in reversed(rev_index_list)]

    def get_tree_id(self) -> int:
        return self._tree_id

    def get_children(self, id: int) -> list[int]:
        return self.messages[id]["children"]

    @staticmethod
    def from_file(filepath: str) -> "ChatTree":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return ChatTree(data["tree_id"], data["messages"])

    @staticmethod
    def new() -> "ChatTree":
        return ChatTree(str(uuid.uuid4()), [])
