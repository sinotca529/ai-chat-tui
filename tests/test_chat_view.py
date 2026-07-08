from types import SimpleNamespace

from prompt_toolkit.layout import HSplit, VSplit, Window

from application.thread_entry import ThreadEntry
from domain.node import Node
from domain.role import Role
from ui.chat_view import ChatView, _RowEntry


def _entry(node_id: int, role: Role, content: str, parent_id: int | None = None,
           sibling_index: int = 1, sibling_count: int = 1,
           tool_messages: tuple = ()) -> ThreadEntry:
    return ThreadEntry(
        node=Node(id=node_id, role=role, content=content, parent_id=parent_id,
                  tool_messages=tool_messages),
        sibling_index=sibling_index,
        sibling_count=sibling_count,
    )


def _fake_session(pending: str | None = None, streaming: str = ""):
    return SimpleNamespace(pending_user_msg=pending, streaming_text=streaming)


def _view(session=None) -> ChatView:
    return ChatView(session or _fake_session())


def test_row_entry_extracts_tool_calls_from_tool_messages():
    tool_messages = (
        {"role": "assistant", "content": None,
         "tool_calls": [
             {"id": "t1", "type": "function",
              "function": {"name": "web_search", "arguments": '{"query": "気になる話題"}'}},
         ]},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    )
    entry = _RowEntry.from_thread_entry(
        _entry(1, Role.ASSISTANT, "回答", tool_messages=tool_messages)
    )
    assert entry.tool_calls == (("web_search", {"query": "気になる話題"}),)


def test_row_entry_tolerates_broken_tool_arguments():
    tool_messages = (
        {"role": "assistant", "content": None,
         "tool_calls": [
             {"id": "t1", "type": "function",
              "function": {"name": "web_search", "arguments": "{broken"}},
         ]},
    )
    entry = _RowEntry.from_thread_entry(
        _entry(1, Role.ASSISTANT, "回答", tool_messages=tool_messages)
    )
    assert entry.tool_calls == (("web_search", {}),)


def test_render_entry_appends_tool_call_line_in_yellow():
    view = _view()
    entry = _RowEntry(role=Role.ASSISTANT, content="回答", sibling_index=1,
                      sibling_count=1, tool_calls=(("web_search", {"query": "q1"}),))
    fragments = view._render_entry(entry, 0)
    tool_fragments = [(s, t) for s, t in fragments if "web_search" in t]
    assert tool_fragments == [("fg:ansiyellow", "\n  [web_search: q1]")]


def test_update_builds_one_row_per_entry():
    view = _view()
    view.update([
        _entry(0, Role.USER, "q"),
        _entry(1, Role.ASSISTANT, "a", parent_id=0),
    ])
    assert len(view._rows) == 2
    assert view.last_content_window() is view._content_windows[-1]


def test_cursor_starts_at_last_entry_and_wraps_to_sentinel():
    view = _view()
    view.update([
        _entry(0, Role.USER, "q"),
        _entry(1, Role.ASSISTANT, "a", parent_id=0),
        _entry(2, Role.USER, "q2", parent_id=1),
    ])
    view.init_browse_cursor()
    assert view.selected_entry().node.id == 2

    view.move_cursor_up()
    assert view.selected_entry().node.id == 1
    view.move_cursor_down()
    view.move_cursor_down()  # 末尾を超えると番兵 (-1) に戻り選択なしになる
    assert view.selected_entry() is None
    view.move_cursor_up()  # 番兵から上移動で末尾に復帰
    assert view.selected_entry().node.id == 2


def test_cursor_reset_when_entries_shrink():
    view = _view()
    view.update([_entry(0, Role.USER, "q"), _entry(1, Role.ASSISTANT, "a", parent_id=0)])
    view.init_browse_cursor()
    view.update([_entry(0, Role.USER, "q")])  # ブランチ切替などで行数が減る
    assert view.selected_entry() is None  # 範囲外カーソルは破棄される


def test_selection_style_follows_injected_browse_state():
    """browse 状態は外部（ChatApp._mode）が単一情報源で、ChatView は写しを持たない"""
    browse = {"on": False}
    view = ChatView(_fake_session(), is_browse=lambda: browse["on"])
    view.update([_entry(0, Role.USER, "q")])
    view.init_browse_cursor()

    assert view._row_style(0, Role.USER) == "bg:#1e1e1e"  # input 中は選択ハイライトなし
    browse["on"] = True
    assert view._row_style(0, Role.USER) == "bg:#1e4272"  # browse に入った瞬間から反映


def test_set_cursor_to_node():
    view = _view()
    view.update([_entry(0, Role.USER, "q"), _entry(1, Role.ASSISTANT, "a", parent_id=0)])
    view.set_cursor_to_node(0)
    assert view.selected_entry().node.id == 0


def test_sibling_indicator_only_for_branched_user_rows():
    view = _view()
    view.update([
        _entry(0, Role.USER, "分岐あり", sibling_index=2, sibling_count=3),
        _entry(1, Role.ASSISTANT, "a", parent_id=0),
    ])
    # 分岐ありユーザー行は VSplit（本文 + [n/m] インジケータ）、それ以外は Window 単体
    assert isinstance(view._rows[0], VSplit)
    assert isinstance(view._rows[1], Window)


def test_container_appends_pending_and_stream_windows():
    session = _fake_session()
    view = ChatView(session)
    view.update([_entry(0, Role.USER, "q")])

    container = view._get_container()
    assert isinstance(container, HSplit)
    assert len(container.children) == 1

    session.pending_user_msg = "送信中メッセージ"
    session.streaming_text = "スト"
    container = view._get_container()
    # 既存行 + pending 行 + ストリーミング行
    assert len(container.children) == 3
