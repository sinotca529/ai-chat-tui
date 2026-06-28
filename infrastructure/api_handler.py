from typing import AsyncIterator
from openai import AsyncOpenAI


class ApiHandler:
    def __init__(self, url: str, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(base_url=url, api_key=api_key)
        self._model = model

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
        return response.choices[0].message.content.strip()

    async def list_models(self) -> list[str]:
        response = await self._client.models.list()
        return sorted(m.id for m in response.data)

    async def stream(
        self, thread: list[dict], new_message: str
    ) -> AsyncIterator[str]:
        messages = thread + [{"role": "user", "content": new_message}]
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
