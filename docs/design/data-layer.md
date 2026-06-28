# 非UI層設計

## 層の構成

```
┌──────────────────────────────────────────────┐
│                   UI 層                      │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│             アプリケーション層               │
│                ChatSession                   │
└───────┬───────────────────────┬──────────────┘
        │                       │
┌───────▼──────┐    ┌───────────▼────────────┐
│  ドメイン層  │    │ インフラストラクチャ層 │
│  Role        │    │ ChatTreeStore          │
│  Node        │    │ ApiHandler             │
│  ChatTree    │    │                        │
└──────────────┘    └────────────────────────┘
```

UI 層は `ChatSession` のみを参照する。
`ChatTree`、`ChatTreeStore`、`ApiHandler` を直接触らない。

---

## ドメイン層

業務概念を表現する。外部システムへの依存を持たない。

### Role

```python
from enum import StrEnum

class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
```

`str` のサブクラスであるため、JSON シリアライズ時に変換なしで文字列として扱える。
`Role.USER == "user"` が成立するため、API へ渡す際も変換不要。
`match` 文での網羅性チェックも効く。

### Node

ツリーの 1 要素。1 メッセージに対応する。

```python
@dataclass(frozen=True)
class Node:
    id: int
    role: Role
    content: str
    parent_id: int | None   # ルートノードのみ None
```

#### 子・兄弟情報を Node に持たせない理由

`parent_id` は作成時に確定し、以後変化しない。
「このメッセージが何への返信か」という、メッセージ自身の文脈を表す情報であり、Node に持たせることは自然。

一方、子ノードの一覧はメッセージ自身の情報ではなく、ツリーの構造的情報。
作成時点では子は存在せず、後から追加されるたびに変化する。
Node に持たせると、子を追加するたびに親ノードを変更しなければならず、immutable にできない。

Git のコミットオブジェクトも同じ設計をとっている。
各コミットは `parent` だけを持ち、子は持たない。
子は全コミットの `parent` を走査して導出する。

子・兄弟はいずれも `parent_id` の走査で導出する。
チャット履歴のノード数は多くても数百程度であり、O(n) スキャンはボトルネックにならない。

```python
def children(self, node_id: int) -> list[int]:
    return [n.id for n in self.nodes if n.parent_id == node_id]

def siblings(self, node_id: int) -> list[int]:
    parent_id = self.nodes[node_id].parent_id
    if parent_id is None:
        return []
    return [n.id for n in self.nodes if n.parent_id == parent_id and n.id != node_id]
```

#### ノード ID をツリー全体の通し番号とする理由

`id` はツリー全体でユニークな通し番号であり、ノードの挿入順に `0, 1, 2, ...` と採番される。
チャット履歴はノードの削除・並び替えが発生しない追記専用の構造であるため、`id = len(nodes)` での採番が成立する。
これにより `nodes[id]` で O(1) アクセスが可能。

### ChatTree

ノードの集合とカーソル位置を管理する。

```python
class ChatTree:
    tree_id: str          # UUID
    nodes: list[Node]
    current_id: int | None  # 現在のカーソル位置（通常は最後のアシスタントノード）
```

```python
def insert(self, parent_id: int | None, role: Role, content: str) -> int
    """ノードを追加し、追加したノードの id を返す"""

def thread(self, node_id: int) -> list[Node]
    """ルートから node_id までのパス（スレッド）を返す"""

def siblings(self, node_id: int) -> list[int]
    """node_id の兄弟ノード ID リストを返す"""

def children(self, node_id: int) -> list[int]
    """node_id の子ノード ID リストを返す"""

def set_current(self, node_id: int) -> None
    """カーソルを移動する"""
```

#### カーソル（`current_id`）の意味

- 通常は直近のアシスタントノードを指す。
- 分岐操作（過去メッセージへの返信）では、返信先の親ノードに移動してから `send_message` を呼ぶ。
- ツリーをロードしたとき、前回の位置から再開できるよう `current_id` は保存・復元される。
- 新規ツリーの場合は `None`。

---

## アプリケーション層

UI 層が直接操作するインターフェース。
ドメイン層とインフラストラクチャ層を束ね、ユースケースを実現する。

### ChatSession

```python
class ChatSession:
    def __init__(self, tree: ChatTree, api: ApiHandler, store: ChatTreeStore)
```

```python
def current_thread(self) -> list[ThreadEntry]
    """現在のカーソルから辿ったスレッド（ルート → カーソル）、兄弟情報付き"""

def navigate_to(self, node_id: int) -> None
    """カーソルを移動する。分岐の切り替えに使用"""

def navigate_to_branch_end(self, node_id: int) -> None
    """指定ノードから長子を辿って末端まで移動し、current_id を更新する"""

def siblings_of(self, node_id: int) -> list[int]
    """指定ノードの兄弟 ID リスト（自身を含む）"""

async def send_message(self, msg: str) -> AsyncIterator[str]
    """メッセージを送信し、レスポンスのチャンクを順次 yield する"""

def new_tree(self) -> None
    """空のツリーを新規作成し、カレントツリーを切り替える（保存しない）"""

def load_tree(self, tree_id: str) -> None
    """保存済みツリーをロードし、カレントツリーを切り替える"""

def list_tree_ids(self) -> list[str]
    """保存済みツリー ID の一覧を返す"""

async def list_models(self) -> list[str]
    """ApiHandler に委譲してモデル一覧を返す"""

def set_model(self, model_id: str) -> None
    """ApiHandler に委譲してモデルを切り替える"""

@property
def current_model(self) -> str
    """現在使用中のモデル ID"""
```

#### `send_message` のフロー

```
1. 現在のカーソルを親として、ユーザーノードをツリーに挿入
2. 現在のスレッドを API に送信し、ストリームを開始
3. チャンクを yield しながら、レスポンス全文を蓄積
4. ストリーム完了後、アシスタントノードをツリーに挿入
5. カーソルをアシスタントノードに移動
6. ツリーを保存
```

```python
async def send_message(self, msg: str) -> AsyncIterator[str]:
    thread = self.current_thread()
    user_id = self._tree.insert(self._tree.current_id, Role.USER, msg)

    full_response = ""
    async for chunk in self._api.stream(thread, msg):
        full_response += chunk
        yield chunk

    asst_id = self._tree.insert(user_id, Role.ASSISTANT, full_response)
    self._tree.set_current(asst_id)
    self._store.save(self._tree)
```

#### ストリーム開始前にユーザーノードを挿入する理由

UI がストリーミング中にユーザーメッセージを即座に表示するため。

#### ストリームが中断された場合の挙動

ストリームの例外は呼び出し元（UI 層）に伝播させる。
ユーザーノードは残るが、アシスタントノードは挿入されないため、同じカーソル位置から再試行できる。
ツリーは保存しない。

---

## インフラストラクチャ層

外部システムとの入出力を担う。
`ChatTreeStore` はローカルファイルシステム、`ApiHandler` は外部 API へのアダプター。

### ChatTreeStore

シリアライズロジックをここに集約し、`ChatTree` 自身は保存の方法を知らない。

```python
class ChatTreeStore:
    def __init__(self, save_dir: str)

    def save(self, tree: ChatTree) -> None
        """ツリーを JSON ファイルとして保存する"""

    def load(self, tree_id: str) -> ChatTree
        """ツリーを JSON ファイルから復元する"""

    def list_ids(self) -> list[str]
        """保存済みツリー ID の一覧を返す（新しい順）"""
```

### ApiHandler

`ChatSession` がこのインターフェースに依存する。

```python
class ApiHandler:
    def __init__(self, base_url: str, api_key: str, model: str)

    async def stream(
        self,
        thread: list[Node],
        new_message: str,
    ) -> AsyncIterator[str]
        """スレッドと新しいメッセージを受け取り、レスポンスのチャンクを yield する"""

    async def list_models(self) -> list[str]
        """サーバーから利用可能なモデル ID 一覧を取得して返す（GET /v1/models）"""

    def set_model(self, model_id: str) -> None
        """使用するモデルを変更する。次回の stream() 呼び出しから反映される"""

    @property
    def model(self) -> str
        """現在使用中のモデル ID"""
```

`openai` ライブラリの非同期クライアント (`AsyncOpenAI`) を使用する。
`list_models()` は `client.models.list()` に委譲する。Ollama も `/v1/models` を実装しているため追加実装は不要。

---

## 永続化フォーマット（JSON）

ファイル名: `{tree_id}.json`

```json
{
  "tree_id": "550e8400-e29b-41d4-a716-446655440000",
  "current_id": 5,
  "nodes": [
    { "id": 0, "role": "user",      "content": "こんにちは",                    "parent_id": null },
    { "id": 1, "role": "assistant", "content": "こんにちは！何かお手伝いできますか？", "parent_id": 0 },
    { "id": 2, "role": "user",      "content": "Pythonについて教えて",            "parent_id": 1 },
    { "id": 3, "role": "assistant", "content": "はじめまして！",                  "parent_id": 0 },
    ...
  ]
}
```

子・兄弟関係は `parent_id` から導出するため、保存しない。

---

## 操作フロー

### 通常のメッセージ送信

```
カーソル: node#3 (assistant)
         ↓ send_message("次の質問")
node#4 (user, parent=#3) を挿入
         ↓ API ストリーム
node#5 (assistant, parent=#4) を挿入
カーソル: node#5
```

### 分岐（過去メッセージへの返信）

```
現在のスレッド: root → #0 → #1 → #2 → #3(cursor)

node#1 (user) を選択して別の返信を送る場合:
  navigate_to(node#0)  ← node#1 の親に移動
  send_message("別の聞き方")
  → node#4 (user, parent=#0) を挿入
  → node#5 (assistant, parent=#4) を挿入
  カーソル: node#5

結果のツリー:
  root(#0)
  ├── #1(user) → #2(assistant) → #3(user) → ... (元のスレッド)
  └── #4(user) → #5(assistant)              (新しいブランチ)
```

### ツリーの切り替え

```
store.list_ids()  →  UI でリスト表示
  ↓ 選択
store.load(tree_id)  →  ChatTree を取得
session = ChatSession(tree, api, store)
  ↓
session.current_thread()  →  UI に表示
```

---

## 現行実装との差分

| 項目                   | 現行                         | 新設計                                      |
| ---------------------- | ---------------------------- | ------------------------------------------- |
| 層の分類               | UI / それ以外                | UI / アプリケーション / ドメイン / インフラ |
| `siblings` の保存      | 各ノードに保持               | 廃止（導出）                                |
| `children` の保存      | 各ノードに保持               | 廃止（導出）                                |
| ノード型               | `dict`（`role` は `str`）    | `frozen dataclass`（`role` は `StrEnum`）   |
| シリアライズ責務       | `ChatTree.save()`            | `ChatTreeStore` に集約                      |
| カーソル位置の永続化   | なし（常に左端の葉から開始） | `current_id` として保存                     |
| ストリーミング         | 副作用を持つ同期ジェネレータ | 副作用のない非同期ジェネレータ              |
| `user_msg_id + 1` 仮定 | UI 層に存在                  | 廃止（UI は ID を意識しない）               |
| API クライアント       | `OpenAI`（同期）             | `AsyncOpenAI`（非同期）                     |
