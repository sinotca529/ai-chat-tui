# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 必須ルール（コンテキスト圧縮後も必ず遵守すること）

**言語**: ユーザーへの応答は常に日本語で行う。コンテキスト圧縮後も例外なく日本語を維持する。

**ブランチ規律（絶対厳守）**: 1 つの issue/機能/修正 = 1 ブランチ = 1 PR。複数の懸念事項を 1 ブランチに混在させてはならない。今取り組んでいる作業と直交する修正が必要になった場合は、必ず作業を中断して別ブランチを作成し、ユーザーに報告してから対処する。

**仕様の文書化**: 新しい仕様・設計上の不変条件・挙動を追加・変更するコミットには、必ず同一コミット内に CLAUDE.md の更新を含めること。CLAUDE.md を更新せずに仕様変更コミットを作ってはならない。コミット前に「このコミットは挙動を変えるか？」を自問し、Yes なら CLAUDE.md をステージに加えてから commit する。

**警告・エラーの扱い**: 警告やエラーが発生した場合は必ず根本原因を調査すること。`warnings.filterwarnings` や `try/except` で症状を隠す対処療法を根本原因の究明より先に行ってはならない。

**テストの維持（デグレ防止）**: コミット前に必ず `uv run pytest` を実行し、全テストが通ることを確認する。挙動を追加・変更するコミットには、対応するテストの追加・更新を同一コミットに含めること。バグ修正時は先に再現テストを書いてから直す。テスト戦略・フェイクの使い方は `docs/design/testing.md` を参照。

## Running the app

```bash
# Activate venv first
source .venv/bin/activate

# Run the TUI
python main.py
```

The app connects to an OpenAI-compatible API endpoint. Settings are in `config.toml`.

## Running tests

```bash
uv sync           # dev 依存 (pytest, pytest-asyncio) を含めてインストール
uv run pytest     # 全テスト実行（実 API・実端末に依存しない、数秒で完了）
```

テストは実 AI サーバに接続しない。API は `tests/conftest.py` の `FakeApiHandler` で、端末は prompt_toolkit の `create_pipe_input` + `DummyOutput` で差し替える。CI (GitHub Actions) が push / PR ごとに全テストを実行する。詳細は `docs/design/testing.md`。

## Dependencies

```bash
uv sync   # or: pip install -e .
```

Requires Python 3.13+. Key deps: `prompt-toolkit` (TUI framework), `openai` (API client), `pygments` (syntax highlighting).

## Configuration

`config.toml` で接続先・モデル・保存ディレクトリを設定する。API キーは環境変数 `OPENAI_API_KEY`（または `.env`）から読む。

```toml
[api]
url   = "http://localhost:11434/v1"
model = "some-model"
# context_window = 32768  # 設定するとコンテキスト圧縮が有効になる（任意）

[storage]
save_dir = "./trees"
```

## Architecture

prompt_toolkit を使ったブランチ型 AI チャット TUI。4 層構成。

```
UI 層 → アプリケーション層 → ドメイン層
                           → インフラストラクチャ層
```

**ドメイン層 (`domain/`)**
- `role.py` — `Role` (StrEnum: USER / ASSISTANT)
- `node.py` — `Node` (frozen dataclass: id, role, content, parent_id, tool_messages)。`tool_messages` はツール呼び出しを伴う ASSISTANT ノードに付与される中間 API メッセージ列（`role: assistant/tool` のメッセージ）。表示には使わず、スレッド再構築時に最終応答の直前に注入してコンテキストを維持する。
- `chat_tree.py` — `ChatTree`: append-only ツリー。子・兄弟は `parent_id` から導出。`title` / `system_prompt` / `summary` / `summary_upto_id` フィールドを持つ（後者 2 つはコンテキスト圧縮用。1 ツリーに 1 スロット）。`rollback()` で末尾ノードを pop し `current_id` を親に戻す。

**アプリケーション層 (`application/`)**
- `thread_entry.py` — `ThreadEntry` (frozen dataclass: node + sibling_index + sibling_count)
- `chat_session.py` — `ChatSession`: UI が直接触る唯一のインターフェース。ツリー操作・API 呼び出し・永続化を束ねる。ストリーミング状態 (`_streaming_text` / `_pending_user_msg` / `_error_text`) も保持し、ChatView の唯一の描画ソースとなる。

**インフラストラクチャ層 (`infrastructure/`)**
- `chat_tree_store.py` — `ChatTreeStore`: `ChatTree` を JSON ファイルとして保存・読み込み・削除。`list_trees()` は `(tree_id, title)` ペアを返す。
- `tool_registry.py` / `web_search.py` / `web_fetch.py` / `current_datetime.py` — ツール基盤（`@tool` デコレータ + `ToolRegistry`）と組み込みツール。ツールは `main.py` で登録する。`web_search` は DDG 検索（上位 5 件のスニペット）、`fetch_page` は URL の本文を trafilatura で Markdown 抽出して返す（http/https のみ、タイムアウト 15 秒、5 MiB 上限、本文はコンテキスト保護のため 8000 文字で切り詰め）、`get_current_datetime` はローカル日時を曜日・タイムゾーン付きで返す（引数なし。ローカルモデルは今日の日付を知らないため、相対日付の解釈や検索クエリ組み立てに必須）。HTTP エラー・タイムアウト等は例外にせず読みやすいエラーメッセージ文字列で返し、モデルが対処できるようにする。
- `api_handler.py` — `ApiHandler`: `AsyncOpenAI` ラッパー。`stream()` / `generate_title()` / `summarize()` / `list_models()` / `set_model()`。`stream()` 完了後に `last_tool_messages` でツール呼び出しの中間メッセージ列を取得できる。ツール実行は `asyncio.to_thread` で行う（同期ツール）。**ツール非対応サーバへのフォールバック**: `tools` 付きリクエストが 400 (BadRequestError) で拒否された場合、ツールなし + 履歴中のツール関連メッセージ（`role:tool` / `tool_calls` 付き assistant）除去で 1 回だけ再送信する。成功したら以後そのハンドラインスタンスではツールを無効化し（再試行の往復を繰り返さない）、表示専用の `ToolIndicator` でフォールバックを通知する。再送信も失敗した場合は tools 起因ではないため例外をそのまま伝播し、ツールは無効化しない。tools を送っていないリクエストの 400 は再試行しない。

**UI 層 (`ui/`)**
- `chat_app.py` — `ChatApp`: top-level。モード管理・キーバインド・ストリーミング制御。
- `chat_view.py` — `ChatView`: メッセージごとに `Window` を生成し `HSplit` に積む。`ScrollablePane` + `DynamicContainer` でラップ。ブラウズモードのカーソルも管理。自身に状態は持たず、`ChatSession` を参照して描画する。内部の `_RowEntry` は `node.tool_messages` からツール呼び出し情報 `(name, args)` を抽出して保持し、メッセージ本文の後に改行して `[name: args]` の形式で黄色表示する（`fg:ansiyellow`）。
- `highlight.py` — コードブロックのパース (`iter_content`) と Pygments によるハイライト (`highlight_code`)。
- `tree_select_overlay.py` — `TreeSelectOverlay`: 保存済みツリーの選択・削除 UI。
- `model_select_overlay.py` — `ModelSelectOverlay`: モデル一覧の選択 UI（非同期ロード）。
- `system_prompt_overlay.py` — `SystemPromptOverlay`: TextArea によるシステムプロンプト編集 UI。
- `help_overlay.py` — `HelpOverlay`: キーバインド一覧の静的表示。

## Key design details

**ブランチ構造**: `Node` は `parent_id` のみ持つ。子・兄弟は全ノードをスキャンして導出（Git のコミットと同じ設計）。ルートノード（`parent_id=None`）同士も兄弟として扱う。`current_id=None` は「ルート（最初のメッセージの直前）」を表し、`navigate_to(None)` で戻れる。ルートのユーザーメッセージをブランチ編集した場合はここから分岐する。そのため UI 層でブランチ編集中かどうかは `ChatApp._branch_editing` フラグで判定する（分岐先 `_branch_target_id` は正当な値として `None` を取り得るため、`None` チェックでは判定できない）。

**モード**: `input` / `browse` / `tree_overlay` / `model_overlay` / `system_overlay` / `help_overlay` の 6 状態。`Condition` フィルタでキーバインドを分岐する。

**キーバインド**:
- `Ctrl+D` — 送信
- `Ctrl+C` — ストリーミング中はキャンセル、それ以外は終了
- `Tab` / `Esc` — input ↔ browse 切り替え
- `Ctrl+T` — ツリー選択オーバーレイをトグル
- `Ctrl+O` — モデル選択オーバーレイをトグル
- `Ctrl+P` — システムプロンプト編集オーバーレイをトグル
- `F1` — キーバインド一覧オーバーレイをトグル（`?` はメッセージ本文に入力できるよう予約しない）
- browse: `↑↓`/`jk` メッセージ移動、`←→`/`hl` 兄弟ブランチ切り替え、`e` 分岐編集、`Ctrl+E`/`Ctrl+Y` 1 行スクロール下/上
- tree overlay: `↑↓` カーソル移動、`Enter` 選択、`d` 削除確認、`y`/`n` 削除確定/キャンセル
- input: `Ctrl+A/E` 行頭/行末、`Ctrl+K/U` 行削除、`Enter` は `copy_margin=False` の改行（自動インデント無効。非ブラケットペーストで改行が Enter として処理されてもインデントが階段状に重ならないようにするため）

**入力欄のゴーストテキスト**: `ChatApp._is_input_empty`（input モードかつバッファが空）のとき、`Ctrl+D で送信, F1 でヘルプ` をカーソル位置に追従する Float（`xcursor=True, ycursor=True`）として表示する。バッファへの実書き込みではないため、送信時の内容に混入しない。

**下端オートスクロール**: `ChatView.window` は `ScrollablePane` を拡張した `AutoScrollPane`。素の `ScrollablePane` はフォーカスされた Window がペイン内にあるときしかスクロールしないため（ストリーミング中のフォーカスは入力欄＝ペイン外）、`stick_to_bottom=True` の間は描画のたびに下端へスクロールする。追従の ON/OFF: 送信 (`Ctrl+D`)・新規チャット・ツリー選択で ON、browse モード進入 (`Tab`) で OFF（過去を読む操作を妨げない）。browse から input に戻っただけでは復活せず、次の送信で ON に戻る。

**per-message Window アーキテクチャ**: メッセージ 1 件ごとに `Window` を作り `HSplit` に積む。`Window.style` をラムダにすることで行全体の背景色をロール・選択状態に応じて動的に制御する。サイドバー的な `[n/m]` 表示は `VSplit` で右端に配置。

**ストリーミング**: `asyncio.ensure_future` でバックグラウンド実行。`ChatSession.send_message(msg, invalidate)` はコルーチンで、トークンを受け取るたびに `invalidate()` を呼んで差分再描画を促す。ストリーミング中は `ChatSession._pending_user_msg` / `_streaming_text` に状態を保持し、`ChatView` はこれを直接参照して `_pending_window` / `_stream_window` を表示する。ツリーへの書き込みはストリーミング完了後にのみ行われるため、キャンセルや API エラー時のロールバックは不要。`save()` 失敗時のみ `ChatTree.rollback()` を 2 回呼んで user / assistant ノードを取り消す。**ストリーミング開始前の不変条件**: `_pending_window` は `ChatView._rows`（`update()` で構築済みの行リスト）の末尾に追加される。そのためブランチ編集（`e` キー）経由で送信する場合は、`navigate_to` で `current_id` を分岐点に移動した直後に `_refresh_chat_view()` を呼び、`_rows` を分岐点までの状態に更新してからストリーミングを開始しなければならない。

**コンテキスト圧縮（コンパクション）**: `config.toml` の `[api] context_window`（トークン数）を設定したときのみ有効（未設定なら無効 = opt-in）。送信前にリクエスト全体の推定トークン数が `context_window × 0.7` を超えたら、直近 4 ノードを残して古いノードを `ApiHandler.summarize()` で要約し、`ChatTree.summary` / `summary_upto_id` に保存する。トークン推定は「JSON 直列化長 × 1 文字 ≈ 1 トークン」の保守的近似（日本語で安全側、英語では早めに圧縮が走るだけ）。API 送信時は要約を system メッセージに合成し（`[これまでの会話の要約]` セクション）、要約済みノードは送らない。**ツリー構造・表示は一切変更しない**（append-only 維持、全ノードは browse で閲覧可能）。要約は 1 ツリーに 1 スロットで、`summary_upto_id` が現在のスレッドパス上にない間（別ブランチ閲覧中）は適用されず全ノードを生で送る。再圧縮は「旧要約 + 差分ノード」を入力とする増分方式。圧縮実行時はストリーミング表示の先頭に表示専用の `[コンテキストを圧縮しました]` を出す（ツリーには保存しない）。

**タイトル自動生成**: 初回の AI 応答完了後にバックグラウンドで `ApiHandler.generate_title()` を呼び、結果を JSON に保存。未設定の場合は `tree_id` 先頭 16 文字で代替表示。

**空ツリーの非永続化**: `ChatTreeStore.new_tree()` は保存を行わない。メッセージ送信完了時にのみ保存される。
