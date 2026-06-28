from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window, VSplit, HSplit, ScrollablePane
from prompt_toolkit.layout.containers import DynamicContainer
from application.thread_entry import ThreadEntry
from domain.role import Role
from ui.highlight import iter_content, highlight_code


class ChatView:
    def __init__(self) -> None:
        self._entries: list[ThreadEntry] = []
        self._streaming_text: str = ""
        self._cursor_index: int = -1
        self._browse_mode: bool = False

        self._rows: list = []
        self._content_windows: list[Window] = []
        self._is_streaming: bool = False

        self._stream_control = FormattedTextControl(
            text=self._get_stream_text,
            focusable=True,
            get_cursor_position=self._get_stream_cursor_pos,
        )
        self._stream_window = Window(
            content=self._stream_control,
            wrap_lines=True,
            get_line_prefix=lambda lineno, wrap_count: "  " if wrap_count > 0 else "",
            style="",
            dont_extend_height=True,
        )

        self.window = ScrollablePane(DynamicContainer(self._get_container))

    # ── コンテナ ──────────────────────────────────────────────────────────────

    def _get_container(self):
        rows = list(self._rows)
        if self._is_streaming:
            rows.append(self._stream_window)
        if not rows:
            return Window(content=FormattedTextControl(lambda: [("", "")]))
        return HSplit(rows)

    # ── 公開 API ──────────────────────────────────────────────────────────────

    def update(self, entries: list[ThreadEntry]) -> None:
        self._entries = entries
        self._streaming_text = ""
        self._is_streaming = False
        self._rows = []
        self._content_windows = []
        for i, entry in enumerate(entries):
            row, content_win = self._build_row(i, entry)
            self._rows.append(row)
            self._content_windows.append(content_win)
        if self._cursor_index >= len(entries):
            self._cursor_index = -1

    def start_streaming(self, user_msg: str) -> None:
        from domain.node import Node
        fake_node = Node(id=-1, role=Role.USER, content=user_msg, parent_id=None)
        fake_entry = ThreadEntry(node=fake_node, sibling_index=1, sibling_count=1)
        row, content_win = self._build_row(len(self._rows), fake_entry)
        self._rows.append(row)
        self._content_windows.append(content_win)
        self._entries = self._entries + [fake_entry]
        self._streaming_text = ""
        self._is_streaming = True

    def append_chunk(self, chunk: str) -> None:
        self._streaming_text += chunk

    def set_browse_mode(self, enabled: bool) -> None:
        self._browse_mode = enabled
        if enabled and self._cursor_index < 0:
            self._cursor_index = max(0, len(self._entries) - 1)

    def selected_entry(self) -> ThreadEntry | None:
        if 0 <= self._cursor_index < len(self._entries):
            return self._entries[self._cursor_index]
        return None

    def selected_content_window(self) -> Window | None:
        if 0 <= self._cursor_index < len(self._content_windows):
            return self._content_windows[self._cursor_index]
        return None

    @property
    def stream_window(self) -> Window:
        return self._stream_window

    def move_cursor_up(self) -> None:
        if not self._entries:
            return
        if self._cursor_index < 0:
            self._cursor_index = len(self._entries) - 1
        else:
            self._cursor_index = max(0, self._cursor_index - 1)

    def move_cursor_down(self) -> None:
        if not self._entries:
            return
        if self._cursor_index >= 0:
            next_idx = self._cursor_index + 1
            if next_idx >= len(self._entries):
                self._cursor_index = -1
            else:
                self._cursor_index = next_idx

    # ── 行スタイル ────────────────────────────────────────────────────────────

    def _row_style(self, index: int, role: Role) -> str:
        if self._browse_mode and index == self._cursor_index:
            return "bg:#1e4272"
        if role == Role.USER:
            return "bg:#1e1e1e"
        return ""

    # ── 行構築 ────────────────────────────────────────────────────────────────

    def _build_row(self, index: int, entry: ThreadEntry) -> tuple:
        content_ctrl = FormattedTextControl(
            text=lambda e=entry, i=index: self._render_entry(e, i),
            focusable=True,
        )
        role = entry.node.role
        content_win = Window(
            content=content_ctrl,
            wrap_lines=True,
            get_line_prefix=lambda lineno, wrap_count: "  " if wrap_count > 0 else "",
            style=lambda i=index, r=role: self._row_style(i, r),
            dont_extend_height=True,
        )

        if role == Role.USER and entry.sibling_count > 1:
            ind_text = f"[{entry.sibling_index}/{entry.sibling_count}]"
            ind_ctrl = FormattedTextControl(
                text=lambda e=entry, i=index: [(
                    "fg:ansiwhite" if (self._browse_mode and i == self._cursor_index) else "fg:ansiyellow",
                    f"[{e.sibling_index}/{e.sibling_count}]",
                )],
            )
            ind_win = Window(
                content=ind_ctrl,
                width=len(ind_text),
                dont_extend_width=True,
                style=lambda i=index, r=role: self._row_style(i, r),
            )
            return VSplit([content_win, ind_win]), content_win

        return content_win, content_win

    # ── レンダリング ──────────────────────────────────────────────────────────

    def _render_entry(self, entry: ThreadEntry, index: int) -> StyleAndTextTuples:
        result: StyleAndTextTuples = []
        is_selected = self._browse_mode and index == self._cursor_index

        if entry.node.role == Role.USER:
            role_style = "bold fg:ansiwhite" if is_selected else "bold fg:ansibrightcyan"
            text_style = "fg:ansiwhite"
        else:
            role_style = "bold fg:ansiwhite" if is_selected else "bold fg:ansibrightgreen"
            text_style = "fg:ansiwhite" if is_selected else ""

        result.append((role_style, ">" if entry.node.role == Role.USER else "*"))
        self._render_content(result, entry.node.content, text_style)
        result.append(("", "\n"))
        return result

    def _get_stream_text(self) -> StyleAndTextTuples:
        return [
            ("bold fg:ansibrightgreen", "*"),
            ("", f" {self._streaming_text}▌\n"),
        ]

    def _get_stream_cursor_pos(self) -> Point:
        y = f" {self._streaming_text}▌".count("\n")
        return Point(x=0, y=y)

    def _render_content(
        self,
        result: StyleAndTextTuples,
        content: str,
        text_style: str,
    ) -> None:
        first_segment = True

        for is_code, lang, text in iter_content(content):
            if is_code:
                code = text if text.endswith("\n") else text + "\n"
                result.append(("", "\n  "))
                for tok_style, tok_text in highlight_code(code, lang):
                    result.append((tok_style, tok_text.replace("\n", "\n  ")))
                first_segment = False
            else:
                lines = text.split("\n")
                for j, line in enumerate(lines):
                    if j == 0 and first_segment:
                        result.append((text_style, f" {line}"))
                    elif j == 0:
                        result.append((text_style, line))
                    else:
                        result.append((text_style, f"\n  {line}"))
                first_segment = False
