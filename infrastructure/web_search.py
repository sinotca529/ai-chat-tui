import warnings
from duckduckgo_search import DDGS
from .tool_registry import tool

@tool(
    {
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
    },
    indicator=lambda args: f"[web_search: {args.get('query', '')}]\n",
)
def web_search(query: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        results = DDGS().text(query, max_results=5)
    if not results:
        return "No results found."
    return "\n\n".join(f"[{r['title']}]({r['href']})\n{r['body']}" for r in results)
