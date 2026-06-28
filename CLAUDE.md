# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- `chat_tree.py` — `ChatTree`: append-only ツリー。子・兄弟は `parent_id` から導出。

**アプリケーション層 (`application/`)**
- `thread_entry.py` — `ThreadEntry` (frozen dataclass: node + sibling_index + sibling_count)
- `chat_session.py` — `ChatSession`: UI が直接触る唯一のインターフェース。ツリー操作・API 呼び出し・永続化を束ねる。

**インフラストラクチャ層 (`infrastructure/`)**
- `chat_tree_store.py` — `ChatTreeStore`: `ChatTree` を JSON ファイルとして保存・読み込み。
- `api_handler.py` — `ApiHandler`: `AsyncOpenAI` ラッパー。`stream()` / `list_models()` / `set_model()`。

**UI 層 (`ui/`)**
- `chat_app.py` — `ChatApp`: top-level。モード管理・キーバインド・ストリーミング制御。
- `chat_view.py` — `ChatView`: スレッドを `FormattedTextControl` でレンダリング。ブラウズモードのカーソルも管理。
- `highlight.py` — コードブロックのパース (`iter_content`) と Pygments によるハイライト (`highlight_code`)。
- `tree_select_overlay.py` — `TreeSelectOverlay`: 保存済みツリーの選択 UI。
- `model_select_overlay.py` — `ModelSelectOverlay`: モデル一覧の選択 UI（非同期ロード）。

## Key design details

**ブランチ構造**: `Node` は `parent_id` のみ持つ。子・兄弟は全ノードをスキャンして導出（Git のコミットと同じ設計）。

**モード**: `input` / `browse` / `tree_overlay` / `model_overlay` の 4 状態。`Condition` フィルタでキーバインドを分岐する。

**キーバインド**:
- `Ctrl+D` — 送信
- `Tab` / `Esc` — input ↔ browse 切り替え
- `Ctrl+T` — ツリー選択オーバーレイをトグル
- `Ctrl+O` — モデル選択オーバーレイをトグル
- browse: `↑/↓` メッセージ移動、`←/→` 兄弟ブランチ切り替え、`e` 分岐編集

**ストリーミング**: `asyncio.ensure_future` でバックグラウンド実行。`app.invalidate()` で差分再描画。

**空ツリーの非永続化**: `ChatTreeStore.new_tree()` は保存を行わない。メッセージ送信完了時にのみ保存される。
