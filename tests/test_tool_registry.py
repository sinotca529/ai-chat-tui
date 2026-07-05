from infrastructure.tool_registry import ToolRegistry, tool

_DEF = {
    "type": "function",
    "function": {
        "name": "greet",
        "description": "greet someone",
        "parameters": {"type": "object", "properties": {}},
    },
}


def test_tool_decorator_bundles_definition_and_implementation():
    @tool(_DEF, indicator=lambda args: f"[greet: {args['name']}]")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    assert greet.definition == _DEF
    assert greet({"name": "world"}) == "Hello, world!"
    assert greet.indicator({"name": "world"}) == "[greet: world]"


def test_registry_register_and_lookup():
    @tool(_DEF)
    def greet(name: str = "") -> str:
        return name

    registry = ToolRegistry()
    assert not registry  # 空レジストリは falsy → tools を API に送らない
    assert registry.definitions() == []
    assert registry.get("greet") is None

    registry.register(greet)
    assert registry
    assert registry.definitions() == [_DEF]
    assert registry.get("greet") is greet
