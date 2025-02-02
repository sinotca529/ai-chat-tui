import os
from chat_tree import ChatTree


class ChatTreeStore:
    """チャットツリーを管理するクラス."""

    def __init__(self, save_dir: str):
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def save(self, chat_tree: ChatTree) -> None:
        """ツリーをJSONファイルに保存."""
        filepath = os.path.join(self.save_dir, f"{chat_tree.tree_id}.json")
        chat_tree.save(filepath)

    def tree_id_list(self) -> list[str]:
        """保存されたスレッドのリストを取得."""
        files = sorted(os.listdir(self.save_dir), reverse=True)
        return [
            file[:-len(".json")]
            for file in files
            if file.endswith(".json")
        ]

    def load(self, tree_id: str) -> ChatTree:
        """指定したスレッドを読み込む."""
        filepath = os.path.join(self.save_dir, f"{tree_id}.json")
        return ChatTree.from_file(filepath)
