import asyncio
from ui.thread_select_window import ThreadSelectWindow
from ui.thread_view import TreeView
from textual.app import App, ComposeResult
from textual.events import Paste
from textual.widgets import Header, Footer, TextArea
from chat_tree_store import ChatTreeStore
from api_handler import ApiHandler
from chat_tree import ChatTree
from chat_tree_handler import ChatTreeHandler


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

    .msg {
        height: auto;
        border: none;
        background: transparent;
    }

    .assistant {
        color: lightgreen;
    }

    .siblings {
        color: gray;
        text-align: right;
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
        self.chat_tree_sotre = ChatTreeStore(save_dir)
        self.api_handler = ApiHandler(base_url, api_key, model)
        self.tree_handler = ChatTreeHandler(ChatTree.new(), self.api_handler)

    def compose(self) -> ComposeResult:
        """ウィジェットを配置."""
        yield Header()
        yield TreeView(id="chat-container")
        yield TextArea(id="input-box")
        yield Footer()

    async def on_mount(self) -> None:
        """アプリ起動時の初期化."""
        self.set_focus(self.query_one("#input-box", TextArea))

    async def on_key(self, event) -> None:
        match event.key:
            case "ctrl+c":
                self.exit()

            case "ctrl+t":
                self.display_thread_list()

            case "ctrl+d":
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

    async def chat(self, user_msg: str) -> None:
        if not user_msg:
            return
        user_msg = user_msg.strip()
        if not user_msg:
            return

        # Do chat
        user_msg_id, resp_stream = self.tree_handler.send_message(user_msg)

        # Update chat view
        thread = self.query_one("#chat-container", TreeView)
        await thread.add_user_message(user_msg, user_msg_id, [])
        await thread.add_assistant_message(resp_stream)

        # Save chat log
        self.chat_tree_sotre.save(self.tree_handler.tree)

    def display_thread_list(self):
        """スレッドリストをフローティングスクリーンで表示."""
        thread_ids = self.chat_tree_sotre.tree_id_list()
        self.push_screen(ThreadSelectWindow(thread_ids), self.display_thread)

    async def display_thread(self, thread_id: str):
        """選択したスレッドをチャット画面に表示."""
        thread_view = self.query_one("#chat-container", TreeView)
        self.tree_handler = ChatTreeHandler(
            self.chat_tree_sotre.load(thread_id),
            self.api_handler
        )
        await thread_view.render_thread(self.tree_handler.current_thread())
