from datetime import datetime
from openai import OpenAI
from chat_log_manager import ChatLogManager


class ChatManager:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        save_dir: str
    ):
        super().__init__()
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.msg_list = []
        self.model = model

        self.log_manager = ChatLogManager(save_dir)
        self.thread_id = None

    def send_message(self, msg: str):
        """OpenAI API にメッセージを送信"""

        if self.thread_id is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.thread_id = timestamp

        self.msg_list.append({"role": "user", "content": msg})
        stream = self.client.chat.completions.create(
            messages=self.msg_list,
            model=self.model,
            stream=True,
        )

        response = ""
        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content or ""
            except Exception:
                delta = ""
            response += delta
            yield delta

        self.msg_list.append({"role": "assistant", "content": response})
        self.log_manager.save_thread(self.thread_id, self.msg_list)

    def load_thread(self, thread_id: str):
        """指定したスレッドを読み込む."""
        self.msg_list = self.log_manager.load_thread(thread_id)
        self.thread_id = thread_id

    def thread_id_list(self):
        """保存されたスレッドのリストを取得."""
        return self.log_manager.thread_id_list()
