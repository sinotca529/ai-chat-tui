"""ChatApp の E2E テスト。

create_pipe_input で実際のキー入力を注入し、DummyOutput で描画を捨てる。
API は FakeApiHandler（tests/conftest.py）で差し替えるため外部依存はない。
キーバインド → モード遷移 → ChatSession → 永続化 の配線全体を検証する。
"""
import asyncio
from contextlib import asynccontextmanager

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from application.chat_session import ChatSession
from domain.chat_tree import ChatTree
from ui.chat_app import ChatApp
from tests.conftest import FakeApiHandler

CTRL_C = "\x03"
CTRL_D = "\x04"
CTRL_Q = "\x11"
TAB = "\t"


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    async def poll():
        while not predicate():
            await asyncio.sleep(0.02)
    await asyncio.wait_for(poll(), timeout)


@asynccontextmanager
async def _running_app(session: ChatSession):
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=DummyOutput()):
            app = ChatApp(session)
            run_task = asyncio.ensure_future(app.run())
            await _wait_for(lambda: app._app.is_running)
            try:
                yield app, pipe
            finally:
                if not run_task.done():
                    pipe.send_text(CTRL_Q)
                await asyncio.wait_for(run_task, timeout=5)


async def test_send_message_end_to_end(store):
    api = FakeApiHandler(chunks=("Hi", " there"))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("こんにちは")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)

    thread = session.current_thread()
    assert [e.node.content for e in thread] == ["こんにちは", "Hi there"]
    # 初回応答後にタイトルが自動生成・保存される
    await _wait_for(lambda: store.list_trees() != [] and store.list_trees()[0][1] != "")
    assert store.list_trees()[0][1] == "生成タイトル"


async def test_empty_input_is_not_sent(store):
    api = FakeApiHandler()
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("   ")
        pipe.send_text(CTRL_D)
        await asyncio.sleep(0.2)
        assert session.current_thread() == []
        assert not app._streaming


async def test_cancel_streaming_restores_input(store):
    api = FakeApiHandler(chunks=("部分応答",), block_forever=True)
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("キャンセルされる質問")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: app._streaming)
        pipe.send_text(CTRL_C)
        await _wait_for(lambda: not app._streaming)

        # ツリーは汚れず、入力欄にメッセージが復元される
        assert session.current_thread() == []
        assert app._input_area.text == "キャンセルされる質問"


async def test_stream_error_shows_message_and_restores_input(store):
    api = FakeApiHandler(chunks=("途中", RuntimeError("connection lost")))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("失敗する質問")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: "connection lost" in session.streaming_text)
        await _wait_for(lambda: not app._streaming)

        assert session.current_thread() == []
        assert "connection lost" in session.streaming_text  # エラー表示
        assert app._input_area.text == "失敗する質問"


async def test_branch_edit_creates_sibling(store):
    """ブランチ編集 (browse → e → Ctrl+D) で兄弟ノードが作られること。

    CLAUDE.md の不変条件（分岐点へ navigate 後に _refresh_chat_view して
    からストリーミング開始）の回帰テスト。
    """
    api = FakeApiHandler(chunks=("応答",))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("q1")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        pipe.send_text("q2")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 4)

        pipe.send_text(TAB)  # browse モードへ（カーソルは末尾の応答）
        pipe.send_text("k")  # 1 つ上 = 2 番目のユーザーメッセージ q2
        pipe.send_text("e")  # ブランチ編集開始
        await _wait_for(lambda: app._branch_target_id is not None)
        assert app._input_area.text == "q2"

        pipe.send_text(CTRL_D)  # 同文のまま分岐送信
        # 元の q2（node_id=2）に兄弟ができるまで待つ
        await _wait_for(lambda: len(session.siblings_of(2)) == 2)
        await _wait_for(lambda: not app._streaming)

        thread = session.current_thread()
        branched = thread[2]
        assert branched.node.content == "q2"
        assert branched.sibling_count == 2  # 元の q2 と分岐後の q2 が兄弟
        assert branched.sibling_index == 2


async def test_branch_edit_of_root_message_creates_sibling(store):
    """ルートのユーザーメッセージ (parent_id=None) のブランチ編集も分岐すること。"""
    api = FakeApiHandler(chunks=("応答",))
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("root質問")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)

        pipe.send_text(TAB)
        pipe.send_text("k")  # ルートのユーザーメッセージへ
        pipe.send_text("e")
        await _wait_for(lambda: app._input_area.text == "root質問")
        pipe.send_text(CTRL_D)
        # ルート（node_id=0）に兄弟ができるまで待つ
        await _wait_for(lambda: len(session.siblings_of(0)) == 2)
        await _wait_for(lambda: not app._streaming)

        thread = session.current_thread()
        assert len(thread) == 2  # 分岐なので新スレッドも 2 件
        assert thread[0].node.content == "root質問"
        assert thread[0].node.parent_id is None
        assert thread[0].sibling_count == 2  # 元の root質問 と兄弟になる
        assert thread[0].sibling_index == 2


async def test_help_overlay_toggle(store):
    api = FakeApiHandler()
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("?")
        await _wait_for(lambda: app._mode == "help_overlay")
        pipe.send_text("?")
        await _wait_for(lambda: app._mode == "input")


async def test_new_chat_switches_tree(store):
    api = FakeApiHandler()
    session = ChatSession(tree=ChatTree(), api=api, store=store)

    async with _running_app(session) as (app, pipe):
        pipe.send_text("q1")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        old_tree_id = session.tree_id

        pipe.send_text("\x0e")  # Ctrl+N
        await _wait_for(lambda: session.tree_id != old_tree_id)
        assert session.current_thread() == []
