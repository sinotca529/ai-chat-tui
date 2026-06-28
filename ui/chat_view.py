from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from application.thread_entry import ThreadEntry
from domain.role import Role
from ui.highlight import iter_content, highlight_code


class ChatView:
    def __init__(self) -> None:
        self._entries: list[ThreadEntry] = []
        self._streaming_text: str = ""
        self._cursor_index: int = -1  # -1 = 末尾（最新メッセージ）
        self._browse_mode: bool = False

        self.control = FormattedTextControl(
            text=self._get_formatted_text,
            focusable=True,
            get_cursor_position=self._get_cursor_pos,
        )
        self.window = Window(
            content=self.control,
            wrap_lines=True,
            get_line_prefix=lambda lineno, wrap_count: "  " if wrap_count > 0 else "",
        )

    def update(self, entries: list[ThreadEntry]) -> None:
        self._entries = entries
        self._streaming_text = ""
        if self._cursor_index >= len(entries):
            self._cursor_index = -1

    def start_streaming(self, user_msg: str) -> None:
        from domain.node import Node
        fake_node = Node(id=-1, role=Role.USER, content=user_msg, parent_id=None)
        fake_entry = ThreadEntry(node=fake_node, sibling_index=1, sibling_count=1)
        self._entries = self._entries + [fake_entry]
        self._streaming_text = ""

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

    def _entry_start_line(self, index: int) -> int:
        y = 0
        for i in range(index):
            y += self._entries[i].node.content.count("\n") + 1
        return y

    def _get_cursor_pos(self) -> Point:
        if not self._entries:
            return Point(x=0, y=0)

        if self._browse_mode and 0 <= self._cursor_index < len(self._entries):
            return Point(x=0, y=self._entry_start_line(self._cursor_index))

        total = sum(e.node.content.count("\n") + 1 for e in self._entries)
        if self._streaming_text:
            total += self._streaming_text.count("\n") + 1
        return Point(x=0, y=max(0, total - 1))

    def _get_formatted_text(self) -> StyleAndTextTuples:
        result: StyleAndTextTuples = []
        for i, entry in enumerate(self._entries):
            is_selected = self._browse_mode and i == self._cursor_index

            if entry.node.role == Role.USER:
                role_style = "bold fg:ansiwhite" if is_selected else "bold fg:ansibrightcyan"
                text_style = "fg:ansiwhite" if is_selected else ""
            else:
                role_style = "bold fg:ansiwhite" if is_selected else "bold fg:ansibrightgreen"
                text_style = "fg:ansiwhite" if is_selected else ""

            indicator = (
                f"  [{entry.sibling_index}/{entry.sibling_count}]"
                if entry.node.role == Role.USER and entry.sibling_count > 1
                else ""
            )
            ind_style = text_style if is_selected else "fg:ansiyellow"

            result.append((role_style, ">" if entry.node.role == Role.USER else "*"))
            self._render_content(result, entry.node.content, text_style)
            if indicator:
                result.append((ind_style, indicator))
            result.append(("", "\n"))

        if self._streaming_text:
            result.append(("bold fg:ansibrightgreen", "*"))
            result.append(("", f" {self._streaming_text}▌\n"))

        if not result:
            result.append(("", ""))

        return result

    def _render_content(
        self,
        result: StyleAndTextTuples,
        content: str,
        text_style: str,
    ) -> None:
        """content をコードブロックを識別しながら result へ追加する"""
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
