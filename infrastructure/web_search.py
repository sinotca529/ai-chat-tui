from duckduckgo_search import DDGS
from .tool_registry import ToolRegistry


_DEFINITION = {
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


def search(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return f"検索に失敗しました: {e}"
    if not results:
        return "検索結果が見つかりませんでした。"
    return "\n\n".join(
        f"## {r['title']}\n{r['body']}\n{r['href']}"
        for r in results
    )


def register(registry: ToolRegistry) -> None:
    registry.register(
        _DEFINITION,
        lambda args: search(args.get("query", "")),
        indicator=lambda args: f"\n[🔍 {args.get('query', '')}]\n",
    )
