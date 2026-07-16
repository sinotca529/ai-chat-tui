from __future__ import annotations
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window, VSplit, HSplit, ScrollablePane
from prompt_toolkit.layout.containers import DynamicContainer
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from application.thread_entry import ThreadEntry
from domain.role import Role
from ui.highlight import iter_content, highlight_code

if TYPE_CHECKING:
    from application.chat_session import ChatSession


@dataclass(frozen=True)
class _RowEntry:
    """行レンダリング専用の表示データ。domain オブジェクトに依存しない。"""
    role: Role
    content: str
    sibling_index: int
    sibling_count: int
    tool_calls: tuple = ()  # (name, args_dict) のタプル列
    attachments: tuple = ()  # (ファイル名, 文字数) のタプル列

    @classmethod
    def from_thread_entry(cls, e: ThreadEntry) -> "_RowEntry":
        tool_calls: list[tuple[str, dict]] = []
        for msg in e.node.tool_messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except Exception:
                        args = {}
                    tool_calls.append((name, args))
        return cls(
            role=e.node.role,
            content=e.node.content,
            sibling_index=e.sibling_index,
            sibling_count=e.sibling_count,
            tool_calls=tuple(tool_calls),
            attachments=tuple(
                (os.path.basename(a["path"]), len(a["content"]))
                for a in e.node.attachments
            ),
        )


class AutoScrollPane(ScrollablePane):
    """`stick_to_bottom` が True の間、描画のたびに下端へスクロールする ScrollablePane。

    ScrollablePane はフォーカスされた Window がペイン内にあるときしかスクロール位置を
    調整しない。ストリーミング中はフォーカスが入力欄（ペイン外）にあるため、
    下端への追従はここで write_to_screen のたびに行う。仮想高さの計算は親クラスの
    write_to_screen と同一のロジック（スクロールバー分の幅補正を含む）を用いる。
    """

    def __init__(self, content: DynamicContainer) -> None:
        # keep_focused_window_visible は無効化する。画面より大きいメッセージに
        # フォーカスがあると「その Window の上端より上へスクロールできない」
        # 制約（min_scroll = ypos）が働き、先頭方向への手動スクロールが膠着する。
        # 可視性の管理は keep_cursor_visible（カーソル行）に一本化する。
        super().__init__(content, keep_focused_window_visible=False)
        self.stick_to_bottom = True
        # 直近の描画時のジオメトリ。手動スクロールのクランプに使う。
        # レイアウト構造（入力欄の高さ等）をここ以外が知る必要をなくす。
        self._viewport_height = 0
        self._content_height = 0

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: MouseHandlers,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        virtual_width = write_position.width - (1 if self.show_scrollbar() else 0)
        virtual_height = max(
            self.content.preferred_height(
                virtual_width, self.max_available_height
            ).preferred,
            write_position.height,
        )
        self._viewport_height = write_position.height
        self._content_height = virtual_height
        if self.stick_to_bottom:
            self.vertical_scroll = virtual_height - write_position.height
        super().write_to_screen(
            screen, mouse_handlers, write_position, parent_style, erase_bg, z_index
        )

    def scroll_line_up(self) -> None:
        self.vertical_scroll = max(0, self.vertical_scroll - 1)

    def scroll_line_down(self) -> None:
        max_scroll = max(0, self._content_height - self._viewport_height)
        self.vertical_scroll = min(self.vertical_scroll + 1, max_scroll)


_CURSOR_LINE_STYLE = "bg:#1e4272"
_FALLBACK_WIDTH = 80  # 初回描画前に幅が未確定なときの折り返し計算用
_WRAP_PREFIX_WIDTH = 2  # 折り返し継続行の get_line_prefix "  " の幅


def _wrap_starts(line: str, width: int, cont_width: int) -> list[int]:
    """論理行が折り返される各視覚行の開始文字オフセットを返す。

    prompt_toolkit の Window と同様に文字の表示幅（全角 = 2 セル）で
    折り返し位置を計算する。先頭行は width、継続行は cont_width
    （行プレフィックス分狭い）で折り返す。
    """
    if width <= _WRAP_PREFIX_WIDTH or not line:
        return [0]
    starts = [0]
    avail = width
    col = 0
    for i, ch in enumerate(line):
        w = get_cwidth(ch)
        if col + w > avail:
            starts.append(i)
            col = w
            avail = max(1, cont_width)
        else:
            col += w
    return starts


def _highlight_line(
    fragments: StyleAndTextTuples,
    target_line: int,
    start_col: int = 0,
    end_col: int | None = None,
) -> StyleAndTextTuples:
    """fragments 中の指定論理行の [start_col, end_col) 文字範囲に背景色を付ける。

    end_col が None なら行末まで。視覚行（折り返しセグメント）単位の
    カーソル表示に使う。
    """
    out: StyleAndTextTuples = []
    line = 0
    col = 0
    for style, text in fragments:
        parts = text.split("\n")
        for j, part in enumerate(parts):
            if j > 0:
                out.append((style, "\n"))
                line += 1
                col = 0
            if not part:
                continue
            if line != target_line:
                out.append((style, part))
                col += len(part)
                continue
            s = max(0, min(len(part), start_col - col))
            e = len(part) if end_col is None else max(0, min(len(part), end_col - col))
            if s > 0:
                out.append((style, part[:s]))
            if e > s:
                out.append((f"{style} {_CURSOR_LINE_STYLE}", part[s:e]))
            if e < len(part):
                out.append((style, part[e:]))
            col += len(part)
    return out


class ChatView:
    def __init__(
        self,
        session: ChatSession,
        is_browse: Callable[[], bool] | None = None,
    ) -> None:
        self._session = session
        self._entries: list[ThreadEntry] = []
        # ブラウズカーソルは (メッセージ index, 論理行, 折り返しセグメント) の
        # 3 次元。移動は視覚行単位（vim の gj/gk 相当）。
        # _cursor_msg = -1 は「選択なし」の番兵。
        self._cursor_msg: int = -1
        self._cursor_line: int = 0
        self._cursor_seg: int = 0
        self._line_counts: list[int] = []
        self._line_texts: list[list[str]] = []  # メッセージごとの論理行テキスト
        # browse 状態の単一情報源は ChatApp._mode。自前の写しは持たず、
        # 描画のたびにコールバックで参照する（手動同期による乖離を防ぐ）。
        self._is_browse = is_browse or (lambda: False)
        self._rows: list = []
        self._content_windows: list[Window] = []

        # ストリーミング中の未確定ユーザーメッセージ行（セッションから動的に読む）
        self._pending_window = Window(
            content=FormattedTextControl(text=self._get_pending_text),
            wrap_lines=True,
            get_line_prefix=lambda lineno, wrap_count: "  " if wrap_count > 0 else "",
            style=lambda: self._row_style(-2, Role.USER),
            dont_extend_height=True,
        )

        self._stream_control = FormattedTextControl(
            text=self._get_stream_text,
            focusable=True,
            get_cursor_position=self._get_stream_cursor_pos,
        )
        self._stream_window = Window(
            content=self._stream_control,
            wrap_lines=True,
            get_line_prefix=lambda lineno, wrap_count: "  " if (lineno > 0 or wrap_count > 0) else "",
            style="",
            dont_extend_height=True,
        )

        self.window = AutoScrollPane(DynamicContainer(self._get_container))

    # ── コンテナ ──────────────────────────────────────────────────────────────

    def _get_container(self):
        rows = list(self._rows)
        if self._session.pending_user_msg is not None:
            rows.append(self._pending_window)
        if self._session.streaming_text:
            rows.append(self._stream_window)
        if not rows:
            return Window(content=FormattedTextControl(lambda: [("", "")]))
        return HSplit(rows)

    # ── 公開 API ──────────────────────────────────────────────────────────────

    def update(self, entries: list[ThreadEntry]) -> None:
        self._entries = entries
        self._rows = []
        self._content_windows = []
        self._line_counts = []
        self._line_texts = []
        for i, entry in enumerate(entries):
            row_entry = _RowEntry.from_thread_entry(entry)
            row, content_win = self._build_row(i, row_entry)
            self._rows.append(row)
            self._content_windows.append(content_win)
            # 表示テキストは末尾に必ず "\n" が 1 つ付く → 最後の空要素を除いた
            # split 結果が論理行のリスト
            text = "".join(t for _, t in self._render_entry(row_entry, i))
            lines = text.split("\n")[:-1] or [""]
            self._line_texts.append(lines)
            self._line_counts.append(len(lines))
        if self._cursor_msg >= len(entries):
            self._cursor_msg = -1
            self._cursor_line = 0
            self._cursor_seg = 0
        elif self._cursor_msg >= 0:
            lines = self._line_counts[self._cursor_msg]
            self._cursor_line = min(self._cursor_line, lines)  # lines は末尾の空行
            if self._is_on_blank_line():
                self._cursor_seg = 0
            else:
                self._cursor_seg = min(
                    self._cursor_seg,
                    len(self._segments(self._cursor_msg, self._cursor_line)) - 1,
                )

    def set_follow_bottom(self, follow: bool) -> None:
        """下端オートスクロール追従の ON/OFF。"""
        self.window.stick_to_bottom = follow

    def scroll_line_up(self) -> None:
        """ビューを 1 行上へ。カーソルが画面外に出る場合は引きずる（vim の Ctrl+Y）。"""
        self.window.scroll_line_up()
        self._drag_cursor_into_view()

    def scroll_line_down(self) -> None:
        """ビューを 1 行下へ。カーソルが画面外に出る場合は引きずる（vim の Ctrl+E）。"""
        self.window.scroll_line_down()
        self._drag_cursor_into_view()

    def init_browse_cursor(self) -> None:
        """browse モード進入時、カーソル未設定なら末尾メッセージの最終視覚行に置く"""
        if self._cursor_msg < 0:
            self.move_cursor_to_bottom()

    def move_cursor_to_prev_message(self) -> None:
        """メッセージ先頭へ。既に先頭なら前のメッセージの先頭へ（vim の { 相当）"""
        if not self._entries:
            return
        if self._cursor_msg < 0:
            self._cursor_msg = len(self._entries) - 1  # 番兵からは末尾メッセージの先頭へ
        elif self._cursor_line == 0 and self._cursor_seg == 0 and self._cursor_msg > 0:
            self._cursor_msg -= 1
        self._cursor_line = 0
        self._cursor_seg = 0

    def move_cursor_to_next_message(self) -> None:
        """次のメッセージの先頭へ（vim の } 相当）。末尾メッセージでは留まる"""
        if not self._entries or self._cursor_msg < 0:
            return
        if self._cursor_msg < len(self._entries) - 1:
            self._cursor_msg += 1
            self._cursor_line = 0
            self._cursor_seg = 0

    def move_cursor_to_top(self) -> None:
        """先頭メッセージの先頭視覚行へ（vim の gg 相当）"""
        if not self._entries:
            return
        self._cursor_msg = 0
        self._cursor_line = 0
        self._cursor_seg = 0

    def move_cursor_to_bottom(self) -> None:
        """末尾メッセージの最終テキスト行へ（vim の G 相当）"""
        if not self._entries:
            return
        rows = self._visual_rows()
        # rows[-1] は末尾メッセージの空行なので、その 1 つ上のテキスト行へ
        self._set_cursor_to_row(rows, len(rows) - 2)

    def selected_entry(self) -> ThreadEntry | None:
        if 0 <= self._cursor_msg < len(self._entries):
            return self._entries[self._cursor_msg]
        return None

    def selected_content_window(self) -> Window | None:
        if 0 <= self._cursor_msg < len(self._content_windows):
            return self._content_windows[self._cursor_msg]
        return None

    def set_cursor_to_node(self, node_id: int) -> None:
        for i, e in enumerate(self._entries):
            if e.node.id == node_id:
                self._cursor_msg = i
                self._cursor_line = 0
                self._cursor_seg = 0
                return

    def last_content_window(self) -> Window | None:
        return self._content_windows[-1] if self._content_windows else None

    @property
    def stream_window(self) -> Window:
        return self._stream_window

    def move_cursor_up(self) -> None:
        """1 視覚行上へ（gj/gk 相当）。メッセージ境界は自動で越え、先頭で停止する。"""
        if not self._entries:
            return
        if self._cursor_msg < 0:
            self.init_browse_cursor()
            return
        self._set_cursor_to_row(self._visual_rows(), self._cursor_global_row() - 1)

    def move_cursor_down(self) -> None:
        """1 視覚行下へ。末尾の視覚行では留まる（vim 同様）。

        番兵（-1）にはしない: カーソルが消えるとフォーカス中 Window の
        カーソル位置が prompt_toolkit のデフォルト (0,0) に落ち、
        keep_cursor_visible がそのメッセージの先頭までビューを
        巻き戻してしまう。番兵は「ブラウズ未進入」の初期状態のみ。
        """
        if not self._entries or self._cursor_msg < 0:
            return
        self._set_cursor_to_row(self._visual_rows(), self._cursor_global_row() + 1)

    # ── 折り返し計算 ──────────────────────────────────────────────────────────

    def _content_width(self, index: int) -> int:
        """メッセージ Window の直近描画時の幅。未描画なら妥当なデフォルト。"""
        info = self._content_windows[index].render_info
        return info.window_width if info else _FALLBACK_WIDTH

    def _segments(self, msg: int, line: int) -> list[int]:
        """指定論理行の各視覚行の開始文字オフセット。"""
        width = self._content_width(msg)
        return _wrap_starts(
            self._line_texts[msg][line], width, width - _WRAP_PREFIX_WIDTH
        )

    def _clamped_seg(self, segs: list[int]) -> int:
        """端末リサイズ等でセグメント数が減った場合に備えたクランプ。"""
        return min(self._cursor_seg, len(segs) - 1)

    def _is_on_blank_line(self) -> bool:
        """カーソルがメッセージ末尾の空行（line == 論理行数）にあるか。"""
        return self._cursor_line >= self._line_counts[self._cursor_msg]

    def _visual_rows(self) -> list[tuple[int, int, int]]:
        """通し視覚行番号 → カーソル位置 (msg, line, seg) の対応表。

        メッセージ末尾の空行は (msg, 論理行数, 0) で表し、カーソルを
        置ける（移動は常に 1 視覚行ずつ）。この表の index は描画上の
        視覚行番号と一致する（整合はオラクルテスト
        test_wrap_math_matches_renderer が保証する）。
        """
        rows: list[tuple[int, int, int]] = []
        for m in range(len(self._entries)):
            for line in range(self._line_counts[m]):
                for seg in range(len(self._segments(m, line))):
                    rows.append((m, line, seg))
            rows.append((m, self._line_counts[m], 0))  # 末尾の空行
        return rows

    def _set_cursor_to_row(self, rows: list[tuple[int, int, int]], row: int) -> None:
        """指定の視覚行へ移動する。範囲外は端にクランプ。"""
        row = max(0, min(len(rows) - 1, row))
        self._cursor_msg, self._cursor_line, self._cursor_seg = rows[row]

    def _cursor_global_row(self) -> int:
        """ペイン全体の仮想スクリーンにおけるカーソルの視覚行位置。"""
        offset = 0
        for m in range(self._cursor_msg):
            # +1 は表示テキスト末尾の "\n" による空行
            offset += sum(
                len(self._segments(m, line)) for line in range(self._line_counts[m])
            ) + 1
        lines = self._line_counts[self._cursor_msg]
        rows_before = sum(
            len(self._segments(self._cursor_msg, line))
            for line in range(min(self._cursor_line, lines))
        )
        if self._is_on_blank_line():
            return offset + rows_before
        seg = self._clamped_seg(self._segments(self._cursor_msg, self._cursor_line))
        return offset + rows_before + seg

    def _drag_cursor_into_view(self) -> None:
        """カーソルがビューポート外に出ていたら、ビュー内の端の行へ移動させる。

        カーソルが画面内にあれば ScrollablePane は keep_cursor_visible で
        スクロール位置を変更しないため、手動スクロールとの衝突も解消される。
        """
        if self._cursor_msg < 0 or not self._entries:
            return
        pane = self.window
        vh = max(1, pane._viewport_height)
        scroll = pane.vertical_scroll
        max_scroll = max(0, pane._content_height - vh)
        # ScrollablePane の scroll_offsets（カーソル上下の余白）の内側まで
        # 引きずらないと、次の描画でスクロールが押し戻されてしまう。
        # コンテンツの端ではオフセットを緩和する（vim の scrolloff と同じ）。
        offsets = pane.scroll_offsets
        top = scroll + (offsets.top if scroll > 0 else 0)
        bottom = scroll + vh - 1 - (offsets.bottom if scroll < max_scroll else 0)
        row = self._cursor_global_row()
        rows = self._visual_rows()
        if row < top:
            self._set_cursor_to_row(rows, top)
        elif row > bottom:
            self._set_cursor_to_row(rows, bottom)

    def _cursor_point(self) -> Point:
        """カーソルの視覚行を表す (セグメント開始文字, 論理行) の content 座標。"""
        if self._is_on_blank_line():
            return Point(x=0, y=self._cursor_line)
        segs = self._segments(self._cursor_msg, self._cursor_line)
        return Point(x=segs[self._clamped_seg(segs)], y=self._cursor_line)

    # ── 行スタイル ────────────────────────────────────────────────────────────

    def _row_style(self, index: int, role: Role) -> str:
        if role == Role.USER:
            return "bg:#1e1e1e"
        return ""

    # ── 行構築 ────────────────────────────────────────────────────────────────

    def _build_row(self, index: int, entry: _RowEntry) -> tuple[VSplit | Window, Window]:
        content_ctrl = FormattedTextControl(
            text=lambda e=entry, i=index: self._render_entry(e, i),
            focusable=True,
            # カーソルの視覚行を ScrollablePane に伝え、行単位で可視に保たせる
            get_cursor_position=lambda i=index: (
                self._cursor_point() if (self._is_browse() and i == self._cursor_msg) else None
            ),
        )
        role = entry.role
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
                    "fg:ansiwhite" if (self._is_browse() and i == self._cursor_msg) else "fg:ansiyellow",
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

    def _render_entry(self, entry: _RowEntry, index: int) -> StyleAndTextTuples:
        result: StyleAndTextTuples = []

        if entry.role == Role.USER:
            role_style = "bold fg:ansibrightcyan"
            text_style = "fg:ansiwhite"
        else:
            role_style = "bold fg:ansibrightgreen"
            text_style = ""

        result.append((role_style, ">" if entry.role == Role.USER else "*"))
        self._render_content(result, entry.content, text_style)
        for name, args in entry.tool_calls:
            arg_str = ", ".join(f"{v}" for v in args.values())
            result.append(("fg:ansiyellow", f"\n  [{name}: {arg_str}]"))
        for name, chars in entry.attachments:
            result.append(("fg:ansiyellow", f"\n  [添付: {name} ({chars}文字)]"))
        result.append(("", "\n"))

        # 選択表示は視覚行単位: カーソルのあるセグメントの文字範囲だけ背景色を付ける。
        # update() 中の行数計測呼び出しでは _line_texts が未構築なのでスキップする
        # （追加されるのは style のみ or 最終 "\n" 後のスペース 1 つで、
        # 行数計測には影響しない）。
        if (
            self._is_browse()
            and index == self._cursor_msg
            and index < len(self._line_texts)
        ):
            if self._cursor_line >= len(self._line_texts[index]):
                # メッセージ末尾の空行にカーソルがある: 1 セルのスペースで示す
                result.append((_CURSOR_LINE_STYLE, " "))
            else:
                segs = self._segments(index, self._cursor_line)
                seg = self._clamped_seg(segs)
                start = segs[seg]
                end = segs[seg + 1] if seg + 1 < len(segs) else None
                result = _highlight_line(result, self._cursor_line, start, end)
        return result

    def _get_pending_text(self) -> StyleAndTextTuples:
        msg = self._session.pending_user_msg
        if msg is None:
            return []
        entry = _RowEntry(role=Role.USER, content=msg, sibling_index=1, sibling_count=1)
        # -2 は _cursor_index と一致しない番兵値（選択スタイルを当てないため）
        return self._render_entry(entry, -2)

    def _get_stream_text(self) -> StyleAndTextTuples:
        text = self._session.streaming_text
        return [
            ("bold fg:ansibrightgreen", "*"),
            ("", f" {text}▌\n"),
        ]

    def _get_stream_cursor_pos(self) -> Point:
        text = self._session.streaming_text
        y = f" {text}▌".count("\n")
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
