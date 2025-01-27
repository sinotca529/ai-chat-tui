import asyncio
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Input, Static, Button, ListView, ListView, ListItem
from openai import OpenAI
from chat_log_manager import ChatLogManager

URL = "http://localhost:11434/v1/"
MODEL = "7shi/tanuki-dpo-v1.0:latest"
SAVE_DIR = "./threads"


class Chat(App):
    CSS = """
    Horizontal {
        width: 100%;
        height: 90%;
    }

    #sidebar {
        max-width: 30%
    }

    #chat-container {
        width: 70%;
        overflow: auto;
        padding: 1;
    }

    .message {
    }
    """

    def __init__(self):
        super().__init__()
        self.client = OpenAI(base_url=URL, api_key="dummy")
        self.messages = []
        self.thread_id = None
        self.log_manager = ChatLogManager(SAVE_DIR)

    def compose(self) -> ComposeResult:
        """ウィジェットを配置."""
        yield Header()
        with Horizontal():
            yield Container(ListView(id="sidebar"), id="sidebar")
            yield Container(Static(id="chat-container"), id="chat-container")
        yield Input(placeholder="Input message...", id="input-box")
        yield Footer()

    async def on_mount(self) -> None:
        """アプリ起動時の初期化."""
        self.load_saved_threads()
        self.set_focus(self.query_one("#input-box", Input))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """入力が送信されたときの処理."""

        if self.thread_id is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.thread_id = timestamp

        user_message = event.value
        if user_message.strip():
            await self.update_chat("You", [user_message])
            event.input.value = ""  # 入力ボックスをクリア
            self.refresh()
            await asyncio.sleep(0.01)
            await self.send_message_to_api(user_message)

    async def send_message_to_api(self, user_message: str) -> None:
        """OpenAI APIにメッセージを送信."""
        try:
            self.messages.append({"role": "user", "content": user_message})
            stream = self.client.chat.completions.create(
                messages=self.messages,
                model=MODEL,
                stream=True,
            )

            response = ""

            # 非同期マッピングで delta.content を取り出す
            def stream_map():
                nonlocal response
                nonlocal stream
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    response += delta
                    yield delta

            await self.update_chat("AI", stream_map())
            self.messages.append({"role": "assistant", "content": response})
            self.log_manager.save_thread(self.thread_id, self.messages)
            self.load_saved_threads()

        except Exception as e:
            await self.update_chat("ERROR", [str(e)])

    async def update_chat(self, role: str, stream):
        container = self.query_one("#chat-container", Static)
        container.update(container.renderable + f"[b]{role}:[/b] ")
        self.refresh()

        for chunk in stream:
            container.update(container.renderable + str(chunk))
            self.refresh()
            await asyncio.sleep(0.01)

        container.update(container.renderable + "\n")
        self.refresh()
        await asyncio.sleep(0.01)

    def load_saved_threads(self):
        """保存されたスレッドのリストをサイドバーに表示."""
        sidebar = self.query_one("#sidebar", ListView)
        sidebar.clear()

        for thread_id in self.log_manager.thread_id_list():
            sidebar.append(ListItem(Button(thread_id, id=f"load-{thread_id}")))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """サイドバーからスレッドを選択したときの処理."""
        button_id = event.button.id
        if button_id and button_id.startswith("load-"):
            thread_id = button_id[len("load-"):]
            self.messages = self.log_manager.load_thread(thread_id)
            await self.display_thread()
            self.thread_id = thread_id

    async def display_thread(self):
        """選択したスレッドをチャット画面に表示."""
        container = self.query_one("#chat-container", Static)
        container.update("")
        for message in self.messages:
            role = "You" if message["role"] == "user" else "AI"
            await self.update_chat(role, [message["content"]])


if __name__ == "__main__":
    Chat().run()
