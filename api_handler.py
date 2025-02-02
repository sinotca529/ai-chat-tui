from typing import Generator
from openai import OpenAI


class ApiHandler:
    def __init__(self, base_url: str, api_key: str, model: str):
        super().__init__()
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def send_message(
        self,
        thread: list[dict],
        msg: str
    ) -> Generator[str, None, None]:
        """OpenAI API にメッセージを送信"""

        thread = thread[:]  # shallow copy
        thread.append({"role": "user", "content": msg})

        stream = self.client.chat.completions.create(
            messages=thread,
            model=self.model,
            stream=True,
        )

        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content or ""
            except Exception:
                delta = ""
            yield delta
