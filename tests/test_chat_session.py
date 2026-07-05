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
