from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from prompt_toolkit.widgets import Frame


class TreeSelectOverlay:
    def __init__(self) -> None:
        self._tree_ids: list[str] = []
        self._cursor_index: int = 0

        self.control = FormattedTextControl(
            text=self._get_formatted_text,
            focusable=True,
            get_cursor_position=self._get_cursor_pos,
        )
        inner = Window(content=self.control, width=60, height=10)
        self.window = Frame(body=inner, title="ツリーを選択 (Enter: 決定 / Ctrl+T: 閉じる)")

    def load(self, tree_ids: list[str]) -> None:
        self._tree_ids = ["[新規作成]"] + tree_ids
        self._cursor_index = 0

    def selected_id(self) -> str | None:
        """選択中の項目を返す。[新規作成] のとき None"""
        if not self._tree_ids:
            return None
        item = self._tree_ids[self._cursor_index]
        return None if item == "[新規作成]" else item

    def move_up(self) -> None:
        if self._tree_ids:
            self._cursor_index = max(0, self._cursor_index - 1)

    def move_down(self) -> None:
        if self._tree_ids:
            self._cursor_index = min(len(self._tree_ids) - 1, self._cursor_index + 1)

    def _get_cursor_pos(self) -> Point:
        return Point(x=0, y=self._cursor_index)

    def _get_formatted_text(self):
        result = []
        for i, tid in enumerate(self._tree_ids):
            if i == self._cursor_index:
                result.append(("reverse", f" {tid} \n"))
            else:
                result.append(("", f" {tid} \n"))
        if not result:
            result.append(("", "(保存済みツリーなし)\n"))
        return result
