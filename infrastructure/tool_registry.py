from collections.abc import Callable


class ToolFunction:
    """@tool デコレータで作成される、定義・実装・インジケータの束。"""

    def __init__(
        self,
        fn: Callable[..., str],
        definition: dict,
        indicator: Callable[[dict], str] | None = None,
    ) -> None:
        self.definition = definition
        self.indicator = indicator
        self._fn = fn

    def __call__(self, args: dict) -> str:
        return self._fn(**args)


def tool(
    definition: dict,
    indicator: Callable[[dict], str] | None = None,
) -> Callable[[Callable[..., str]], ToolFunction]:
    """ツール定義と実装を一体化するデコレータ。"""
    def decorator(fn: Callable[..., str]) -> ToolFunction:
        return ToolFunction(fn, definition, indicator)
    return decorator


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolFunction] = {}

    def register(self, *tool_fns: ToolFunction) -> None:
        for tf in tool_fns:
            name = tf.definition["function"]["name"]
            self._tools[name] = tf

    def definitions(self) -> list[dict]:
        return [tf.definition for tf in self._tools.values()]

    def get(self, name: str) -> ToolFunction | None:
        return self._tools.get(name)

    def __bool__(self) -> bool:
        return bool(self._tools)
