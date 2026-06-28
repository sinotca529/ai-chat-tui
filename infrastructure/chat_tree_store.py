import json
import os
from domain.chat_tree import ChatTree


class ChatTreeStore:
    def __init__(self, save_dir: str) -> None:
        self._save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def save(self, tree: ChatTree) -> None:
        path = os.path.join(self._save_dir, f"{tree.tree_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tree.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, tree_id: str) -> ChatTree:
        path = os.path.join(self._save_dir, f"{tree_id}.json")
        with open(path, "r", encoding="utf-8") as f:
            return ChatTree.from_dict(json.load(f))

    def list_ids(self) -> list[str]:
        return sorted(
            fname[:-5]
            for fname in os.listdir(self._save_dir)
            if fname.endswith(".json")
        )

    def new_tree(self) -> ChatTree:
        return ChatTree()
