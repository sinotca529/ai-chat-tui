import json
from dataclasses import dataclass, field
from typing import AsyncIterator
from openai import AsyncOpenAI
from .web_search import search


_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for recent or current information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
}

_MAX_TOOL_ROUNDS = 5


@dataclass
class _RoundResult:
    content: list[str] = field(default_factory=list)
    tool_calls: dict[int, dict] = field(default_factory=dict)
    finish_reason: str | None = None


class ApiHandler:
    def __init__(self, url: str, api_key: str, model: str, api_key_header: str | None = None, tools_enabled: bool = False) -> None:
        if api_key_header:
            self._client = AsyncOpenAI(base_url=url, api_key="dummy", default_headers={api_key_header: api_key})
        else:
            self._client = AsyncOpenAI(base_url=url, api_key=api_key)
        self._model = model
        self._tools_enabled = tools_enabled

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
        tools = [_SEARCH_TOOL] if self._tools_enabled else None
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
        messages.append({
            "role": "assistant",
            "content": "".join(result.content) or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for _, tc in sorted(result.tool_calls.items())
            ],
        })
        for _, tc in sorted(result.tool_calls.items()):
            if tc["name"] == "web_search":
                query = json.loads(tc["arguments"]).get("query", "")
                yield f"\n[🔍 {query}]\n"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": search(query),
                })
