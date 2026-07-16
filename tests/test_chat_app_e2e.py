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
F1 = "\x1bOP"


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


@asynccontextmanager
async def _start_app(store, **api_kwargs):
    """FakeApiHandler + ChatSession + 起動済みアプリの一体型ヘルパー。

    api_kwargs は FakeApiHandler にそのまま渡す（chunks= 等）。
    """
    api = FakeApiHandler(**api_kwargs)
    session = ChatSession(tree=ChatTree(), api=api, store=store)
    async with _running_app(session) as (app, pipe):
        yield app, pipe, session, api


async def test_send_message_end_to_end(store):
    async with _start_app(store, chunks=("Hi", " there")) as (app, pipe, session, api):
        pipe.send_text("こんにちは")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)

    thread = session.current_thread()
    assert [e.node.content for e in thread] == ["こんにちは", "Hi there"]
    # 初回応答後にタイトルが自動生成・保存される
    await _wait_for(lambda: store.list_trees() != [] and store.list_trees()[0][1] != "")
    assert store.list_trees()[0][1] == "生成タイトル"


async def test_empty_input_is_not_sent(store):
    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("   ")
        pipe.send_text(CTRL_D)
        await asyncio.sleep(0.2)
        assert session.current_thread() == []
        assert not app._streaming


async def test_cancel_streaming_restores_input(store):
    async with _start_app(store, chunks=("部分応答",), block_forever=True) as (app, pipe, session, api):
        pipe.send_text("キャンセルされる質問")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: app._streaming)
        pipe.send_text(CTRL_C)
        await _wait_for(lambda: not app._streaming)

        # ツリーは汚れず、入力欄にメッセージが復元される
        assert session.current_thread() == []
        assert app._input_area.text == "キャンセルされる質問"


async def test_stream_error_shows_message_and_restores_input(store):
    async with _start_app(store, chunks=("途中", RuntimeError("connection lost"))) as (app, pipe, session, api):
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
    async with _start_app(store, chunks=("応答",)) as (app, pipe, session, api):
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
    async with _start_app(store, chunks=("応答",)) as (app, pipe, session, api):
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
    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text(F1)
        await _wait_for(lambda: app._mode == "help_overlay")
        pipe.send_text(F1)
        await _wait_for(lambda: app._mode == "input")


async def test_question_mark_is_typed_into_input_not_bound_to_help(store):
    """? キーはヘルプに割り当てず、メッセージ本文にそのまま入力できること"""
    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("これは質問ですか?")
        await _wait_for(lambda: app._input_area.text == "これは質問ですか?")
        assert app._mode == "input"


async def test_autoscroll_follows_streaming_response(store):
    """画面に収まらない長い応答のストリーミング中、下端に自動スクロールすること。

    DummyOutput は 40 行 × 80 桁。チャットペインは約 31 行なので
    60 行の応答は必ず溢れる。
    """
    async with _start_app(store, chunks=("行\n" * 60,), block_forever=True) as (app, pipe, session, api):
        pipe.send_text("長い応答をください")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: app._streaming)
        # ストリーミング中（未確定表示の間）に下端へスクロールされる
        await _wait_for(lambda: app._chat_view.window.vertical_scroll > 0)
        pipe.send_text(CTRL_C)
        await _wait_for(lambda: not app._streaming)


async def test_autoscroll_after_response_completes(store):
    async with _start_app(store, chunks=("行\n" * 60,)) as (app, pipe, session, api):
        pipe.send_text("長い応答をください")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        # 確定後の再描画でも下端に追従したままになる
        await _wait_for(lambda: app._chat_view.window.vertical_scroll > 0)


async def _settled_scroll(app) -> int:
    """スクロール位置が 2 回連続で同値になる（描画が安定する）まで待って返す"""
    last = -1
    while True:
        cur = app._chat_view.window.vertical_scroll
        if cur == last:
            return cur
        last = cur
        await asyncio.sleep(0.1)


async def test_browse_manual_scroll_moves_one_line(store):
    """browse モードの Ctrl+Y / Ctrl+E が 1 行ずつスクロールし、上端で止まること。

    注: browse 進入時は選択メッセージの先頭が見える位置までスクロールが
    調整される（既存挙動）ため、絶対位置ではなく相対移動を検証する。
    """
    async with _start_app(store, chunks=("行\n" * 60,)) as (app, pipe, session, api):
        pipe.send_text("長い応答をください")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        await _wait_for(lambda: app._chat_view.window.vertical_scroll > 0)

        pipe.send_text(TAB)  # browse モード（追従 OFF、カーソルは末尾行）
        await _wait_for(lambda: app._mode == "browse")
        start = await asyncio.wait_for(_settled_scroll(app), timeout=5)
        assert start > 0  # コンテンツが溢れているので下端 > 0

        pipe.send_text("\x19")  # Ctrl+Y: 1 行上へ
        await _wait_for(lambda: app._chat_view.window.vertical_scroll == start - 1)
        pipe.send_text("\x05")  # Ctrl+E: 1 行下へ（下端でクランプ）
        await _wait_for(lambda: app._chat_view.window.vertical_scroll == start)
        pipe.send_text("\x05")  # 下端よりさらに下へは行かない
        await asyncio.sleep(0.2)
        assert app._chat_view.window.vertical_scroll == start

        # 上端まで戻してさらに Ctrl+Y しても 0 で止まる
        for _ in range(start + 2):
            pipe.send_text("\x19")
        await _wait_for(lambda: app._chat_view.window.vertical_scroll == 0)
        pipe.send_text("\x19")
        await asyncio.sleep(0.2)
        assert app._chat_view.window.vertical_scroll == 0


async def test_scroll_keeps_cursor_visible_and_view_does_not_jump_back(store):
    """C-y/C-e でカーソルがビュー内に追従し、直後の j/k でビューが巻き戻らないこと"""
    def cursor_visible(app) -> bool:
        view, pane = app._chat_view, app._chat_view.window
        row = view._cursor_global_row()
        return pane.vertical_scroll <= row < pane.vertical_scroll + pane._viewport_height

    async with _start_app(store, chunks=("行\n" * 60,)) as (app, pipe, session, api):
        pipe.send_text("長い応答をください")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        pipe.send_text(TAB)
        await _wait_for(lambda: app._mode == "browse")
        start = await asyncio.wait_for(_settled_scroll(app), timeout=5)

        for _ in range(20):
            pipe.send_text("\x19")  # Ctrl+Y × 20
        await _wait_for(lambda: app._chat_view.window.vertical_scroll == start - 20)
        assert cursor_visible(app)  # カーソルが画面外に置き去りになっていない

        # 置き去りカーソルへの巻き戻りが起きない（従来のバグ）
        scroll_before = await asyncio.wait_for(_settled_scroll(app), timeout=5)
        pipe.send_text("k")
        await asyncio.sleep(0.3)
        assert app._chat_view.window.vertical_scroll == scroll_before
        assert cursor_visible(app)


async def test_j_at_bottom_does_not_rewind_view(store):
    """最下部でさらに j を押してもビューが巻き戻らないこと。

    従来はカーソルが番兵 (-1) になり、フォーカス中 Window のカーソル位置が
    デフォルト (0,0) に落ちて最後のメッセージの先頭までスクロールが巻き
    戻っていた。
    """
    async with _start_app(store, chunks=("行\n" * 50,)) as (app, pipe, session, api):
        for msg in ("q1", "q2"):
            pipe.send_text(msg)
            pipe.send_text(CTRL_D)
            await _wait_for(lambda: not app._streaming and bool(session.current_thread()))
        await _wait_for(lambda: len(session.current_thread()) == 4)

        pipe.send_text(TAB)
        await _wait_for(lambda: app._mode == "browse")
        bottom = await asyncio.wait_for(_settled_scroll(app), timeout=5)
        assert bottom > 0
        last_msg = app._chat_view._cursor_msg
        last_text_line = app._chat_view._cursor_line

        pipe.send_text("j")  # 末尾テキスト行 → 末尾メッセージの空行へ
        pipe.send_text("j")  # 最終視覚行で停止
        await asyncio.sleep(0.4)
        # ビューは巻き戻らず、カーソルは末尾メッセージの空行に留まる
        assert app._chat_view.window.vertical_scroll == bottom
        assert app._chat_view._cursor_msg == last_msg
        assert app._chat_view._cursor_line == last_text_line + 1  # 空行
        assert app._chat_view.selected_entry() is not None

        pipe.send_text("k")  # 直後の k は 1 視覚行だけ上がる（テキスト行へ復帰）
        await asyncio.sleep(0.3)
        assert app._chat_view.window.vertical_scroll == bottom
        assert app._chat_view._cursor_line == last_text_line


async def test_browse_mode_disables_autoscroll_until_next_send(store):
    async with _start_app(store) as (app, pipe, session, api):
        assert app._chat_view.window.stick_to_bottom  # 初期状態は追従 ON

        pipe.send_text(TAB)  # browse モードへ → 過去を読むので追従 OFF
        await _wait_for(lambda: app._mode == "browse")
        assert not app._chat_view.window.stick_to_bottom

        pipe.send_text(TAB)  # input へ戻っただけでは追従は復活しない
        await _wait_for(lambda: app._mode == "input")
        assert not app._chat_view.window.stick_to_bottom

        pipe.send_text("次の質問")
        pipe.send_text(CTRL_D)  # 送信で追従 ON に戻る
        await _wait_for(lambda: len(session.current_thread()) == 2)
        assert app._chat_view.window.stick_to_bottom


async def test_enter_does_not_copy_indent(store):
    """Enter は自動インデント（copy_margin）しない。

    非ブラケットペーストでは改行が 1 つずつ Enter として処理されるため、
    copy_margin が有効だと貼り付けたコードのインデントが階段状に重なる。
    """
    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("    indented line")
        pipe.send_text("\r")  # Enter
        pipe.send_text("next line")
        await _wait_for(
            lambda: app._input_area.text == "    indented line\nnext line"
        )


async def test_non_bracketed_paste_preserves_indentation(store):
    """非ブラケットペーストでインデント付きコードが原文どおり貼り付くこと。

    ブラケットペーストが効かない端末経路では、貼り付けは生のキー入力の
    連続として届き、改行は CR として送られる。インデントの増減を含む
    コードでその経路を再現する（copy_margin が有効だと前行のインデントが
    各行にコピーされ、階段状に崩れて失敗する）。
    """
    code = "def f(x):\n    if x:\n        return 1\n    return 0"
    async with _start_app(store) as (app, pipe, session, api):
        # 端末が改行を CR として送る非ブラケットペーストのキー列
        pipe.send_text(code.replace("\n", "\r"))
        await _wait_for(lambda: app._input_area.text == code)


async def test_external_editor_roundtrip(store, tmp_path, monkeypatch):
    """Ctrl+X Ctrl+E で $VISUAL のエディタが起動し、下書きが渡って
    保存内容が入力欄に反映されること（git のコミットメッセージと同じ流儀）。
    """
    editor = tmp_path / "fake_editor.sh"
    editor.write_text('#!/bin/sh\nprintf \'edited:%s\' "$(cat "$1")" > "$1"\n')
    editor.chmod(0o755)
    monkeypatch.setenv("VISUAL", str(editor))

    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("下書き")
        await _wait_for(lambda: app._input_area.text == "下書き")
        pipe.send_text("\x18\x05")  # Ctrl+X Ctrl+E
        # 偽エディタが「edited:下書き」に書き換えた内容が反映される
        await _wait_for(lambda: app._input_area.text == "edited:下書き")
        # 自動送信はされない（送信は従来どおり Ctrl+D）
        assert session.current_thread() == []
        assert app._mode == "input"


async def test_external_editor_failure_keeps_input(store, tmp_path, monkeypatch):
    """エディタが異常終了（非ゼロ exit）した場合は入力欄を変更しない"""
    editor = tmp_path / "failing_editor.sh"
    editor.write_text('#!/bin/sh\nprintf "junk" > "$1"\nexit 1\n')
    editor.chmod(0o755)
    monkeypatch.setenv("VISUAL", str(editor))

    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("元の下書き")
        await _wait_for(lambda: app._input_area.text == "元の下書き")
        pipe.send_text("\x18\x05")  # Ctrl+X Ctrl+E
        await asyncio.sleep(0.5)  # エディタ実行の完了を待つ
        assert app._input_area.text == "元の下書き"


async def test_gg_and_G_jump_to_top_and_bottom(store):
    async with _start_app(store, chunks=("応答",)) as (app, pipe, session, api):
        pipe.send_text("q1")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        pipe.send_text("q2")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 4)

        pipe.send_text(TAB)
        await _wait_for(lambda: app._mode == "browse")
        pipe.send_text("gg")
        await _wait_for(lambda: app._chat_view._cursor_msg == 0)
        assert app._chat_view.selected_entry().node.content == "q1"

        pipe.send_text("G")
        await _wait_for(lambda: app._chat_view._cursor_msg == 3)
        assert app._chat_view.selected_entry().node.content == "応答"

        pipe.send_text("{")  # 前のメッセージ（先頭）へ
        await _wait_for(lambda: app._chat_view._cursor_msg == 2)
        pipe.send_text("[[")  # エイリアスでも同じ
        await _wait_for(lambda: app._chat_view._cursor_msg == 1)
        pipe.send_text("}")
        await _wait_for(lambda: app._chat_view._cursor_msg == 2)
        pipe.send_text("]]")
        await _wait_for(lambda: app._chat_view._cursor_msg == 3)


async def test_wrap_math_matches_renderer(store):
    """自前の折り返し計算が prompt_toolkit の実描画と一致すること（オラクル検証）。

    ChatView._segments は pt と同じ get_cwidth・同じ貪欲法の「写し」なので、
    pt 側のアルゴリズム変更でサイレントにずれるリスクがある。CJK・半角・
    絵文字・Ambiguous 文字の混在コンテンツで「自前計算の視覚行数の合計 +
    末尾空行 = 実際に描画された Window の高さ」を検証し、ずれたらここで
    検出する。
    """
    mixed = "\n".join([
        "日本語の長い行です。" * 20,          # 全角のみ
        "mixed 半角と全角の交互テキスト " * 15,  # 混在
        "emoji 🙂🎉👍 and ambiguous ①②③ " * 10,
        "a" * 150,                           # 半角のみ
    ])
    async with _start_app(store, chunks=(mixed,)) as (app, pipe, session, api):
        pipe.send_text("長文ください")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        view = app._chat_view
        await _wait_for(lambda: view._content_windows[1].render_info is not None)

        ours = sum(
            len(view._segments(1, line)) for line in range(view._line_counts[1])
        )
        rendered = view._content_windows[1].render_info.window_height
        assert ours > view._line_counts[1]  # 折り返しが実際に発生している
        assert ours + 1 == rendered  # +1 は表示テキスト末尾の "\n" による空行


async def test_attachment_send_end_to_end(store, tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("メモの中身", encoding="utf-8")
    async with _start_app(store, chunks=("読みました",)) as (app, pipe, session, api):
        pipe.send_text(f"@{f} を要約して")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)

    node = session.current_thread()[0].node
    assert node.attachments[0]["content"] == "メモの中身"
    assert "メモの中身" in api.sent_messages[-1]["content"]


async def test_missing_attachment_shows_error_and_restores_input(store):
    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("@/no/such/file.md を読んで")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: "見つかりません" in session.streaming_text)
        await _wait_for(lambda: not app._streaming)
        assert app._input_area.text == "@/no/such/file.md を読んで"
        assert session.current_thread() == []


async def test_at_token_completion_and_tab_coexistence(store, tmp_path, monkeypatch):
    """@ トークンで補完メニューが出て Tab が補完に、閉じれば Tab が browse 切替に働く"""
    (tmp_path / "attach_target.md").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("@attach_t")
        # complete_while_typing で補完候補が付くのを待つ
        await _wait_for(lambda: app._input_area.buffer.complete_state is not None)
        pipe.send_text(TAB)  # 補完メニュー表示中の Tab は補完（browse に切り替わらない）
        await _wait_for(lambda: app._input_area.text == "@attach_target.md")
        assert app._mode == "input"

        pipe.send_text("\x1b")  # Esc で補完メニューを閉じる
        await _wait_for(lambda: app._input_area.buffer.complete_state is None)
        pipe.send_text(TAB)  # メニューが閉じていれば Tab は browse 切替
        await _wait_for(lambda: app._mode == "browse")


async def test_ghost_text_hidden_once_typing_starts(store):
    async with _start_app(store) as (app, pipe, session, api):
        assert app._is_input_empty()
        pipe.send_text("a")
        await _wait_for(lambda: app._input_area.text == "a")
        assert not app._is_input_empty()


async def test_tree_overlay_height_grows_with_items(store):
    """ツリー選択オーバーレイの一覧が項目数に応じて広がる（従来は 10 行固定）"""
    from domain.chat_tree import ChatTree as _Tree
    for i in range(30):
        store.save(_Tree(tree_id=f"tree-{i:02d}", title=f"ツリー{i}"))

    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("\x14")  # Ctrl+T
        await _wait_for(lambda: app._mode == "tree_overlay")
        inner = app._tree_overlay._list_window
        await _wait_for(lambda: inner.render_info is not None)
        # 30 ツリー + [新規作成] = 31 行（DummyOutput 40 行の余白内に収まる）
        await _wait_for(lambda: inner.render_info.window_height == 31)


async def test_new_chat_switches_tree(store):
    async with _start_app(store) as (app, pipe, session, api):
        pipe.send_text("q1")
        pipe.send_text(CTRL_D)
        await _wait_for(lambda: len(session.current_thread()) == 2)
        old_tree_id = session.tree_id

        pipe.send_text("\x0e")  # Ctrl+N
        await _wait_for(lambda: session.tree_id != old_tree_id)
        assert session.current_thread() == []
