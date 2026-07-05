import asyncio

import pytest

from application.chat_session import ChatSession
from domain.chat_tree import ChatTree
from infrastructure.chat_tree_store import ChatTreeStore


class FakeApiHandler:
    """ApiHandler と同じインターフェースを持つテスト用フェイク。

    実 API を一切呼ばない。chunks に str（通常トークン）・ToolIndicator・
    Exception（送出）を混在させてストリーミングの各シナリオを再現できる。
    block_forever=True にするとキャンセルのテストに使える。
    """

    def __init__(
        self,
        chunks: tuple = ("Hi!",),
        title: str = "生成タイトル",
        tool_messages: tuple = (),
        block_forever: bool = False,
        summary_text: str = "これまでの要約",
    ) -> None:
        self.chunks = chunks
        self.title = title
        self.model = "fake-model"
        self.last_tool_messages = list(tool_messages)
        self.block_forever = block_forever
        self.sent_messages: list[dict] | None = None  # 直近の stream() 呼び出し引数
        self.summary_text = summary_text
        self.summarize_calls: list[list[dict]] = []  # summarize() の入力履歴

    async def stream(self, messages: list[dict]):
        self.sent_messages = messages
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk
        if self.block_forever:
            await asyncio.Event().wait()

    async def generate_title(self, messages: list[dict]) -> str:
        return self.title

    async def summarize(self, messages: list[dict]) -> str:
        self.summarize_calls.append(messages)
        return self.summary_text

    async def list_models(self) -> list[str]:
        return ["fake-model", "other-model"]

    def set_model(self, model_id: str) -> None:
        self.model = model_id


@pytest.fixture
def store(tmp_path) -> ChatTreeStore:
    return ChatTreeStore(str(tmp_path / "trees"))


@pytest.fixture
def fake_api() -> FakeApiHandler:
    return FakeApiHandler()


@pytest.fixture
def session(store, fake_api) -> ChatSession:
    return ChatSession(tree=ChatTree(), api=fake_api, store=store)
