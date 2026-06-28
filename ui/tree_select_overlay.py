from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from prompt_toolkit.widgets import Frame


class TreeSelectOverlay:
    def __init__(self) -> None:
        self._trees: list[tuple[str, str]] = []  # (tree_id, title)
        self._cursor_index: int = 0
        self._confirming: bool = False

        self.control = FormattedTextControl(
            text=self._get_formatted_text,
            focusable=True,
            get_cursor_position=self._get_cursor_pos,
        )
        inner = Window(content=self.control, width=60, height=10)
        self.window = Frame(body=inner, title="ツリーを選択 (Enter: 決定 / Ctrl+T: 閉じる)")

    def load(self, trees: list[tuple[str, str]]) -> None:
        self._trees = [("", "[新規作成]")] + trees
        self._cursor_index = 0
        self._confirming = False

    def selected_id(self) -> str | None:
        """選択中の tree_id を返す。[新規作成] のとき None"""
        if not self._trees:
            return None
        tree_id, _ = self._trees[self._cursor_index]
        return None if tree_id == "" else tree_id

    def selected_label(self) -> str:
        if not self._trees:
            return ""
        tree_id, title = self._trees[self._cursor_index]
        return title if title else (tree_id[:16] if tree_id else "[新規作成]")

    def start_confirm(self) -> None:
        self._confirming = True

    def cancel_confirm(self) -> None:
        self._confirming = False

    def is_confirming(self) -> bool:
        return self._confirming

    def move_up(self) -> None:
        if self._trees and not self._confirming:
            self._cursor_index = max(0, self._cursor_index - 1)

    def move_down(self) -> None:
        if self._trees and not self._confirming:
            self._cursor_index = min(len(self._trees) - 1, self._cursor_index + 1)

    def _get_cursor_pos(self) -> Point:
        if self._confirming:
            return Point(x=0, y=0)
        return Point(x=0, y=self._cursor_index)

    def _get_formatted_text(self):
        if self._confirming:
            label = self.selected_label()
            return [
                ("bold fg:ansired", f" 「{label}」を削除しますか？\n"),
                ("", " [y] 削除  [n] キャンセル\n"),
            ]
        result = []
        for i, (tree_id, title) in enumerate(self._trees):
            label = title if title else (tree_id[:16] if tree_id else "[新規作成]")
            text = f" {label} \n"
            result.append(("reverse" if i == self._cursor_index else "", text))
        if not result:
            result.append(("", "(保存済みツリーなし)\n"))
        return result
