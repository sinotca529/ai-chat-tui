import os
import json


class ChatLogManager:
    """チャットログを管理するクラス."""

    def __init__(self, save_dir: str):
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def save_thread(self, thread_id: str, messages: list):
        """スレッドをJSONファイルに保存."""
        filepath = os.path.join(self.save_dir, f"{thread_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

    def thread_id_list(self):
        """保存されたスレッドのリストを取得."""
        files = sorted(os.listdir(self.save_dir), reverse=True)
        return [
            file[:-len(".json")]
            for file in files
            if file.endswith(".json")
        ]

    def load_thread(self, thread_id: str):
        """指定したスレッドを読み込む."""
        filepath = os.path.join(self.save_dir, f"{thread_id}.json")
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
