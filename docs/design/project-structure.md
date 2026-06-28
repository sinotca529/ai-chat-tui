# プロジェクト構成と設定

## ディレクトリ構成

```
ai-chat-tui/
├── main.py
├── config.toml              ユーザー設定（バージョン管理対象）
├── .env                     APIキー（バージョン管理対象外）
├── domain/
│   ├── role.py              Role（StrEnum）
│   ├── node.py              Node（frozen dataclass）
│   └── chat_tree.py         ChatTree
├── application/
│   ├── thread_entry.py      ThreadEntry（frozen dataclass）
│   └── chat_session.py      ChatSession
├── infrastructure/
│   ├── chat_tree_store.py   ChatTreeStore
│   └── api_handler.py       ApiHandler
└── ui/
    ├── chat_app.py              ChatApp
    ├── chat_view.py             ChatView
    ├── highlight.py             コードブロックのシンタックスハイライト
    ├── tree_select_overlay.py   TreeSelectOverlay
    └── model_select_overlay.py  ModelSelectOverlay
```

各ディレクトリは Python パッケージ（`__init__.py` あり）とする。

---

## 設定

### 秘密情報

API キーは環境変数から読み込む。
`.env` ファイルに書いた場合は `python-dotenv` で読み込む。

```
OPENAI_API_KEY=sk-...
```

`.env` は `.gitignore` に追加する。

### ユーザー設定

`config.toml` に記述する。
Python 3.11 以降の標準ライブラリ `tomllib` で読み込むため、追加の依存なしに利用できる。

```toml
[api]
url   = "https://api.openai.com/v1"
model = "gpt-4o"

[storage]
save_dir = "./trees"
```

`config.toml` はリポジトリに含め、デフォルト値を記述しておく。

### 読み込み順序

1. `config.toml` から基本設定を読む。
2. 環境変数（または `.env`）から API キーを読む。
3. コマンドライン引数で `--config <path>` を指定した場合、そのファイルを代わりに読む。

### main.py での利用

```python
import os
import tomllib
from dotenv import load_dotenv

load_dotenv()

with open("config.toml", "rb") as f:
    config = tomllib.load(f)

api_key  = os.environ["OPENAI_API_KEY"]
url      = config["api"]["url"]
model    = config["api"]["model"]
save_dir = config["storage"]["save_dir"]
```

---

## 依存パッケージ

| パッケージ       | 用途                                     |
| ---------------- | ---------------------------------------- |
| `prompt-toolkit` | TUI フレームワーク                       |
| `openai`         | OpenAI API クライアント（`AsyncOpenAI`） |
| `python-dotenv`  | `.env` 読み込み                          |

`tomllib` は Python 3.11 標準ライブラリのため追加不要。
