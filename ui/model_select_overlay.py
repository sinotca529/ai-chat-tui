from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from prompt_toolkit.widgets import Frame


class ModelSelectOverlay:
    def __init__(self) -> None:
        self._models: list[str] = []
        self._cursor_index: int = 0
        self._loading: bool = False
        self._error: str | None = None
        self._current_model: str = ""

        self.control = FormattedTextControl(
            text=self._get_formatted_text,
            focusable=True,
            get_cursor_position=self._get_cursor_pos,
        )
        inner = Window(content=self.control, width=60, height=10)
        self.window = Frame(body=inner, title="モデルを選択 (Enter: 決定 / Ctrl+O: 閉じる)")

    def start_loading(self, current_model: str) -> None:
        self._loading = True
        self._error = None
        self._models = []
        self._current_model = current_model
        self._cursor_index = 0

    def load(self, models: list[str], current_model: str) -> None:
        self._loading = False
        self._error = None
        self._models = models
        self._current_model = current_model
        self._cursor_index = models.index(current_model) if current_model in models else 0

    def set_error(self, message: str) -> None:
        self._loading = False
        self._error = message

    def selected_model(self) -> str | None:
        if not self._models or not (0 <= self._cursor_index < len(self._models)):
            return None
        return self._models[self._cursor_index]

    def move_up(self) -> None:
        if self._models:
            self._cursor_index = max(0, self._cursor_index - 1)

    def move_down(self) -> None:
        if self._models:
            self._cursor_index = min(len(self._models) - 1, self._cursor_index + 1)

    def _get_cursor_pos(self) -> Point:
        return Point(x=0, y=self._cursor_index)

    def _get_formatted_text(self):
        if self._loading:
            return [("", "読み込み中...\n")]
        if self._error:
            return [("fg:ansired", f"エラー: {self._error}\n")]
        result = []
        for i, model_id in enumerate(self._models):
            marker = " * " if model_id == self._current_model else "   "
            text = f"{marker}{model_id} \n"
            result.append(("reverse" if i == self._cursor_index else "", text))
        if not result:
            result.append(("", "(モデルなし)\n"))
        return result
