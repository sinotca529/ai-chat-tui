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


def test_wrap_starts_ascii():
    from ui.chat_view import _wrap_starts
    # 先頭行 10 セル、継続行 8 セル
    assert _wrap_starts("a" * 25, 10, 8) == [0, 10, 18]


def test_wrap_starts_cjk_double_width():
    from ui.chat_view import _wrap_starts
    # 全角は 2 セル: 先頭行に 5 文字（10 セル）
    assert _wrap_starts("あ" * 8, 10, 8) == [0, 5]


def test_wrap_starts_cjk_never_splits_across_boundary():
    from ui.chat_view import _wrap_starts
    # 全角文字はセル境界をまたがず丸ごと次の視覚行へ送られる
    assert _wrap_starts("aaaああ", 5, 5) == [0, 4]


def test_wrap_starts_short_empty_and_narrow():
    from ui.chat_view import _wrap_starts
    assert _wrap_starts("short", 80, 78) == [0]
    assert _wrap_starts("", 80, 78) == [0]
    assert _wrap_starts("whatever", 2, 0) == [0]  # 幅が狭すぎる場合は折り返さない


def test_visual_line_movement_within_wrapped_line(monkeypatch):
    view = _view()
    view.update([_entry(0, Role.USER, "a" * 200)])
    monkeypatch.setattr(view, "_content_width", lambda i: 80)
    view.init_browse_cursor()
    # 行テキストは "> " + 200 文字 = 202 文字 → 80 + 78 + 44 の 3 視覚行
    assert (view._cursor_line, view._cursor_seg) == (0, 2)

    view.move_cursor_up()
    assert view._cursor_seg == 1
    view.move_cursor_up()
    assert view._cursor_seg == 0
    view.move_cursor_up()  # 先頭視覚行で停止
    assert (view._cursor_line, view._cursor_seg) == (0, 0)

    view.move_cursor_down()
    assert view._cursor_seg == 1
    view.move_cursor_down()
    view.move_cursor_down()  # 最終視覚行を超えると番兵へ
    assert view.selected_entry() is None


def test_only_cursor_visual_row_is_highlighted(monkeypatch):
    view = ChatView(_fake_session(), is_browse=lambda: True)
    entries = [_entry(0, Role.USER, "a" * 200)]
    view.update(entries)
    monkeypatch.setattr(view, "_content_width", lambda i: 80)
    view.init_browse_cursor()
    view.move_cursor_up()  # 中央のセグメント（文字 [80, 158) の 78 文字）へ

    from ui.chat_view import _RowEntry
    frags = view._render_entry(_RowEntry.from_thread_entry(entries[0]), 0)
    highlighted = "".join(t for s, t in frags if "bg:#1e4272" in s)
    plain = "".join(t for s, t in frags if "bg:#1e4272" not in s)
    assert len(highlighted) == 78
    assert len(plain) == 202 - 78 + 1  # 残りの文字 + 末尾の改行


def test_line_cursor_moves_within_and_across_messages():
    view = _view()
    view.update([
        _entry(0, Role.USER, "u1\nu2\nu3"),
        _entry(1, Role.ASSISTANT, "a1\na2", parent_id=0),
    ])
    view.init_browse_cursor()  # 末尾メッセージの最終行
    assert (view.selected_entry().node.id, view._cursor_line) == (1, 1)

    view.move_cursor_up()
    assert (view.selected_entry().node.id, view._cursor_line) == (1, 0)
    view.move_cursor_up()  # メッセージ境界を越えて前メッセージの最終行へ
    assert (view.selected_entry().node.id, view._cursor_line) == (0, 2)
    view.move_cursor_up()
    view.move_cursor_up()
    assert (view.selected_entry().node.id, view._cursor_line) == (0, 0)
    view.move_cursor_up()  # 先頭行で停止
    assert (view.selected_entry().node.id, view._cursor_line) == (0, 0)

    view.move_cursor_down()
    assert (view.selected_entry().node.id, view._cursor_line) == (0, 1)


def test_line_count_includes_tool_call_lines():
    tool_messages = (
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "web_search", "arguments": "{}"}}]},
    )
    view = _view()
    view.update([
        _entry(0, Role.ASSISTANT, "1行だけの本文", tool_messages=tool_messages),
    ])
    # 本文 1 行 + ツール呼び出し表示 1 行
    assert view._line_counts == [2]


def test_cursor_line_clamped_when_message_shrinks():
    """h/l でのブランチ切替等で行数が減ったらカーソル行をクランプする"""
    view = _view()
    view.update([_entry(0, Role.USER, "1\n2\n3\n4")])
    view.init_browse_cursor()
    assert view._cursor_line == 3
    view.update([_entry(0, Role.USER, "1\n2")])
    assert (view.selected_entry().node.id, view._cursor_line) == (0, 1)


def test_cursor_reset_when_entries_shrink():
    view = _view()
    view.update([_entry(0, Role.USER, "q"), _entry(1, Role.ASSISTANT, "a", parent_id=0)])
    view.init_browse_cursor()
    view.update([_entry(0, Role.USER, "q")])  # ブランチ切替などで行数が減る
    assert view.selected_entry() is None  # 範囲外カーソルは破棄される


def _styles_by_line(fragments):
    """フラグメント列を論理行ごとの (style, text) リストに分解する"""
    lines = [[]]
    for style, text in fragments:
        parts = text.split("\n")
        for j, part in enumerate(parts):
            if j > 0:
                lines.append([])
            if part:
                lines[-1].append((style, part))
    return lines


def test_only_cursor_line_is_highlighted():
    """選択表示は行単位: カーソル行だけに背景色が付く（browse 状態は外部が単一情報源）"""
    browse = {"on": False}
    view = ChatView(_fake_session(), is_browse=lambda: browse["on"])
    entries = [_entry(0, Role.USER, "1行目\n2行目\n3行目")]
    view.update(entries)
    view.init_browse_cursor()
    view.move_cursor_up()  # 2 行目（line=1）へ

    from ui.chat_view import _RowEntry
    row = _RowEntry.from_thread_entry(entries[0])

    # input モード中はハイライトなし
    assert not any("bg:#1e4272" in s for s, _ in view._render_entry(row, 0))

    browse["on"] = True
    lines = _styles_by_line(view._render_entry(row, 0))
    assert all("bg:#1e4272" in s for s, t in lines[1])      # カーソル行
    assert not any("bg:#1e4272" in s for s, t in lines[0])  # 他の行
    assert not any("bg:#1e4272" in s for s, t in lines[2])


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
