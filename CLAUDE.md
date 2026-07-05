# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 必須ルール（コンテキスト圧縮後も必ず遵守すること）

**言語**: ユーザーへの応答は常に日本語で行う。コンテキスト圧縮後も例外なく日本語を維持する。

**ブランチ規律（絶対厳守）**: 1 つの issue/機能/修正 = 1 ブランチ = 1 PR。複数の懸念事項を 1 ブランチに混在させてはならない。今取り組んでいる作業と直交する修正が必要になった場合は、必ず作業を中断して別ブランチを作成し、ユーザーに報告してから対処する。

## Running the app

```bash
# Activate venv first
source .venv/bin/activate

# Run the TUI
python main.py
```

The app connects to an OpenAI-compatible API endpoint. Settings are in `config.toml`.

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
- `node.py` — `Node` (frozen dataclass: id, role, content, parent_id)
- `chat_tree.py` — `ChatTree`: append-only ツリー。子・兄弟は `parent_id` から導出。`title` / `system_prompt` フィールドを持つ。`rollback()` で末尾ノードを pop し `current_id` を親に戻す。

**アプリケーション層 (`application/`)**
- `thread_entry.py` — `ThreadEntry` (frozen dataclass: node + sibling_index + sibling_count)
- `chat_session.py` — `ChatSession`: UI が直接触る唯一のインターフェース。ツリー操作・API 呼び出し・永続化を束ねる。ストリーミング状態 (`_streaming_text` / `_pending_user_msg` / `_error_text`) も保持し、ChatView の唯一の描画ソースとなる。

**インフラストラクチャ層 (`infrastructure/`)**
- `chat_tree_store.py` — `ChatTreeStore`: `ChatTree` を JSON ファイルとして保存・読み込み・削除。`list_trees()` は `(tree_id, title)` ペアを返す。
- `api_handler.py` — `ApiHandler`: `AsyncOpenAI` ラッパー。`stream()` / `generate_title()` / `list_models()` / `set_model()`。

**UI 層 (`ui/`)**
- `chat_app.py` — `ChatApp`: top-level。モード管理・キーバインド・ストリーミング制御。
- `chat_view.py` — `ChatView`: メッセージごとに `Window` を生成し `HSplit` に積む。`ScrollablePane` + `DynamicContainer` でラップ。ブラウズモードのカーソルも管理。自身に状態は持たず、`ChatSession` を参照して描画する。
- `highlight.py` — コードブロックのパース (`iter_content`) と Pygments によるハイライト (`highlight_code`)。
- `tree_select_overlay.py` — `TreeSelectOverlay`: 保存済みツリーの選択・削除 UI。
- `model_select_overlay.py` — `ModelSelectOverlay`: モデル一覧の選択 UI（非同期ロード）。
- `system_prompt_overlay.py` — `SystemPromptOverlay`: TextArea によるシステムプロンプト編集 UI。
- `help_overlay.py` — `HelpOverlay`: キーバインド一覧の静的表示。

## Key design details

**ブランチ構造**: `Node` は `parent_id` のみ持つ。子・兄弟は全ノードをスキャンして導出（Git のコミットと同じ設計）。

**モード**: `input` / `browse` / `tree_overlay` / `model_overlay` / `system_overlay` / `help_overlay` の 6 状態。`Condition` フィルタでキーバインドを分岐する。

**キーバインド**:
- `Ctrl+D` — 送信
- `Ctrl+C` — ストリーミング中はキャンセル、それ以外は終了
- `Tab` / `Esc` — input ↔ browse 切り替え
- `Ctrl+T` — ツリー選択オーバーレイをトグル
- `Ctrl+O` — モデル選択オーバーレイをトグル
- `Ctrl+P` — システムプロンプト編集オーバーレイをトグル
- `?` — キーバインド一覧オーバーレイをトグル
- browse: `↑↓`/`jk` メッセージ移動、`←→`/`hl` 兄弟ブランチ切り替え、`e` 分岐編集、`Ctrl+E`/`Ctrl+Y` 1 行スクロール下/上
- tree overlay: `↑↓` カーソル移動、`Enter` 選択、`d` 削除確認、`y`/`n` 削除確定/キャンセル
- input: `Ctrl+A/E` 行頭/行末、`Ctrl+K/U` 行削除

**per-message Window アーキテクチャ**: メッセージ 1 件ごとに `Window` を作り `HSplit` に積む。`Window.style` をラムダにすることで行全体の背景色をロール・選択状態に応じて動的に制御する。サイドバー的な `[n/m]` 表示は `VSplit` で右端に配置。

**ストリーミング**: `asyncio.ensure_future` でバックグラウンド実行。`ChatSession.send_message(msg, invalidate)` はコルーチンで、トークンを受け取るたびに `invalidate()` を呼んで差分再描画を促す。ストリーミング中は `ChatSession._pending_user_msg` / `_streaming_text` に状態を保持し、`ChatView` はこれを直接参照して `_pending_window` / `_stream_window` を表示する。ツリーへの書き込みはストリーミング完了後にのみ行われるため、キャンセルや API エラー時のロールバックは不要。`save()` 失敗時のみ `ChatTree.rollback()` を 2 回呼んで user / assistant ノードを取り消す。

**タイトル自動生成**: 初回の AI 応答完了後にバックグラウンドで `ApiHandler.generate_title()` を呼び、結果を JSON に保存。未設定の場合は `tree_id` 先頭 16 文字で代替表示。

**空ツリーの非永続化**: `ChatTreeStore.new_tree()` は保存を行わない。メッセージ送信完了時にのみ保存される。
