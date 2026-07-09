import json
import os
from datetime import date

from .tool_registry import ToolFunction, tool

# 1 件あたりの文字数上限と総件数上限。メモリは全件を system メッセージに
# 無条件注入するため、コンテキストを圧迫しないよう小さく保つ。
MAX_ENTRY_CHARS = 200
MAX_ENTRIES = 50


class MemoryStore:
    """全ツリー共通の永続メモリ。save_dir/memory.json に保存する。

    読み出しは毎回ファイルから行う（アプリ起動中の外部編集を反映する）。
    壊れた JSON は読み出しでは空扱い（チャットを止めない）、書き込みでは
    拒否する（黙って上書きしてデータを失わない）。
    """

    def __init__(self, save_dir: str) -> None:
        os.makedirs(save_dir, exist_ok=True)
        self._path = os.path.join(save_dir, "memory.json")

    def list_all(self) -> list[dict]:
        try:
            return self._load()
        except (json.JSONDecodeError, OSError):
            return []

    def add(self, text: str) -> None:
        text = text.strip()
        if not text:
            raise ValueError("memory content is empty")
        if len(text) > MAX_ENTRY_CHARS:
            raise ValueError(
                f"memory entry too long ({len(text)} > {MAX_ENTRY_CHARS} chars); "
                "summarize it into one short sentence"
            )
        try:
            memories = self._load()
        except json.JSONDecodeError:
            raise ValueError(
                "memory.json is corrupted; fix or remove it manually before saving"
            )
        if len(memories) >= MAX_ENTRIES:
            raise ValueError(
                f"memory is full ({MAX_ENTRIES} entries); "
                "remove old entries from memory.json"
            )
        next_id = max((m.get("id", 0) for m in memories), default=0) + 1
        memories.append(
            {"id": next_id, "text": text, "created_at": date.today().isoformat()}
        )
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({"memories": memories}, f, ensure_ascii=False, indent=2)

    def _load(self) -> list[dict]:
        if not os.path.exists(self._path):
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f).get("memories", [])


def make_save_memory_tool(store: MemoryStore) -> ToolFunction:
    """MemoryStore に書き込む save_memory ツールを生成する（状態はクロージャで束縛）。"""

    @tool(
        {
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": (
                    "Save a short note about the user to persistent memory, "
                    "carried across all future conversations. Use this ONLY when "
                    "the user explicitly asks you to remember something "
                    "(e.g. '覚えて', 'remember this'). Do not use it on your own "
                    "judgement. Keep the note one concise sentence."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The note to remember (one short sentence)",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        indicator=lambda args: f"[save_memory: {args.get('content', '')}]\n",
    )
    def save_memory(content: str) -> str:
        try:
            store.add(content)
        except ValueError as e:
            return f"Error: {e}"
        return "Saved to memory."

    return save_memory
