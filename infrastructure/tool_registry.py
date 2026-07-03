from dataclasses import dataclass
from collections.abc import Callable


@dataclass
class ToolEntry:
    definition: dict
    handler: Callable[[dict], str]
    indicator: Callable[[dict], str] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}

    def register(
        self,
        definition: dict,
        handler: Callable[[dict], str],
        indicator: Callable[[dict], str] | None = None,
    ) -> None:
        name = definition["function"]["name"]
        self._tools[name] = ToolEntry(definition, handler, indicator)

    def definitions(self) -> list[dict]:
        return [e.definition for e in self._tools.values()]

    def get(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def __bool__(self) -> bool:
        return bool(self._tools)
