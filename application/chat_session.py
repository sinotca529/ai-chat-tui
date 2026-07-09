import json
from collections.abc import Callable
from domain.chat_tree import ChatTree
from domain.role import Role
from application.thread_entry import ThreadEntry
from infrastructure.api_handler import ApiHandler, ToolIndicator
from infrastructure.chat_tree_store import ChatTreeStore
from infrastructure.memory_store import MemoryStore

# コンテキスト圧縮の発動閾値（context_window に対する推定トークン数の割合）
_COMPACT_TRIGGER_RATIO = 0.7
# 圧縮時に生のまま残す直近ノード数（2 往復分）
_KEEP_RECENT_NODES = 4
# ツール結果を原文のまま送る直近ノード数。それより古いノードの
# role:tool メッセージ本文は下記の長さに切り詰める（Anthropic の
# context editing / clear_tool_uses と同方式。ツール結果の情報は直後の
# アシスタント応答に引き継がれているため、実用上の損失は小さい）
_TOOL_RESULT_KEEP_RECENT = 4
_OLD_TOOL_RESULT_MAX_CHARS = 500


def _truncate_old_tool_result(msg: dict) -> dict:
    """古いノードの role:tool メッセージ本文を切り詰める。それ以外は素通し。"""
    if msg.get("role") != "tool":
        return msg
    content = msg.get("content") or ""
    if len(content) <= _OLD_TOOL_RESULT_MAX_CHARS:
        return msg
    omitted = len(content) - _OLD_TOOL_RESULT_MAX_CHARS
    return {
        **msg,
        "content": content[:_OLD_TOOL_RESULT_MAX_CHARS]
        + f"\n...(古いツール結果のため以下 {omitted} 文字省略)",
    }


def _estimate_tokens(messages: list[dict]) -> int:
    """リクエストの推定トークン数。1 文字 ≈ 1 トークンの保守的な近似。

    日本語は 1 文字 1 トークン以上に分割されることもあるため、JSON 直列化長
    （キーや記号を含む）で数えて安全側に倒す。英語では過大評価になるが、
    早めに圧縮が走るだけで害はない。
    """
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)


class ChatSession:
    def __init__(
        self,
        tree: ChatTree,
        api: ApiHandler,
        store: ChatTreeStore,
        default_system_prompt: str = "",
        context_window: int | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self._tree = tree
        self._api = api
        self._store = store
        self._default_system_prompt = default_system_prompt
        self._context_window = context_window
        self._memory_store = memory_store
        self._display_text: str = ""   # 表示用（ToolIndicator を含む）
        self._save_text: str = ""       # 保存用（ToolIndicator を除くテキストのみ）
        self._pending_user_msg: str | None = None
        self._error_text: str = ""

    @property
    def streaming_text(self) -> str:
        """ストリーミング中のテキスト（ToolIndicator 含む）、またはエラーメッセージ。"""
        return self._display_text or self._error_text

    @property
    def pending_user_msg(self) -> str | None:
        return self._pending_user_msg

    def set_stream_error(self, msg: str) -> None:
        self._error_text = msg

    def prepare_streaming(self, msg: str) -> None:
        """ストリーミング開始前に pending 状態を設定し、レイアウトに pending_window を出現させる。"""
        self._pending_user_msg = msg
        self._error_text = ""

    @property
    def tree_id(self) -> str:
        return self._tree.tree_id

    def current_thread(self) -> list[ThreadEntry]:
        if self._tree.current_id is None:
            return []
        nodes = self._tree.thread(self._tree.current_id)
        result: list[ThreadEntry] = []
        for node in nodes:
            siblings = self._tree.siblings_with_self(node.id)
            sibling_count = len(siblings)
            sibling_index = siblings.index(node.id) + 1
            result.append(
                ThreadEntry(
                    node=node,
                    sibling_index=sibling_index,
                    sibling_count=sibling_count,
                )
            )
        return result

    @property
    def system_prompt(self) -> str:
        return self._tree.system_prompt

    @property
    def effective_system_prompt(self) -> str:
        return self._tree.system_prompt or self._default_system_prompt

    def set_system_prompt(self, prompt: str) -> None:
        self._tree.set_system_prompt(prompt)
        if self._tree.current_id is not None:
            self._store.save(self._tree)

    def _summary_state(self) -> tuple[str, list[ThreadEntry]]:
        """適用可能な要約と、生のまま送るエントリ列を返す。

        要約対象（summary_upto_id まで）が現在のスレッドパス上にある場合のみ
        要約を適用する。別ブランチにいる間は要約を使わず全ノードを送る。
        """
        entries = self.current_thread()
        summary = self._tree.summary
        upto = self._tree.summary_upto_id
        if summary and upto is not None:
            ids = [e.node.id for e in entries]
            if upto in ids:
                return summary, entries[ids.index(upto) + 1:]
        return "", entries

    def _build_thread_messages(self) -> list[dict]:
        summary, entries = self._summary_state()
        messages = []
        recent_boundary = len(entries) - _TOOL_RESULT_KEEP_RECENT
        for i, e in enumerate(entries):
            if e.node.tool_messages:
                tool_msgs = list(e.node.tool_messages)
                if i < recent_boundary:
                    tool_msgs = [_truncate_old_tool_result(m) for m in tool_msgs]
                messages.extend(tool_msgs)
            messages.append({"role": str(e.node.role), "content": e.node.content})
        system_parts = []
        if self.effective_system_prompt:
            system_parts.append(self.effective_system_prompt)
        if self._memory_store:
            memories = self._memory_store.list_all()
            if memories:
                lines = "\n".join(f"- {m['text']}" for m in memories)
                system_parts.append(f"[ユーザーに関する記憶]\n{lines}")
        if summary:
            system_parts.append(f"[これまでの会話の要約]\n{summary}")
        if system_parts:
            messages = [{"role": "system", "content": "\n\n".join(system_parts)}] + messages
        return messages

    async def _maybe_compact(self, next_msg: str) -> bool:
        """必要ならコンテキストを圧縮する。圧縮を実行したら True を返す。"""
        if not self._context_window:
            return False
        request = self._build_thread_messages() + [{"role": "user", "content": next_msg}]
        if _estimate_tokens(request) <= self._context_window * _COMPACT_TRIGGER_RATIO:
            return False
        prev_summary, entries = self._summary_state()
        if len(entries) <= _KEEP_RECENT_NODES:
            return False
        to_summarize = entries[:-_KEEP_RECENT_NODES]

        src: list[dict] = []
        if prev_summary:
            # 増分方式: 旧要約 + その後のノードを入力にして要約し直す
            src.append({"role": "user", "content": f"[これまでの会話の要約]\n{prev_summary}"})
        for e in to_summarize:
            src.append({"role": str(e.node.role), "content": e.node.content})

        summary = await self._api.summarize(src)
        if not summary:
            return False
        self._tree.set_summary(summary, to_summarize[-1].node.id)
        if self._tree.current_id is not None:
            self._store.save(self._tree)
        return True

    async def send_message(self, msg: str, invalidate: Callable[[], None]) -> None:
        self._error_text = ""
        self._pending_user_msg = msg
        self._display_text = ""
        self._save_text = ""
        try:
            if await self._maybe_compact(msg):
                # 表示専用の通知。_save_text には入れないためツリーには残らない。
                self._display_text = "[コンテキストを圧縮しました]\n"
                invalidate()
            thread_messages = self._build_thread_messages()
            async for chunk in self._api.stream(
                thread_messages + [{"role": "user", "content": msg}]
            ):
                self._display_text += chunk
                if not isinstance(chunk, ToolIndicator):
                    self._save_text += chunk
                invalidate()

            if not self._save_text:
                return

            tool_messages = tuple(self._api.last_tool_messages)
            user_id = self._tree.insert(self._tree.current_id, Role.USER, msg)
            asst_id = self._tree.insert(user_id, Role.ASSISTANT, self._save_text, tool_messages=tool_messages)
            self._tree.set_current(asst_id)
            try:
                self._store.save(self._tree)
            except Exception:
                self._tree.rollback()
                self._tree.rollback()
                raise
        finally:
            self._pending_user_msg = None
            self._display_text = ""
            self._save_text = ""

    def navigate_to(self, node_id: int | None) -> None:
        """current を移動する。None はルート（ツリー先頭からの分岐）を表す。"""
        self._tree.set_current(node_id)

    def navigate_to_branch_end(self, node_id: int) -> None:
        """指定ノードから長子を辿って末端まで移動する"""
        current = node_id
        while True:
            children = self._tree.children(current)
            if not children:
                break
            current = children[0]
        self._tree.set_current(current)

    def siblings_of(self, node_id: int) -> list[int]:
        return self._tree.siblings_with_self(node_id)

    @property
    def title(self) -> str:
        return self._tree.title

    def set_title(self, title: str) -> None:
        self._tree.set_title(title)
        self._store.save(self._tree)

    async def generate_title(self) -> str:
        title = await self._api.generate_title(self._build_thread_messages())
        self.set_title(title)
        return title

    def delete_tree(self, tree_id: str) -> bool:
        """ツリーを削除する。現在のツリーを削除した場合は新規ツリーに切り替えて True を返す"""
        is_current = tree_id == self._tree.tree_id
        self._store.delete(tree_id)
        if is_current:
            self._tree = self._store.new_tree()
        return is_current

    def list_trees(self) -> list[tuple[str, str]]:
        return self._store.list_trees()

    def load_tree(self, tree_id: str) -> None:
        self._tree = self._store.load(tree_id)

    def new_tree(self) -> None:
        self._tree = self._store.new_tree()

    @property
    def current_model(self) -> str:
        return self._api.model

    def set_model(self, model_id: str) -> None:
        self._api.set_model(model_id)

    async def list_models(self) -> list[str]:
        return await self._api.list_models()
