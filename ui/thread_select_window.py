from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import ListView, ListItem, Label


class ThreadSelectWindow(ModalScreen[str]):
    CSS = """
    ThreadSelectWindow {
        align: center middle;
    }
    ListView {
        width: 80%;
        height: 80%;
    }
    ListItem {
        width: 100%;
    }
    """

    def __init__(self, thread_ids: list[str]):
        super().__init__()
        self.thread_ids = thread_ids

    def compose(self) -> ComposeResult:
        """フローティングスクリーンのUI."""
        yield Label("Select Thread...")
        yield ListView(*[
            ListItem(Label(thread_id), id=f"load-{thread_id}")
            for thread_id in self.thread_ids
        ])

    async def on_list_view_selected(self, msg: ListView.Selected) -> None:
        label_id = msg.item.id
        if label_id and label_id.startswith("load-"):
            thread_id = label_id[len("load-"):]
            self.dismiss(thread_id)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()
