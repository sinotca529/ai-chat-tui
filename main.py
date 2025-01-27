import asyncio
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Input, Static, Button, ListView, ListView, ListItem
from chat_manager import ChatManager


class ChatApp(App):
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

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        save_dir: str
    ):
        super().__init__()
        self.chat_manager = ChatManager(base_url, api_key, model, save_dir)

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
        self.display_thread_list()
        self.set_focus(self.query_one("#input-box", Input))

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
        self.refresh()
        await asyncio.sleep(0.01)

        for chunk in stream:
            container.update(container.renderable + str(chunk))
            self.refresh()
            await asyncio.sleep(0.01)

        container.update(container.renderable + "\n")
        self.refresh()
        await asyncio.sleep(0.01)

    def display_thread_list(self):
        """保存されたスレッドのリストをサイドバーに表示."""
        sidebar = self.query_one("#sidebar", ListView)
        sidebar.clear()
        for thread_id in self.chat_manager.thread_id_list():
            sidebar.append(ListItem(Button(thread_id, id=f"load-{thread_id}")))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """サイドバーからスレッドを選択したときの処理."""
        button_id = event.button.id
        if button_id and button_id.startswith("load-"):
            thread_id = button_id[len("load-"):]
            await self.display_thread(thread_id)

    async def display_thread(self, thread_id: str):
        """選択したスレッドをチャット画面に表示."""
        container = self.query_one("#chat-container", Static)
        container.update("")

        self.chat_manager.load_thread(thread_id)
        for msg in self.chat_manager.msg_list:
            role = "You" if msg["role"] == "user" else "AI"
            await self.update_chat(role, [msg["content"]])


if __name__ == "__main__":
    url = "http://localhost:11434/v1/"
    model = "7shi/tanuki-dpo-v1.0:latest"
    save_dir = "./threads"
    ChatApp(url, "dummy_api_key", model, save_dir).run()
