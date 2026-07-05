import httpx
import trafilatura

from .tool_registry import tool

_TIMEOUT_SECONDS = 15.0
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
_MAX_TEXT_CHARS = 8000  # コンテキスト保護のため抽出本文をこの長さで切り詰める

_HEADERS = {
    # 非ブラウザ UA を弾くサイトが多いため、実在ブラウザと同形式の UA を名乗る。
    # Chrome は UA 凍結によりマイナーバージョンを 0.0.0 に固定しているため、
    # この形式は実ブラウザと区別が付かず陳腐化もしにくい。
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja, en;q=0.7",
}


def _download(url: str) -> str:
    """URL の HTML を取得する。呼び出し側でハンドリングする例外を送出し得る。"""
    with httpx.Client(
        timeout=_TIMEOUT_SECONDS, headers=_HEADERS, follow_redirects=True
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        if len(response.content) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Content too large (> {_MAX_DOWNLOAD_BYTES} bytes)")
        return response.text


def _extract(html: str, url: str | None = None) -> str:
    """HTML から本文を Markdown で抽出し、長すぎる場合は切り詰める。"""
    text = trafilatura.extract(html, url=url, output_format="markdown")
    if not text:
        return "Could not extract readable content from this page."
    if len(text) > _MAX_TEXT_CHARS:
        omitted = len(text) - _MAX_TEXT_CHARS
        text = text[:_MAX_TEXT_CHARS] + f"\n\n...(以下 {omitted} 文字省略)"
    return text


@tool(
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch a web page by URL and return its main text content as Markdown. "
                "Use this to read the full content of pages found via web_search, "
                "or any URL the user mentions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The http(s) URL of the page to fetch",
                    },
                },
                "required": ["url"],
            },
        },
    },
    indicator=lambda args: f"[fetch_page: {args.get('url', '')}]\n",
)
def fetch_page(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"Error: only http(s) URLs are supported: {url}"
    try:
        html = _download(url)
    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} for {url}"
    except httpx.TimeoutException:
        return f"Error: request timed out after {_TIMEOUT_SECONDS}s: {url}"
    except (httpx.HTTPError, ValueError) as e:
        return f"Error: failed to fetch {url}: {e}"
    return _extract(html, url=url)
