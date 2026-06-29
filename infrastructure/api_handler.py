import json
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
            kwargs = {"tools": tools} if tools else {}
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=current_messages,
                stream=True,
                **kwargs,
            )

            content_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}
            finish_reason = None

            async for chunk in response:
                choices = chunk.choices
                if not choices:
                    continue
                choice = choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                if choice.delta.content:
                    content_parts.append(choice.delta.content)
                    yield choice.delta.content
                if choice.delta.tool_calls:
                    for tc in choice.delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc.function.arguments

            if finish_reason != "tool_calls" or not tool_calls_acc:
                break

            current_messages.append({
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for _, tc in sorted(tool_calls_acc.items())
                ],
            })

            for _, tc in sorted(tool_calls_acc.items()):
                if tc["name"] == "web_search":
                    query = json.loads(tc["arguments"]).get("query", "")
                    yield f"\n[🔍 {query}]\n"
                    result = search(query)
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
