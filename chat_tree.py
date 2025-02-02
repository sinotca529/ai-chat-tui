from role import Role
import json
import uuid


class ChatTree:
    def __init__(self, tree_id: str, messages: list[dict]):
        self.tree_id = tree_id
        self.messages = messages

    def insert(self, parent: str, role: Role, message: str) -> int:
        added_index = len(self.messages)
        data = {
            "role": role.role_name(),
            "content": message,
            "id": added_index,
            "parent": parent,
            "children": [],
            "siblings": [],
        }

        if len(self.messages) == 0:
            data["parent"] = None
            self.messages.append(data)
            return added_index

        data["siblings"] = self.messages[parent]["children"][:]  # copy
        self.messages.append(data)

        for sibling in self.messages[parent]["children"]:
            sibling["siblings"].append(added_index)

        self.messages[parent]["children"].append(added_index)
        return added_index

    def append(self, role: Role, message: str) -> int:
        return self.insert(len(self.messages) - 1, role, message)

    def children(self, index: int) -> list[int]:
        return self.messages[index]["children"]

    def save(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            data = {
                "tree_id": self.tree_id,
                "messages": self.messages,
            }
            json.dump(data, f, ensure_ascii=False, indent=2)

    def first_thread_id(self) -> int:
        """最初のスレッドのIDを取得.スレッドIDは葉ノードのインデックス."""
        if len(self.messages) == 0:
            return None

        index = 0
        while len(self.messages[index]["children"]) > 0:
            index = self.messages[index]["children"][0]
        return index

    def thread(self, thread_id: int) -> list[dict]:
        """指定したスレッドのメッセージを取得."""
        if thread_id is None:
            return []

        rev_index_list = [thread_id]
        while self.messages[thread_id]["parent"] is not None:
            thread_id = self.messages[thread_id]["parent"]
            rev_index_list.append(thread_id)

        return [self.messages[i] for i in reversed(rev_index_list)]

    @staticmethod
    def from_file(filepath: str) -> "ChatTree":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return ChatTree(data["tree_id"], data["messages"])

    @staticmethod
    def new() -> "ChatTree":
        return ChatTree(str(uuid.uuid4()), [])
