# テスト戦略

リファクタや機能追加でデグレを起こさないための仕組み。
**テストは実 API・実端末に一切依存せず、`uv run pytest` だけで完結する。**

## 実行方法

```bash
uv sync           # dev 依存 (pytest, pytest-asyncio) を含めてインストール
uv run pytest     # 全テスト実行（数秒で完了する）
uv run pytest tests/test_chat_session.py -k branch   # 絞り込み実行
```

CI（`.github/workflows/ci.yml`）が push / PR ごとに同じテストを実行する。

## 外部依存の切り方

このプロジェクトの外部依存は 2 つあり、それぞれ差し替え点が決まっている。

| 外部依存 | 差し替え点 | テストでの代替 |
|---|---|---|
| AI サーバ (OpenAI 互換 API) | `ApiHandler` | `tests/conftest.py` の `FakeApiHandler` |
| 端末 (TUI) | prompt_toolkit の入出力 | `create_pipe_input` + `DummyOutput` |

### FakeApiHandler（AI サーバの代替）

`ChatSession` が使う `ApiHandler` のインターフェース
（`stream` / `generate_title` / `list_models` / `set_model` / `model` /
`last_tool_messages`）だけを実装したフェイク。`chunks` に
str・`ToolIndicator`・`Exception` を混ぜて渡すことで、正常応答・
ツール実行表示・API エラーの各シナリオを決定的に再現できる。
`block_forever=True` は「応答が返らない」状態を作り、キャンセル系の
テストに使う。

`ApiHandler` 自体の内部ロジック（ツール呼び出しループ、引数の分割チャンク
結合、ラウンド上限）は `tests/test_api_handler.py` で OpenAI クライアントを
`SimpleNamespace` ベースのスタブに差し替えてテストする。

### TUI の E2E テスト（端末の代替）

`tests/test_chat_app_e2e.py` は prompt_toolkit 公式のテスト機構を使う:

```python
with create_pipe_input() as pipe:
    with create_app_session(input=pipe, output=DummyOutput()):
        app = ChatApp(session)   # この中で作った Application はパイプ入力を読む
        ...
        pipe.send_text("\x04")   # Ctrl+D などの実キーを注入
```

これにより「キーバインド → モード遷移 → ChatSession → 永続化」の配線全体を
実際のキー入力で検証できる。描画結果のピクセル的な検証はしない
（レイアウトの見た目は壊れてもテストでは検出できないので、描画ロジックは
`ChatView` の単体テストでフラグメント列として検証する）。

**E2E テストの待機は必ず状態ベースのポーリング（`_wait_for`）で行い、
固定 sleep に頼らない。** 「キー送信 → 条件成立を待つ → 検証」の順を守る。
待機条件は「キー処理前から既に真」にならないものを選ぶこと
（例: `not app._streaming` 単独は送信キー処理前に真になるので不可）。

## テストの層構成

| ファイル | 対象 | 外部依存 |
|---|---|---|
| `test_chat_tree.py` | ChatTree（ツリー操作・シリアライズ・後方互換） | なし |
| `test_chat_tree_store.py` | ChatTreeStore（保存・一覧・削除・空ツリー非永続化） | tmp_path |
| `test_chat_session.py` | ChatSession（送信・ロールバック・分岐・system prompt） | FakeApiHandler + tmp_path |
| `test_api_handler.py` | ApiHandler（ツールループ・チャンク結合・タイトル生成） | OpenAI クライアントスタブ |
| `test_tool_registry.py` | ToolRegistry / @tool デコレータ | なし |
| `test_highlight.py` | コードフェンスのパースとハイライト | なし |
| `test_chat_view.py` | ChatView（行構築・カーソル・ツール表示抽出） | フェイク session |
| `test_chat_app_e2e.py` | ChatApp（キー入力からの一連の流れ） | パイプ入力 + FakeApiHandler |

## 何をテストすべきか

- **CLAUDE.md に書かれた仕様・不変条件には対応するテストを置く。**
  例: 「空ツリーの非永続化」「save() 失敗時の 2 回 rollback」「ツール
  メッセージのスレッド再構築時注入」「ブランチ編集前の `_refresh_chat_view`」
  は全てテスト化済み。仕様を CLAUDE.md に足すときはテストも足す。
- バグを修正したら、まずそのバグを再現する失敗テストを書いてから直す。
- 既知だが未修正のバグは `@pytest.mark.xfail(strict=True)` で登録する
  （現在: ルートメッセージのブランチ編集が分岐しない問題）。修正すると
  XPASS で落ちるので、xfail の外し忘れに気づける。

## 書いてはいけないテスト

- 実 API サーバやネットワークに接続するテスト
- 固定 `sleep` でタイミングを合わせる E2E テスト
- private 属性の値の逐一検証など、リファクタで壊れるだけで挙動を守らないテスト
  （E2E テストでの `app._streaming` のような「状態の完了待ち」参照は許容）
