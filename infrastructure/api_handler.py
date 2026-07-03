import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncIterator
from openai import AsyncOpenAI
from .tool_registry import ToolRegistry

_MAX_TOOL_ROUNDS = 5


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
        tools = defs or None
        current_messages = list(messages)

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

    async def _stream_one_round(
        self, messages: list[dict], tools: list | None, out: _RoundResult
    ) -> AsyncIterator[str]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            **({"tools": tools} if tools else {}),
        )
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

        messages.append({
            "role": "assistant",
            "content": "".join(result.content) or None,
            "tool_calls": [
                {"id": tool_id, "type": "function",
                 "function": {"name": name, "arguments": raw_args}}
                for tool_id, name, raw_args, _ in sorted_tcs
            ],
        })

        for _, name, _, args in sorted_tcs:
            entry = self._registry.get(name)
            if entry and entry.indicator:
                yield ToolIndicator(entry.indicator(args))

        async def _run(tool_id: str, name: str, args: dict) -> tuple[str, str]:
            entry = self._registry.get(name)
            if entry is None:
                return tool_id, f"Unknown tool: {name}"
            content = await asyncio.to_thread(entry.handler, args)
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
            messages.append({"role": "tool", "tool_call_id": tool_id, "content": content})
