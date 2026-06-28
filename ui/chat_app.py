import asyncio

from prompt_toolkit import Application
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, FloatContainer, Float, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.styles import merge_styles
from prompt_toolkit.styles.pygments import style_from_pygments_cls
from prompt_toolkit.widgets import TextArea
from pygments.styles import get_style_by_name

from application.chat_session import ChatSession
from ui.chat_view import ChatView
from ui.tree_select_overlay import TreeSelectOverlay
from ui.model_select_overlay import ModelSelectOverlay


class ChatApp:
    def __init__(self, session: ChatSession) -> None:
        self._session = session
        self._mode = "input"  # "input" | "browse" | "tree_overlay" | "model_overlay"
        self._streaming = False
        self._branch_target_id: int | None = None

        self._chat_view = ChatView()
        self._tree_overlay = TreeSelectOverlay()
        self._model_overlay = ModelSelectOverlay()
        self._stream_task: asyncio.Task | None = None
        self._pending_message: str = ""

        self._input_area = TextArea(
            multiline=True,
            height=8,
            scrollbar=False,
            wrap_lines=True,
            get_line_prefix=self._input_prefix,
        )

        self._app = self._build_app()
        self._refresh_chat_view()

    def _build_app(self) -> Application:
        kb = self._build_keybindings()
        layout = self._build_layout()
        style = merge_styles([
            style_from_pygments_cls(get_style_by_name("monokai")),
        ])
        app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            mouse_support=False,
            style=style,
            color_depth=ColorDepth.TRUE_COLOR,
        )
        app.ttimeoutlen = 0.05
        return app

    def _build_layout(self) -> Layout:
        is_tree_overlay = Condition(lambda: self._mode == "tree_overlay")
        is_model_overlay = Condition(lambda: self._mode == "model_overlay")

        root = FloatContainer(
            content=HSplit([
                self._chat_view.window,
                Window(height=1, char="─"),
                self._input_area,
            ]),
            floats=[
                Float(
                    content=ConditionalContainer(
                        content=self._tree_overlay.window,
                        filter=is_tree_overlay,
                    ),
                    xcursor=False,
                    ycursor=False,
                ),
                Float(
                    content=ConditionalContainer(
                        content=self._model_overlay.window,
                        filter=is_model_overlay,
                    ),
                    xcursor=False,
                    ycursor=False,
                ),
            ],
        )

        return Layout(root, focused_element=self._input_area)

    def _build_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        is_input = Condition(lambda: self._mode == "input")
        is_browse = Condition(lambda: self._mode == "browse")
        is_tree_overlay = Condition(lambda: self._mode == "tree_overlay")
        is_model_overlay = Condition(lambda: self._mode == "model_overlay")
        is_any_overlay = is_tree_overlay | is_model_overlay
        is_tree_confirming = Condition(lambda: self._tree_overlay.is_confirming())
        is_streaming = Condition(lambda: self._streaming)
        not_streaming = ~is_streaming

        @kb.add("c-c", filter=is_streaming)
        def _cancel_stream(event):
            if self._stream_task and not self._stream_task.done():
                self._stream_task.cancel()

        @kb.add("c-c", filter=~is_streaming)
        @kb.add("c-q")
        def _quit(event):
            event.app.exit()

        @kb.add("c-a", filter=is_input)
        def _beginning_of_line(event):
            buf = event.current_buffer
            buf.cursor_position += buf.document.get_start_of_line_position(after_whitespace=False)

        @kb.add("c-e", filter=is_input)
        def _end_of_line(event):
            buf = event.current_buffer
            buf.cursor_position += buf.document.get_end_of_line_position()

        @kb.add("c-k", filter=is_input)
        def _kill_line(event):
            buf = event.current_buffer
            pos = buf.document.get_end_of_line_position()
            buf.delete(count=pos if pos else 1)

        @kb.add("c-u", filter=is_input)
        def _kill_line_backward(event):
            buf = event.current_buffer
            pos = buf.document.get_start_of_line_position(after_whitespace=False)
            buf.delete_before_cursor(count=-pos)

        @kb.add("c-d", filter=is_input & not_streaming)
        def _send(event):
            msg = self._input_area.text.strip()
            if not msg:
                return
            self._input_area.text = ""
            self._streaming = True
            if self._branch_target_id is not None:
                self._session.navigate_to(self._branch_target_id)
                self._branch_target_id = None
            self._pending_message = msg
            self._chat_view.start_streaming(msg)
            event.app.layout.focus(self._chat_view.stream_window)
            self._stream_task = asyncio.ensure_future(self._do_stream(msg))

        @kb.add("tab", filter=is_input)
        def _to_browse(event):
            self._mode = "browse"
            self._chat_view.set_browse_mode(True)
            win = self._chat_view.selected_content_window()
            if win:
                event.app.layout.focus(win)

        @kb.add("escape", filter=is_input)
        def _cancel_branch(event):
            if self._branch_target_id is not None:
                self._branch_target_id = None
                self._input_area.text = ""

        @kb.add("tab", filter=is_browse)
        @kb.add("escape", filter=is_browse)
        def _to_input(event):
            self._mode = "input"
            self._chat_view.set_browse_mode(False)
            event.app.layout.focus(self._input_area)

        @kb.add("up", filter=is_browse)
        @kb.add("k", filter=is_browse)
        def _browse_up(event):
            self._chat_view.move_cursor_up()
            win = self._chat_view.selected_content_window()
            if win:
                event.app.layout.focus(win)

        @kb.add("down", filter=is_browse)
        @kb.add("j", filter=is_browse)
        def _browse_down(event):
            self._chat_view.move_cursor_down()
            win = self._chat_view.selected_content_window()
            if win:
                event.app.layout.focus(win)

        @kb.add("left", filter=is_browse)
        @kb.add("h", filter=is_browse)
        def _sibling_prev(event):
            self._switch_sibling(-1)

        @kb.add("right", filter=is_browse)
        @kb.add("l", filter=is_browse)
        def _sibling_next(event):
            self._switch_sibling(1)

        @kb.add("e", filter=is_browse & not_streaming)
        def _branch_edit(event):
            entry = self._chat_view.selected_entry()
            if entry is None or entry.node.role.value != "user":
                return
            self._input_area.text = entry.node.content
            self._branch_target_id = entry.node.parent_id
            self._mode = "input"
            self._chat_view.set_browse_mode(False)
            event.app.layout.focus(self._input_area)

        # ツリー選択オーバーレイ
        @kb.add("c-t", filter=~is_any_overlay)
        def _open_tree_overlay(event):
            trees = self._session.list_trees()
            self._tree_overlay.load(trees)
            self._mode = "tree_overlay"
            event.app.layout.focus(self._tree_overlay.control)

        @kb.add("c-t", filter=is_tree_overlay)
        def _close_tree_overlay(event):
            self._mode = "input"
            event.app.layout.focus(self._input_area)

        @kb.add("up", filter=is_tree_overlay)
        def _tree_up(event):
            self._tree_overlay.move_up()

        @kb.add("down", filter=is_tree_overlay)
        def _tree_down(event):
            self._tree_overlay.move_down()

        @kb.add("enter", filter=is_tree_overlay & ~is_tree_confirming)
        def _tree_select(event):
            tree_id = self._tree_overlay.selected_id()
            if tree_id is None:
                self._session.new_tree()
            else:
                self._session.load_tree(tree_id)
            self._branch_target_id = None
            self._mode = "input"
            self._chat_view.set_browse_mode(False)
            self._refresh_chat_view()
            event.app.layout.focus(self._input_area)

        @kb.add("d", filter=is_tree_overlay & ~is_tree_confirming)
        def _tree_delete_start(event):
            if self._tree_overlay.selected_id() is not None:
                self._tree_overlay.start_confirm()

        @kb.add("y", filter=is_tree_confirming)
        def _tree_delete_confirm(event):
            tree_id = self._tree_overlay.selected_id()
            if tree_id is not None:
                switched = self._session.delete_tree(tree_id)
                if switched:
                    self._refresh_chat_view()
            self._tree_overlay.load(self._session.list_trees())

        @kb.add("n", filter=is_tree_confirming)
        @kb.add("escape", filter=is_tree_confirming)
        def _tree_delete_cancel(event):
            self._tree_overlay.cancel_confirm()

        # モデル選択オーバーレイ
        @kb.add("c-o", filter=~is_any_overlay)
        def _open_model_overlay(event):
            self._model_overlay.start_loading(self._session.current_model)
            self._mode = "model_overlay"
            event.app.layout.focus(self._model_overlay.control)
            asyncio.ensure_future(self._load_models())

        @kb.add("c-o", filter=is_model_overlay)
        def _close_model_overlay(event):
            self._mode = "input"
            event.app.layout.focus(self._input_area)

        @kb.add("up", filter=is_model_overlay)
        def _model_up(event):
            self._model_overlay.move_up()

        @kb.add("down", filter=is_model_overlay)
        def _model_down(event):
            self._model_overlay.move_down()

        @kb.add("enter", filter=is_model_overlay)
        def _model_select(event):
            model_id = self._model_overlay.selected_model()
            if model_id is not None:
                self._session.set_model(model_id)
            self._mode = "input"
            event.app.layout.focus(self._input_area)

        return kb

    def _switch_sibling(self, direction: int) -> None:
        entry = self._chat_view.selected_entry()
        if entry is None:
            return
        siblings = self._session.siblings_of(entry.node.id)
        if len(siblings) <= 1:
            return
        current_pos = siblings.index(entry.node.id)
        next_sibling_id = siblings[(current_pos + direction) % len(siblings)]
        self._session.navigate_to_branch_end(next_sibling_id)
        self._refresh_chat_view()
        entries = self._chat_view._entries
        for i, e in enumerate(entries):
            if e.node.id == next_sibling_id:
                self._chat_view._cursor_index = i
                break

    def _input_prefix(self, lineno: int, wrap_count: int):
        if lineno == 0 and wrap_count == 0:
            if self._branch_target_id is not None:
                return [("fg:ansiyellow bold", "e ")]
            return [("", "> ")]
        return [("", "  ")]

    def _refresh_chat_view(self) -> None:
        entries = self._session.current_thread()
        self._chat_view.update(entries)

    async def _do_stream(self, msg: str) -> None:
        try:
            async for chunk in self._session.send_message(msg):
                self._chat_view.append_chunk(chunk)
                self._app.invalidate()
            self._refresh_chat_view()
            last_win = self._chat_view.last_content_window()
            if last_win:
                self._app.layout.focus(last_win)
            if not self._session.title:
                asyncio.ensure_future(self._auto_title())
        except asyncio.CancelledError:
            self._session.rollback_last_user_message()
            self._input_area.text = self._pending_message
            self._refresh_chat_view()
        except Exception as e:
            self._chat_view.append_chunk(f"\n[エラー: {e}]")
        finally:
            self._streaming = False
            self._stream_task = None
            self._app.invalidate()
            self._app.layout.focus(self._input_area)

    async def _auto_title(self) -> None:
        try:
            await self._session.generate_title()
        except Exception:
            pass

    async def _load_models(self) -> None:
        try:
            models = await self._session.list_models()
            self._model_overlay.load(models, self._session.current_model)
        except Exception as e:
            self._model_overlay.set_error(str(e))
        finally:
            self._app.invalidate()

    async def run(self) -> None:
        await self._app.run_async()
