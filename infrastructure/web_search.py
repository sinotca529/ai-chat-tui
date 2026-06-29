from duckduckgo_search import DDGS


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
