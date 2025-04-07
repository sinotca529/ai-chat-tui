import os
from chat_tree import ChatTree


class ChatTreeStore:
    """チャットツリーを管理するクラス."""

    def __init__(self, save_dir: str):
        self._save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def save(self, chat_tree: ChatTree) -> None:
        """ツリーをJSONファイルに保存."""
        chat_tree.save(self._path_of(chat_tree.get_tree_id()))

    def tree_id_list(self) -> list[str]:
        """保存されたスレッドのリストを取得."""
        files = sorted(os.listdir(self._save_dir), reverse=True)
        return [f[:-len(".json")] for f in files if f.endswith(".json")]

    def load(self, tree_id: str) -> ChatTree:
        """指定したスレッドを読み込む."""
        return ChatTree.from_file(self._path_of(tree_id))

    def _path_of(self, tree_id: str) -> str:
        """ツリーIDに対応するファイルパスを返す"""
        return os.path.join(self._save_dir, f"{tree_id}.json")
