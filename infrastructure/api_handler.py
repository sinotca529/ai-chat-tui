import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncIterator
from openai import AsyncOpenAI, BadRequestError
from .tool_registry import ToolRegistry

_MAX_TOOL_ROUNDS = 5


def _strip_tool_messages(messages: list[dict]) -> list[dict]:
    """ツール関連メッセージ（role:tool / tool_calls 付き assistant）を除去する。

    ツール非対応サーバはこれらのメッセージ自体も拒否するため、
    フォールバック送信時は履歴からも取り除く必要がある。
    """
    result: list[dict] = []
    for m in messages:
        if m.get("role") == "tool":
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                result.append({"role": "assistant", "content": m["content"]})
            continue
        result.append(m)
    return result


class ToolIndicator(str):
    """ツール実行中の表示専用トークン。ツリーには保存しない。"""


@dataclass
class _RoundResult:
    content: list[str] = field(default_factory=list)
    tool_calls: dict[int, dict] = field(default_factory=dict)
    finish_reason: str | None = None


class ApiHandler:
    def __init__(
        self,
        url: str,
        api_key: str,
        model: str,
        api_key_header: str | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        if api_key_header:
            self._client = AsyncOpenAI(base_url=url, api_key="dummy", default_headers={api_key_header: api_key})
        else:
            self._client = AsyncOpenAI(base_url=url, api_key=api_key)
        self._model = model
        self._registry = registry or ToolRegistry()
        # None=未確認 / False=サーバがツール非対応（400 検出後のフォールバック済み）
        self._tools_supported: bool | None = None

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model_id: str) -> None:
        self._model = model_id

    async def generate_title(self, messages: list[dict]) -> str:
        prompt = messages + [{
            "role": "user",
            "content": "この会話に短いタイトルをつけてください。10〜20文字程度で、タイトルのみ返してください。",
        }]
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=prompt,
            stream=False,
        )
        if not response.choices:
            return ""
        title = response.choices[0].message.content.strip()
        if title.startswith("「") and title.endswith("」"):
            title = title[1:-1]
        return title

    async def list_models(self) -> list[str]:
        response = await self._client.models.list()
        return sorted(m.id for m in response.data)

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        defs = self._registry.definitions()
        tools = defs if (defs and self._tools_supported is not False) else None
        current_messages = list(messages)
        if self._tools_supported is False:
            # 過去にツール対応サーバで作られた履歴が混ざっていても送れるようにする
            current_messages = _strip_tool_messages(current_messages)
        self._tool_message_log: list[dict] = []

        for _ in range(_MAX_TOOL_ROUNDS):
            result = _RoundResult()
            async for token in self._stream_one_round(current_messages, tools, result):
                yield token
            if result.finish_reason != "tool_calls" or not result.tool_calls:
                break
            async for indicator in self._execute_tool_calls(result, current_messages):
                yield indicator
        else:
            # ツールラウンド上限に達した場合、tools=None で最終テキスト応答を強制する
            async for token in self._stream_one_round(current_messages, None, _RoundResult()):
                yield token

    @property
    def last_tool_messages(self) -> list[dict]:
        return self._tool_message_log

    async def _stream_one_round(
        self, messages: list[dict], tools: list | None, out: _RoundResult
    ) -> AsyncIterator[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                **({"tools": tools} if tools else {}),
            )
        except BadRequestError:
            if not tools:
                raise
            # サーバがツール非対応の可能性: tools なし + ツール関連メッセージ除去で
            # 1 回だけ再試行する。ここでも失敗する場合は tools 起因ではないので、
            # その例外をそのまま伝播させる（対処療法で握りつぶさない）。
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=_strip_tool_messages(messages),
                stream=True,
            )
            self._tools_supported = False
            yield ToolIndicator("[サーバがツール非対応のためツールなしで再送信しました]\n")
        async for chunk in response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                out.finish_reason = choice.finish_reason
            if choice.delta.content:
                out.content.append(choice.delta.content)
                yield choice.delta.content
            if choice.delta.tool_calls:
                for tc in choice.delta.tool_calls:
                    self._accumulate_tool_call(out.tool_calls, tc)

    def _accumulate_tool_call(self, acc: dict[int, dict], tc) -> None:
        idx = tc.index
        if idx not in acc:
            acc[idx] = {"id": "", "name": "", "arguments": ""}
        if tc.id:
            acc[idx]["id"] = tc.id
        if tc.function:
            if tc.function.name:
                acc[idx]["name"] += tc.function.name
            if tc.function.arguments:
                acc[idx]["arguments"] += tc.function.arguments

    async def _execute_tool_calls(
        self, result: _RoundResult, messages: list[dict]
    ) -> AsyncIterator[str]:
        sorted_tcs = [
            (tc["id"], tc["name"], tc["arguments"], json.loads(tc["arguments"] or "{}"))
            for _, tc in sorted(result.tool_calls.items())
        ]

        asst_msg = {
            "role": "assistant",
            "content": "".join(result.content) or None,
            "tool_calls": [
                {"id": tool_id, "type": "function",
                 "function": {"name": name, "arguments": raw_args}}
                for tool_id, name, raw_args, _ in sorted_tcs
            ],
        }
        messages.append(asst_msg)
        self._tool_message_log.append(asst_msg)

        for _, name, _, args in sorted_tcs:
            entry = self._registry.get(name)
            if entry and entry.indicator:
                yield ToolIndicator(entry.indicator(args))

        async def _run(tool_id: str, name: str, args: dict) -> tuple[str, str]:
            tf = self._registry.get(name)
            if tf is None:
                return tool_id, f"Unknown tool: {name}"
            content = await asyncio.to_thread(tf, args)
            return tool_id, content

        # return_exceptions=True: ハンドラ例外をキャプチャし、必ずツール結果を補完する。
        # 補完しないと assistant の tool_calls メッセージだけ残り次の API 呼び出しが 400 になる。
        outcomes = await asyncio.gather(
            *[_run(tid, name, args) for tid, name, _, args in sorted_tcs],
            return_exceptions=True,
        )

        for i, outcome in enumerate(outcomes):
            tool_id = sorted_tcs[i][0]
            content = f"Tool error: {outcome}" if isinstance(outcome, Exception) else outcome[1]
            tool_msg = {"role": "tool", "tool_call_id": tool_id, "content": content}
            messages.append(tool_msg)
            self._tool_message_log.append(tool_msg)
