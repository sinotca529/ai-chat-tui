# UI 層設計

## フレームワーク

**prompt_toolkit** を使用する。
Git Bash（mintty）上での動作実績があり、asyncio ネイティブでストリーミング表示との相性がよい。

---

## コンポーネント構成

```
ChatApp
├── ChatView             スレッドの表示とカーソル管理
├── InputArea            メッセージの入力
├── TreeSelectOverlay    保存済みツリーの選択（フローティング）
└── ModelSelectOverlay   モデルの選択（フローティング）
```

`ChatApp` が `ChatSession` への参照を持ち、各コンポーネントに渡す。

---

## レイアウト

```python
FloatContainer(
    content=HSplit([
        ChatView,       # 残余スペースを占有
        HorizontalLine,
        InputArea,      # 固定高さ（8 行）
    ]),
    floats=[
        Float(content=TreeSelectOverlay),
        Float(content=ModelSelectOverlay),
    ]
)
```

各オーバーレイは `ConditionalContainer` で表示を制御する。

---

## 画面イメージ

```
┌──────────────────────────────────────────────┐
│ > こんにちは                        [1/2]   │
│ * こんにちは！何かお手伝いできますか？       │
│ > Pythonについて教えて               [1/1]  │
│ * Pythonは...                               │
│                                             │
│ * ▌                                        │
├──────────────────────────────────────────────┤
│ > _                                         │
└──────────────────────────────────────────────┘
```

- `>` : ユーザーメッセージ
- `*` : AI メッセージ
- プレフィックスの直後に 1 スペース空けてコンテンツを開始する
- 折り返し行はコンテンツ開始列（列 2）に揃える
- ユーザーメッセージの右端に兄弟インジケータ `[N/M]` を表示する（`M > 1` のとき）
- ストリーミング中は最後の AI メッセージにカーソル `▌` を表示する

---

## モード（状態機械）

```
input ──Tab──────────────────────────── browse
  │   ←─Tab / Esc──────────────────────── │
  │                                        │
  ├──Ctrl+T── tree_overlay ──Ctrl+T──── input
  │
  └──Ctrl+O── model_overlay ──Ctrl+O── input
```

| モード          | フォーカス先           | 説明                             |
| --------------- | ---------------------- | -------------------------------- |
| `input`         | InputArea              | デフォルト。テキストを入力できる |
| `browse`        | ChatView               | メッセージを選択し分岐操作を行う |
| `tree_overlay`  | TreeSelectOverlay      | 保存済みツリーを選択する         |
| `model_overlay` | ModelSelectOverlay     | 使用するモデルを選択する         |

---

## キーバインド

| キー        | モード                | 操作                                               |
| ----------- | --------------------- | -------------------------------------------------- |
| `Ctrl+D`    | input                 | メッセージを送信                                   |
| `Tab`       | input                 | 閲覧モードへ切り替え                               |
| `Tab`       | browse                | 入力モードへ切り替え                               |
| `Esc`       | browse                | 入力モードへ切り替え                               |
| `↑` / `↓`  | browse                | カーソルをメッセージ間で移動                       |
| `←` / `→`  | browse                | 選択中ユーザーメッセージの兄弟ブランチを切り替え   |
| `e`         | browse                | 選択中ユーザーメッセージを入力欄に展開し、分岐準備 |
| `Ctrl+T`    | input / browse        | ツリー選択オーバーレイを開く                       |
| `Ctrl+T`    | tree_overlay          | ツリー選択オーバーレイを閉じる                     |
| `↑` / `↓`  | tree_overlay          | ツリー一覧でカーソルを移動                         |
| `Enter`     | tree_overlay          | ツリーを選択して切り替え、オーバーレイを閉じる     |
| `Ctrl+O`    | input / browse        | モデル選択オーバーレイを開く                       |
| `Ctrl+O`    | model_overlay         | モデル選択オーバーレイを閉じる                     |
| `↑` / `↓`  | model_overlay         | モデル一覧でカーソルを移動                         |
| `Enter`     | model_overlay         | モデルを選択して切り替え、オーバーレイを閉じる     |
| `Ctrl+C`    | 全モード              | 終了                                               |
| `Ctrl+Q`    | 全モード              | 終了                                               |

---

## ChatView の状態

```python
class ChatView:
    _entries: list[ThreadEntry]  # 表示中のスレッド
    _cursor_index: int           # 選択中の行インデックス（-1 = 末尾）
    _streaming_text: str         # ストリーミング中の未確定テキスト
    _browse_mode: bool
```

`FormattedTextControl` の描画関数が `_entries` と `_cursor_index` を参照してレンダリングする。
状態が変化するたびに `app.invalidate()` を呼び、再描画をスケジュールする。

---

## ThreadEntry（ChatSession の変更）

`current_thread()` の戻り値を拡張し、兄弟情報を付加する。
UI 側が ChatTree に直接アクセスしないようにするため、ChatSession 側で計算して返す。

```python
@dataclass(frozen=True)
class ThreadEntry:
    node: Node
    sibling_index: int   # 1 始まり。このノードが兄弟中で何番目か
    sibling_count: int   # 兄弟の総数（自身を含む）
```

`sibling_count == 1` のノードには `[N/M]` を表示しない。

---

## 兄弟ブランチの切り替えフロー

チャットビューで選択中のユーザーメッセージに `sibling_count > 1` のとき、`←/→` で切り替える。

```
1. 選択中ノードの兄弟 ID リストを取得
2. 現在のインデックスから前後の兄弟 ID を選択
3. session.navigate_to_branch_end(sibling_id) を呼ぶ
4. ChatView を再描画
```

`navigate_to_branch_end(node_id)` は ChatSession に追加するメソッド。
指定ノードから `children[0]` を再帰的に辿り、末端（葉ノード）に cursor を移動する。

---

## 分岐（メッセージの編集・再送信）フロー

```
1. 閲覧モードで対象ユーザーメッセージにカーソルを当てる
2. `e` キーを押す
3. そのメッセージの内容を InputArea に展開する
4. 分岐先（対象ノードの親 ID）を ChatApp が保持する
5. 入力モードに切り替える
6. `Ctrl+D` でメッセージを送信するとき、保持していた親 ID を使って送信する
```

```python
# ChatApp が保持する状態
_branch_target_id: int | None  # None のとき現在の cursor に追記
```

`send_message` 呼び出し前に `_branch_target_id` があれば `session.navigate_to(_branch_target_id)` を実行してから送信する。
送信後は `_branch_target_id` を `None` にリセットする。

---

## ストリーミング表示フロー

```
1. Ctrl+D でメッセージ送信
2. ChatView にユーザーメッセージを即座に追加して再描画
3. asyncio.ensure_future(stream_task()) でストリーミング開始
4. stream_task():
   a. session.send_message() の AsyncIterator を消費
   b. チャンクを受け取るたびに _streaming_text を更新
   c. app.invalidate() で再描画
   d. 完了後、_streaming_text を確定テキストとして entries に統合
5. 入力欄を有効に戻す
```

ストリーミング中は `Ctrl+D` を無効化し、誤操作を防ぐ。

---

## ツリー選択オーバーレイのフロー

```
1. Ctrl+T でオーバーレイを表示
2. session.list_tree_ids() でツリー ID 一覧を取得して表示
3. ↑/↓ で選択、Enter で確定
4. session.load_tree(tree_id) でツリーを切り替え
5. ChatView をリセットして再描画
6. Ctrl+T でオーバーレイを閉じる
```

先頭に `[新規作成]` を表示し、選択すると空のツリーを新規作成する。

---

## モデル選択オーバーレイのフロー

```
1. Ctrl+O でオーバーレイを表示（「読み込み中...」状態）
2. asyncio.ensure_future(_load_models()) でモデル一覧を非同期取得
3. 取得完了後に一覧を表示。現在のモデルにカーソルを合わせる
4. ↑/↓ で選択、Enter で確定
5. session.set_model(model_id) でモデルを切り替え
6. Ctrl+O でオーバーレイを閉じる
```

取得失敗時はエラーメッセージをオーバーレイ内に表示する。
モデルの切り替えは次回送信から反映される（現在のスレッドには影響しない）。
