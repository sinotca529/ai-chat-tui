import asyncio
from role import Role
from ui.thread_select_window import ThreadSelectWindow
from ui.thread_view import ThreadView
from textual.app import App, ComposeResult
from textual.events import Paste
from textual.widgets import Header, Footer, TextArea
from chat_manager import ChatManager


class ChatApp(App):
    CSS = """
    #chat-container {
        width: 100%;
        height: 85%;
        overflow: auto;
        padding: 1;
        background: black;
    }

    ListItem {
        margin-bottom: 1
    }

    .role {
        width: 5;
    }

    .assistant {
        color: lightgreen;
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
        yield ThreadView(id="chat-container")
        yield TextArea(id="input-box")
        yield Footer()

    async def on_mount(self) -> None:
        """アプリ起動時の初期化."""
        self.set_focus(self.query_one("#input-box", TextArea))

    async def on_key(self, event) -> None:
        """ショートカットキーでフローティングウィンドウをトグル."""
        if event.key == "ctrl+t":
            self.display_thread_list()
        if event.key == "tab":
            user_message = await self.take_input_value()
            await self.chat(user_message)

    def on_paste(self, event: Paste) -> None:
        """クリップボードの内容をテキストエリアに貼り付け"""
        with open('log', 'w') as f:
            print(event.text, file=f)
        input_box = self.query_one("#input-box", TextArea)
        input_box.text += event.text

    async def take_input_value(self) -> str:
        input_box = self.query_one("#input-box", TextArea)
        user_message = input_box.text
        input_box.text = ""
        input_box.refresh()
        await asyncio.sleep(0.01)
        return user_message

    async def chat(self, user_message: str) -> None:
        if user_message:
            user_message = user_message.strip()

            thread = self.query_one("#chat-container", ThreadView)
            response = self.chat_manager.send_message(user_message)

            await thread.update_chat(Role.USER, [user_message])
            await thread.update_chat(Role.ASSISTANT, response)

    def display_thread_list(self):
        """スレッドリストをフローティングスクリーンで表示."""
        thread_ids = self.chat_manager.thread_id_list()
        self.push_screen(ThreadSelectWindow(thread_ids), self.display_thread)

    async def display_thread(self, thread_id: str):
        """選択したスレッドをチャット画面に表示."""
        container = self.query_one("#chat-container", ThreadView)
        container.clear()

        self.chat_manager.load_thread(thread_id)
        for msg in self.chat_manager.msg_list:
            role = Role.USER if msg["role"] == "user" else Role.ASSISTANT
            thread = self.query_one("#chat-container", ThreadView)
            await thread.update_chat(role, [msg["content"]])
