from prompt_toolkit.layout import Window
from prompt_toolkit.widgets import Frame, TextArea


class SystemPromptOverlay:
    def __init__(self) -> None:
        self._text_area = TextArea(
            multiline=True,
            height=8,
            wrap_lines=True,
            scrollbar=False,
        )
        self.window = Frame(
            body=self._text_area,
            title="システムプロンプト  Ctrl+D: 保存  Esc: キャンセル  (空欄=デフォルト使用)",
        )

    def load(self, prompt: str) -> None:
        self._text_area.text = prompt

    @property
    def text(self) -> str:
        return self._text_area.text

    @property
    def control(self):
        return self._text_area.control
