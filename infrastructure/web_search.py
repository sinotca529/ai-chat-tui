from duckduckgo_search import DDGS
from .tool_registry import ToolRegistry

_DEFINITION = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
}


def _handler(args: dict) -> str:
    results = DDGS().text(args.get("query", ""), max_results=5)
    if not results:
        return "No results found."
    return "\n\n".join(f"[{r['title']}]({r['href']})\n{r['body']}" for r in results)


def _indicator(args: dict) -> str:
    return f"[web_search: {args.get('query', '')}]\n"


def register(registry: ToolRegistry) -> None:
    registry.register(_DEFINITION, _handler, _indicator)
