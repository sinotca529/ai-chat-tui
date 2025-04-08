import asyncio
from ui.tree_select_window import TreeSelectWindow
from ui.thread_view import TreeView
from textual.app import App, ComposeResult
from textual.events import Paste
from textual.widgets import Header, Footer, TextArea
from chat_tree_store import ChatTreeStore
from api_handler import ApiHandler
from chat_tree import ChatTree
from chat_tree_handler import ChatTreeHandler
from util.util import logger


class ChatApp(App):
    CSS_PATH = "../tcss/chat_app.tcss"

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
        yield TreeView(self.chat, id="chat-container")
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
                self._display_tree_list()

            case "ctrl+d":
                user_msg = await self.take_input_value()
                await self.chat(user_msg)

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

    async def chat(self, user_msg: str, thread_id: int = None) -> None:
        """チャットをする。
        user_msg:  メッセージ
        thread_id: 起点となるスレッド、つまり返信先。省略した場合、現在のスレッドの末尾に返信
        """
        if not user_msg:
            return

        user_msg = user_msg.strip()
        if not user_msg:
            return

        # スレッドの選択
        if thread_id is not None:
            self.tree_handler.set_thread_id(thread_id)
            logger(__name__).info(self.tree_handler.get_thread_id())
            await self._display_current_thread()

        thread_id = self.tree_handler.get_thread_id()

        # 兄弟ノードの取得
        siblings = self.tree_handler.get_children(thread_id)

        # チャットを実施
        user_msg_id, resp_stream = self.tree_handler.send_message(user_msg)

        # Update chat view
        thread = self.query_one("#chat-container", TreeView)
        await thread.add_user_message(user_msg, user_msg_id, siblings)
        await thread.add_assistant_message(resp_stream, user_msg_id + 1)

        # Save chat log
        self.chat_tree_sotre.save(self.tree_handler.get_tree())

    def _display_tree_list(self):
        """ツリーリストをフローティングスクリーンで表示."""
        tree_ids = self.chat_tree_sotre.tree_id_list()
        self.push_screen(
            TreeSelectWindow(tree_ids),
            self._display_default_thread
        )

    async def _display_current_thread(self):
        thread_view = self.query_one("#chat-container", TreeView)
        await thread_view.render_thread(self.tree_handler.current_thread())

    async def _display_default_thread(self, tree_id: str):
        """指定したツリーのデフォルトのスレッドを表示."""
        thread_view = self.query_one("#chat-container", TreeView)
        self.tree_handler = ChatTreeHandler(
            self.chat_tree_sotre.load(tree_id),
            self.api_handler
        )

        await thread_view.render_thread(self.tree_handler.current_thread())
