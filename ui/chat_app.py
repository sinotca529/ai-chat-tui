import asyncio
from ui.thread_select_window import ThreadSelectWindow
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Input, Static
from chat_manager import ChatManager


class ChatApp(App):
    CSS = """
    #chat-container {
        width: 100%;
        height: 85%;
        overflow: auto;
        padding: 1;
    }

    Input {
        width: 100%;
        height: auto;
        padding: 1;
    }

    Footer {
    }

    .message {
        padding: 1;
        margin-bottom: 1;
    }

    .message.user {
        color: blue;
        background: lightblue;
    }

    .message.ai {
        color: green;
        background: lightgreen;
    }
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        save_dir: str
    ):
        super().__init__()
        self.chat_manager = ChatManager(base_url, api_key, model, save_dir)
        self.show_floating = False

    def compose(self) -> ComposeResult:
        """ウィジェットを配置."""
        yield Header()
        yield Container(Static(id="chat-container"), id="chat-container")
        yield Input(placeholder="Input message...", id="input-box")
        yield Footer()

    async def on_mount(self) -> None:
        """アプリ起動時の初期化."""
        self.set_focus(self.query_one("#input-box", Input))

    def on_key(self, event) -> None:
        """ショートカットキーでフローティングウィンドウをトグル."""
        if event.key == "ctrl+t":
            self.display_thread_list()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """入力が送信されたときの処理."""

        user_message = event.value
        if user_message.strip():
            # show user message
            await self.update_chat("You", [user_message])
            event.input.value = ""  # clear input box
            self.refresh()
            await asyncio.sleep(0.01)

            # send message to API and show response
            response = self.chat_manager.send_message(user_message)
            await self.update_chat("AI", response)

            # update sidebar
            self.display_thread_list()

    async def update_chat(self, role: str, stream):
        container = self.query_one("#chat-container", Static)
        container.update(container.renderable + f"[b]{role}:[/b] ")
        container.refresh()
        await asyncio.sleep(0.01)

        for chunk in stream:
            container.update(container.renderable + str(chunk))
            container.refresh()
            await asyncio.sleep(0.01)

        container.update(container.renderable + "\n")
        container.refresh()
        await asyncio.sleep(0.01)

    def display_thread_list(self):
        """スレッドリストをフローティングスクリーンで表示."""
        thread_ids = self.chat_manager.thread_id_list()
        self.push_screen(ThreadSelectWindow(thread_ids), self.display_thread)

    async def display_thread(self, thread_id: str):
        """選択したスレッドをチャット画面に表示."""
        container = self.query_one("#chat-container", Static)
        container.update("")

        self.chat_manager.load_thread(thread_id)
        for msg in self.chat_manager.msg_list:
            role = "You" if msg["role"] == "user" else "AI"
            await self.update_chat(role, [msg["content"]])
