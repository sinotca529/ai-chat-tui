import asyncio

import pytest

from application.chat_session import ChatSession
from domain.chat_tree import ChatTree
from domain.role import Role
from infrastructure.api_handler import ToolIndicator
from infrastructure.chat_tree_store import ChatTreeStore
from tests.conftest import FakeApiHandler


def _noop() -> None:
    pass


async def test_send_message_appends_user_and_assistant_nodes(session, store):
    await session.send_message("こんにちは", _noop)

    thread = session.current_thread()
    assert [(e.node.role, e.node.content) for e in thread] == [
        (Role.USER, "こんにちは"),
        (Role.ASSISTANT, "Hi!"),
    ]
    # ストリーミング状態は完了後にクリアされる
    assert session.pending_user_msg is None
    assert session.streaming_text == ""
    # 送信完了時に永続化される
    loaded = store.load(session.tree_id)
    assert loaded.current_id == thread[-1].node.id


async def test_streaming_state_visible_during_stream(store):
    api = FakeApiHandler(chunks=("He", "llo"))
    session = ChatSession(tree=ChatTree(), api=api, store=store)
    seen: list[tuple[str | None, str]] = []

    def spy() -> None:
        seen.append((session.pending_user_msg, session.streaming_text))

    await session.send_message("hi", spy)
    assert seen == [("hi", "He"), ("hi", "Hello")]


async def test_tool_indicator_shown_but_not_saved(store):
    api = FakeApiHandler(chunks=(ToolIndicator("[web_search: x]\n"), "結果です"))
    session = ChatSession(tree=ChatTree(), api=api, store=store)
    streamed: list[str] = []
    await session.send_message("調べて", lambda: streamed.append(session.streaming_text))

    assert streamed[0] == "[web_search: x]\n"  # 表示にはインジケータを含む
    thread = session.current_thread()
    assert thread[-1].node.content == "結果です"  # 保存内容には含まない


async def test_tool_messages_persisted_and_replayed_in_next_request(store):
    tool_msgs = (
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "web_search", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "search result"},
    )
    api = FakeApiHandler(chunks=("回答",), tool_messages=tool_msgs)
    session = ChatSession(tree=ChatTree(), api=api, store=store)
    await session.send_message("調べて", _noop)

    assert session.current_thread()[-1].node.tool_messages == tool_msgs

    # 次のリクエストでは中間メッセージが最終応答の直前に注入される
    await session.send_message("続けて", _noop)
    roles = [m["role"] for m in api.sent_messages]
    assert roles == ["user", "assistant", "tool", "assistant", "user"]
    assert api.sent_messages[1]["tool_calls"][0]["id"] == "t1"


async def test_empty_response_inserts_nothing(store, tmp_path):
    api = FakeApiHandler(chunks=())
    session = ChatSession(tree=ChatTree(), api=api, store=store)
    await session.send_message("hi", _noop)

    assert session.current_thread() == []
    assert store.list_trees() == []  # 保存もされない


async def test_stream_error_propagates_and_tree_stays_clean(store):
    api = FakeApiHandler(chunks=("途中", RuntimeError("connection lost")))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    with pytest.raises(RuntimeError):
        await session.send_message("hi", _noop)

    assert session.current_thread() == []  # ツリーへの書き込みは完了後のみ
    assert session.pending_user_msg is None
    assert store.list_trees() == []


async def test_save_failure_rolls_back_both_nodes(fake_api, tmp_path):
    class FailingStore(ChatTreeStore):
        def save(self, tree: ChatTree) -> None:
            raise OSError("disk full")

    store = FailingStore(str(tmp_path / "trees"))
    session = ChatSession(tree=ChatTree(), api=fake_api, store=store)

    with pytest.raises(OSError):
        await session.send_message("hi", _noop)

    # user / assistant の 2 ノードとも取り消され、送信前の状態に戻る
    assert session.current_thread() == []


async def test_cancel_during_stream_leaves_tree_untouched(store):
    api = FakeApiHandler(chunks=("部分応答",), block_forever=True)
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    task = asyncio.ensure_future(session.send_message("hi", _noop))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert session.current_thread() == []
    assert session.pending_user_msg is None
    assert session.streaming_text == ""


async def test_branch_from_middle_creates_sibling(session, fake_api):
    await session.send_message("質問1", _noop)
    asst_id = session.current_thread()[-1].node.id

    # ブランチ編集相当: 分岐点（AI 応答ノード）へ current を戻してから送信する
    await session.send_message("追い質問A", _noop)
    session.navigate_to(asst_id)
    await session.send_message("追い質問B", _noop)

    thread = session.current_thread()
    # 追い質問A / B は同じ親（asst_id）を持つ兄弟になる
    branch_entry = thread[2]
    assert branch_entry.node.content == "追い質問B"
    assert branch_entry.sibling_count == 2
    assert branch_entry.sibling_index == 2


async def test_navigate_to_none_branches_from_root(session):
    """navigate_to(None) でルートに戻り、次の送信はルートの兄弟になる"""
    await session.send_message("最初の質問", _noop)

    session.navigate_to(None)
    assert session.current_thread() == []

    await session.send_message("別の最初の質問", _noop)
    thread = session.current_thread()
    assert [e.node.content for e in thread] == ["別の最初の質問", "Hi!"]
    assert thread[0].sibling_count == 2
    assert thread[0].sibling_index == 2


async def test_navigate_to_branch_end_follows_firstborn_chain(session):
    await session.send_message("q1", _noop)
    end_id = session.current_thread()[-1].node.id
    root_id = session.current_thread()[0].node.id

    session.navigate_to(root_id)
    session.navigate_to_branch_end(root_id)
    assert session.current_thread()[-1].node.id == end_id


async def test_system_prompt_priority(store):
    api = FakeApiHandler()
    session = ChatSession(
        tree=ChatTree(), api=api, store=store, default_system_prompt="デフォルト",
    )
    assert session.effective_system_prompt == "デフォルト"

    await session.send_message("hi", _noop)
    assert api.sent_messages[0] == {"role": "system", "content": "デフォルト"}

    # ツリー固有のプロンプトが設定されればそちらが優先される
    session.set_system_prompt("ツリー固有")
    await session.send_message("hi again", _noop)
    assert api.sent_messages[0] == {"role": "system", "content": "ツリー固有"}


async def test_no_system_message_when_no_prompt(session, fake_api):
    await session.send_message("hi", _noop)
    assert fake_api.sent_messages[0]["role"] == "user"


def _make_compaction_session(store, context_window: int | None) -> tuple[ChatSession, FakeApiHandler]:
    api = FakeApiHandler(chunks=("応答です",))
    session = ChatSession(
        tree=ChatTree(), api=api, store=store, context_window=context_window,
    )
    return session, api


async def test_no_compaction_without_context_window(store):
    """context_window 未設定なら圧縮は一切行われない（opt-in）"""
    session, api = _make_compaction_session(store, context_window=None)
    for i in range(4):
        await session.send_message("あ" * 200, _noop)
    assert api.summarize_calls == []


async def test_no_compaction_below_threshold(store):
    session, api = _make_compaction_session(store, context_window=100_000)
    for i in range(4):
        await session.send_message(f"質問{i}", _noop)
    assert api.summarize_calls == []


async def test_compaction_replaces_old_messages_with_summary(store):
    session, api = _make_compaction_session(store, context_window=500)
    for i in range(4):
        await session.send_message(f"質問{i}:" + "あ" * 60, _noop)

    assert api.summarize_calls  # 閾値超過で要約が実行された
    # 直近リクエスト: 要約入り system + 直近ノード（KEEP=4）+ 新規 user のみ
    sent = api.sent_messages
    assert sent[0]["role"] == "system"
    assert "これまでの要約" in sent[0]["content"]
    assert len(sent) <= 1 + 4 + 1
    # 要約済みの古いメッセージは生では送られない
    contents = [m.get("content", "") for m in sent[1:]]
    assert not any("質問0" in c for c in contents)
    # 表示スレッド（ツリー）は全ノードを保持したまま（append-only 維持）
    assert len(session.current_thread()) == 8


async def test_compaction_result_is_persisted(store):
    session, api = _make_compaction_session(store, context_window=500)
    for i in range(4):
        await session.send_message(f"質問{i}:" + "あ" * 60, _noop)

    loaded = store.load(session.tree_id)
    assert loaded.summary == "これまでの要約"
    assert loaded.summary_upto_id is not None


async def test_recompaction_uses_previous_summary_incrementally(store):
    session, api = _make_compaction_session(store, context_window=500)
    for i in range(8):
        await session.send_message(f"質問{i}:" + "あ" * 60, _noop)

    assert len(api.summarize_calls) >= 2
    # 2 回目以降の要約入力は旧要約から始まる（全履歴を再要約しない）
    second_input = api.summarize_calls[1]
    assert "これまでの要約" in second_input[0]["content"]


async def test_summary_not_applied_on_other_branch(store):
    session, api = _make_compaction_session(store, context_window=500)
    for i in range(8):
        await session.send_message(f"質問{i}:" + "あ" * 60, _noop)
    assert api.summarize_calls
    # 2 回目の圧縮で summary_upto_id は最初の往復より深いノードを指している
    upto = store.load(session.tree_id).summary_upto_id
    assert upto is not None and upto > 1

    # 要約範囲より手前（最初の応答ノード）から分岐すると要約は使われない
    session.navigate_to(session.current_thread()[1].node.id)
    await session.send_message("分岐質問", _noop)

    sent = api.sent_messages
    assert all("これまでの要約" not in m.get("content", "") for m in sent)
    assert any("質問0" in m.get("content", "") for m in sent)  # 手前のノードは生で送られる


async def test_compaction_notice_shown_during_stream_but_not_saved(store):
    session, api = _make_compaction_session(store, context_window=500)
    for i in range(3):
        await session.send_message(f"質問{i}:" + "あ" * 60, _noop)

    seen: list[str] = []
    await session.send_message(
        "質問3:" + "あ" * 60, lambda: seen.append(session.streaming_text)
    )
    assert any(s.startswith("[コンテキストを圧縮しました]") for s in seen)
    # 保存された応答本文には通知が混入しない
    assert session.current_thread()[-1].node.content == "応答です"


def _tool_messages_with_result(content: str) -> tuple:
    return (
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "fetch_page", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": content},
    )


async def test_old_tool_results_are_truncated_on_send(store):
    """直近 4 ノードより古いノードの role:tool 本文は切り詰めて送る"""
    big = "x" * 600
    api = FakeApiHandler(chunks=("回答",), tool_messages=_tool_messages_with_result(big))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    for i in range(3):
        await session.send_message(f"q{i}", _noop)
    await session.send_message("q3", _noop)  # 6 エントリ時点の送信内容を検査

    tool_contents = [m["content"] for m in api.sent_messages if m.get("role") == "tool"]
    assert len(tool_contents) == 3  # 各アシスタントノードに 1 件ずつ
    # 古いノード（境界より前）は切り詰め + 省略表記
    assert tool_contents[0].startswith("x" * 500)
    assert "省略" in tool_contents[0]
    assert len(tool_contents[0]) < len(big) + 50
    # 直近ノードは原文のまま
    assert tool_contents[1] == big
    assert tool_contents[2] == big
    # assistant の tool_calls メッセージは切り詰め対象外
    assert any(m.get("tool_calls") for m in api.sent_messages)


async def test_short_old_tool_results_are_sent_verbatim(store):
    """500 文字以下の古いツール結果は切り詰めない"""
    small = "短い結果"
    api = FakeApiHandler(chunks=("回答",), tool_messages=_tool_messages_with_result(small))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    for i in range(4):
        await session.send_message(f"q{i}", _noop)

    tool_contents = [m["content"] for m in api.sent_messages if m.get("role") == "tool"]
    assert all(c == small for c in tool_contents)


async def test_tool_result_truncation_does_not_touch_tree(store):
    """切り詰めは送信時の変換のみで、ツリー（JSON）には原文が保存され続ける"""
    big = "x" * 600
    api = FakeApiHandler(chunks=("回答",), tool_messages=_tool_messages_with_result(big))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    for i in range(4):
        await session.send_message(f"q{i}", _noop)

    loaded = store.load(session.tree_id)
    first_asst = loaded.thread(loaded.current_id)[1]
    assert first_asst.tool_messages[1]["content"] == big


async def test_memories_injected_into_system_message(store, tmp_path, fake_api):
    from infrastructure.memory_store import MemoryStore

    memory_store = MemoryStore(str(tmp_path / "mem"))
    memory_store.add("犬を飼っている")
    memory_store.add("札幌在住")
    session = ChatSession(
        tree=ChatTree(), api=fake_api, store=store,
        default_system_prompt="あなたは有能なアシスタントです。",
        memory_store=memory_store,
    )
    await session.send_message("hi", _noop)

    system = fake_api.sent_messages[0]
    assert system["role"] == "system"
    # システムプロンプト → 記憶 の順で合成される
    assert system["content"].startswith("あなたは有能なアシスタントです。")
    assert "[ユーザーに関する記憶]" in system["content"]
    assert "- 犬を飼っている" in system["content"]
    assert "- 札幌在住" in system["content"]


async def test_empty_memory_adds_no_section(store, tmp_path, fake_api):
    from infrastructure.memory_store import MemoryStore

    session = ChatSession(
        tree=ChatTree(), api=fake_api, store=store,
        memory_store=MemoryStore(str(tmp_path / "mem")),
    )
    await session.send_message("hi", _noop)
    # メモリが空なら system メッセージ自体を作らない（従来挙動を維持）
    assert fake_api.sent_messages[0]["role"] == "user"


async def test_attachment_snapshot_and_expansion(store, fake_api, tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("仕様書の中身", encoding="utf-8")
    session = ChatSession(tree=ChatTree(), api=fake_api, store=store)

    await session.send_message(f"これを読んで @{f}", _noop)

    node = session.current_thread()[0].node
    assert node.content == f"これを読んで @{f}"  # 本文は原文のまま保存
    assert node.attachments[0]["content"] == "仕様書の中身"
    # API へは展開した内容が送られる
    sent_user = fake_api.sent_messages[-1]
    assert "仕様書の中身" in sent_user["content"]

    # 2 通目でも履歴側のユーザーメッセージに展開が乗る
    await session.send_message("続きを", _noop)
    assert "仕様書の中身" in fake_api.sent_messages[0]["content"]

    # 永続化にもスナップショットが残る
    loaded = store.load(session.tree_id)
    assert loaded.thread(loaded.current_id)[0].attachments[0]["content"] == "仕様書の中身"


async def test_missing_attachment_aborts_send(store, fake_api):
    session = ChatSession(tree=ChatTree(), api=fake_api, store=store)
    with pytest.raises(ValueError):
        await session.send_message("@/no/such/file.md を読んで", _noop)
    # ノードは作られず、ストリーミング状態もクリアされる
    assert session.current_thread() == []
    assert session.pending_user_msg is None
    assert fake_api.sent_messages is None  # API 呼び出し前に中止


async def test_old_attachment_truncated_in_history(store, tmp_path):
    f = tmp_path / "big.md"
    f.write_text("x" * 600, encoding="utf-8")
    api = FakeApiHandler(chunks=("回答",))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    await session.send_message(f"@{f} を読んで", _noop)
    for i in range(3):
        await session.send_message(f"続き{i}", _noop)

    # 最初のユーザーメッセージは直近 4 ノードより古いので添付が縮約される
    first_user = api.sent_messages[0]["content"]
    assert "x" * 500 in first_user
    assert "x" * 501 not in first_user
    assert "省略" in first_user


async def test_generate_title_saves_tree(session, store):
    await session.send_message("hi", _noop)
    title = await session.generate_title()
    assert title == "生成タイトル"
    assert store.load(session.tree_id).title == "生成タイトル"


async def test_delete_current_tree_switches_to_new_tree(session, store):
    await session.send_message("hi", _noop)
    old_id = session.tree_id

    switched = session.delete_tree(old_id)
    assert switched is True
    assert session.tree_id != old_id
    assert store.list_trees() == []


async def test_delete_other_tree_keeps_current(session, store):
    await session.send_message("hi", _noop)
    other = ChatTree(tree_id="other")
    store.save(other)

    switched = session.delete_tree("other")
    assert switched is False
    assert session.current_thread() != []
