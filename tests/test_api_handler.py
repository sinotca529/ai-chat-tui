from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from infrastructure.api_handler import ApiHandler, ToolIndicator, _MAX_TOOL_ROUNDS
from infrastructure.tool_registry import ToolRegistry, tool


def _bad_request(msg: str = "tools is not supported") -> BadRequestError:
    request = httpx.Request("POST", "http://fake/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": msg}})
    return BadRequestError(msg, response=response, body=None)


def _text_chunk(text: str | None = None, finish: str | None = None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish,
            delta=SimpleNamespace(content=text, tool_calls=None),
        )]
    )


def _tool_chunk(index: int, id: str | None = None, name: str | None = None,
                arguments: str | None = None, finish: str | None = None):
    tc = SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish,
            delta=SimpleNamespace(content=None, tool_calls=[tc]),
        )]
    )


class _FakeCompletions:
    """ラウンドごとのチャンク列を返す chat.completions スタブ。"""

    def __init__(self, rounds: list[list]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self._rounds.pop(0)
        if kwargs.get("stream"):
            async def gen():
                for c in chunks:
                    yield c
            return gen()
        return chunks  # 非ストリーミング（generate_title 用）は応答オブジェクトそのもの


def _make_handler(rounds: list[list], registry: ToolRegistry | None = None):
    handler = ApiHandler(url="http://fake", api_key="k", model="m", registry=registry)
    completions = _FakeCompletions(rounds)
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return handler, completions


def _echo_registry() -> ToolRegistry:
    @tool(
        {"type": "function",
         "function": {"name": "echo", "description": "echo",
                      "parameters": {"type": "object", "properties": {}}}},
        indicator=lambda args: f"[echo: {args.get('text', '')}]\n",
    )
    def echo(text: str = "") -> str:
        return f"echoed:{text}"

    registry = ToolRegistry()
    registry.register(echo)
    return registry


async def _collect(handler: ApiHandler, messages: list[dict]) -> list[str]:
    return [chunk async for chunk in handler.stream(messages)]


async def test_plain_text_stream():
    handler, completions = _make_handler(
        [[_text_chunk("Hel"), _text_chunk("lo"), _text_chunk(finish="stop")]]
    )
    chunks = await _collect(handler, [{"role": "user", "content": "hi"}])
    assert chunks == ["Hel", "lo"]
    assert handler.last_tool_messages == []
    assert len(completions.calls) == 1
    assert "tools" not in completions.calls[0]  # レジストリが空なら tools を送らない


async def test_tool_call_round_trip():
    rounds = [
        # 1 ラウンド目: arguments が複数チャンクに分割されて届く
        [
            _tool_chunk(0, id="t1", name="echo", arguments='{"tex'),
            _tool_chunk(0, arguments='t": "abc"}'),
            _text_chunk(finish="tool_calls"),
        ],
        # 2 ラウンド目: ツール結果を受けた最終応答
        [_text_chunk("done"), _text_chunk(finish="stop")],
    ]
    handler, completions = _make_handler(rounds, registry=_echo_registry())
    chunks = await _collect(handler, [{"role": "user", "content": "echo abc"}])

    # インジケータ → 最終応答の順で yield される
    assert isinstance(chunks[0], ToolIndicator)
    assert chunks[0] == "[echo: abc]\n"
    assert chunks[1] == "done"

    # 中間メッセージ列: assistant(tool_calls) + tool 結果
    assert [m["role"] for m in handler.last_tool_messages] == ["assistant", "tool"]
    assert handler.last_tool_messages[1]["content"] == "echoed:abc"
    assert handler.last_tool_messages[1]["tool_call_id"] == "t1"

    # 2 回目の API 呼び出しには中間メッセージが含まれる
    second_messages = completions.calls[1]["messages"]
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-2]["tool_calls"][0]["function"]["arguments"] == '{"text": "abc"}'


async def test_unknown_tool_returns_error_content():
    rounds = [
        [
            _tool_chunk(0, id="t1", name="nonexistent", arguments="{}"),
            _text_chunk(finish="tool_calls"),
        ],
        [_text_chunk("ok", finish="stop")],
    ]
    handler, _ = _make_handler(rounds, registry=_echo_registry())
    await _collect(handler, [])
    assert handler.last_tool_messages[1]["content"] == "Unknown tool: nonexistent"


async def test_tool_exception_is_captured_as_tool_error():
    @tool({"type": "function",
           "function": {"name": "broken", "description": "",
                        "parameters": {"type": "object", "properties": {}}}})
    def broken() -> str:
        raise ValueError("boom")

    registry = ToolRegistry()
    registry.register(broken)
    rounds = [
        [
            _tool_chunk(0, id="t1", name="broken", arguments="{}"),
            _text_chunk(finish="tool_calls"),
        ],
        [_text_chunk("recovered", finish="stop")],
    ]
    handler, _ = _make_handler(rounds, registry=registry)
    chunks = await _collect(handler, [])

    # ツール例外でもストリームは継続し、tool 結果メッセージが必ず補完される
    assert chunks[-1] == "recovered"
    assert handler.last_tool_messages[1]["content"].startswith("Tool error:")


async def test_max_tool_rounds_forces_final_text_response():
    tool_round = [
        _tool_chunk(0, id="t1", name="echo", arguments="{}"),
        _text_chunk(finish="tool_calls"),
    ]
    rounds = [list(tool_round) for _ in range(_MAX_TOOL_ROUNDS)]
    rounds.append([_text_chunk("forced final", finish="stop")])

    handler, completions = _make_handler(rounds, registry=_echo_registry())
    chunks = await _collect(handler, [])

    assert chunks[-1] == "forced final"
    assert len(completions.calls) == _MAX_TOOL_ROUNDS + 1
    assert "tools" not in completions.calls[-1]  # 最終ラウンドは tools なしで強制


class _ToolRejectingCompletions(_FakeCompletions):
    """tools パラメータ付きのリクエストを 400 で拒否するスタブ（ツール非対応サーバ）。"""

    async def create(self, **kwargs):
        if "tools" in kwargs:
            self.calls.append(kwargs)
            raise _bad_request()
        return await super().create(**kwargs)


class _AlwaysRejectingCompletions:
    """全リクエストを 400 で拒否するスタブ。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise _bad_request("some other bad request")


async def test_tools_unsupported_server_falls_back_without_tools():
    rounds = [
        [_text_chunk("こんにちは", finish="stop")],
        [_text_chunk("二回目", finish="stop")],
    ]
    handler, _ = _make_handler([], registry=_echo_registry())
    completions = _ToolRejectingCompletions(rounds)
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    chunks = await _collect(handler, [{"role": "user", "content": "hi"}])

    # フォールバック通知（表示専用）→ 本文の順で yield される
    assert isinstance(chunks[0], ToolIndicator)
    assert chunks[1] == "こんにちは"
    # 1 回目: tools 付きで 400 → 2 回目: tools なしで再送信
    assert "tools" in completions.calls[0]
    assert "tools" not in completions.calls[1]

    # 以後のリクエストは最初から tools を送らない（再試行の往復が発生しない）
    chunks2 = await _collect(handler, [{"role": "user", "content": "again"}])
    assert chunks2 == ["二回目"]
    assert len(completions.calls) == 3
    assert "tools" not in completions.calls[2]


async def test_fallback_strips_tool_messages_from_history():
    """過去にツール対応サーバで作られた履歴（role:tool 等）も除去して送る"""
    history = [
        {"role": "user", "content": "調べて"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "web_search", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
        {"role": "assistant", "content": "回答"},
        {"role": "user", "content": "続けて"},
    ]
    rounds = [
        [_text_chunk("ok", finish="stop")],
        [_text_chunk("ok2", finish="stop")],
    ]
    handler, _ = _make_handler([], registry=_echo_registry())
    completions = _ToolRejectingCompletions(rounds)
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    await _collect(handler, history)
    retry_messages = completions.calls[1]["messages"]
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[1] == {"role": "assistant", "content": "回答"}

    # フォールバック確定後の 2 通目でも履歴からツール関連メッセージを除去する
    await _collect(handler, history)
    assert [m["role"] for m in completions.calls[2]["messages"]] == [
        "user", "assistant", "user",
    ]


async def test_bad_request_without_tools_propagates():
    """tools を送っていないリクエストの 400 は再試行せずそのまま伝播する"""
    handler, _ = _make_handler([])  # レジストリ空 = tools なし
    completions = _AlwaysRejectingCompletions()
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(BadRequestError):
        await _collect(handler, [{"role": "user", "content": "hi"}])
    assert len(completions.calls) == 1  # 再試行しない


async def test_fallback_retry_failure_propagates_and_keeps_tools_enabled():
    """再試行も 400 なら tools 起因ではないので例外を伝播し、ツールは無効化しない"""
    handler, _ = _make_handler([], registry=_echo_registry())
    completions = _AlwaysRejectingCompletions()
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(BadRequestError):
        await _collect(handler, [{"role": "user", "content": "hi"}])
    assert len(completions.calls) == 2  # tools 付き → tools なしの 2 回で打ち切り

    # 次のリクエストでは引き続き tools を送る（誤って無効化されていない）
    with pytest.raises(BadRequestError):
        await _collect(handler, [{"role": "user", "content": "hi"}])
    assert "tools" in completions.calls[2]


async def test_set_model_resets_tools_fallback():
    """別モデルへの切り替えでフォールバック状態を破棄し、tools を再送する。

    ツール非対応モデルで一度フォールバックした後、ツール対応モデルに
    切り替えてもツールが無効のままになる回帰を防ぐ。
    """
    rounds = [
        [_text_chunk("a", finish="stop")],
        [_text_chunk("b", finish="stop")],
    ]
    handler, _ = _make_handler([], registry=_echo_registry())
    completions = _ToolRejectingCompletions(rounds)
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    await _collect(handler, [{"role": "user", "content": "hi"}])  # フォールバック発動
    assert "tools" not in completions.calls[1]

    handler.set_model("tool-capable-model")
    await _collect(handler, [{"role": "user", "content": "hi"}])
    # リセットされたので tools 付きで再確認している（このスタブでは再び 400 →
    # 再フォールバックするが、tools を送り直したこと自体が検証点）
    assert "tools" in completions.calls[2]


async def test_set_model_same_model_keeps_fallback_state():
    """同一モデルの再選択ではフォールバック状態を維持する（往復を増やさない）"""
    rounds = [
        [_text_chunk("a", finish="stop")],
        [_text_chunk("b", finish="stop")],
    ]
    handler, _ = _make_handler([], registry=_echo_registry())
    completions = _ToolRejectingCompletions(rounds)
    handler._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    await _collect(handler, [{"role": "user", "content": "hi"}])  # フォールバック発動
    handler.set_model(handler.model)  # 同じモデルを再選択
    await _collect(handler, [{"role": "user", "content": "hi"}])

    # 3 リクエスト目は最初から tools なし（tools 付きの再確認をしていない）
    assert len(completions.calls) == 3
    assert "tools" not in completions.calls[2]


def test_last_tool_messages_is_empty_before_first_stream():
    """stream() 前に last_tool_messages を読んでも AttributeError にならない"""
    handler, _ = _make_handler([])
    assert handler.last_tool_messages == []


async def test_generate_title_strips_brackets():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="「テスト会話」"))]
    )
    handler, _ = _make_handler([response])
    title = await handler.generate_title([])
    assert title == "テスト会話"


async def test_generate_title_empty_choices_returns_empty():
    handler, _ = _make_handler([SimpleNamespace(choices=[])])
    assert await handler.generate_title([]) == ""
