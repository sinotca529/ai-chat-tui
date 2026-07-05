import httpx

from infrastructure import web_fetch
from infrastructure.web_fetch import _extract, fetch_page

_SAMPLE_HTML = """
<html>
  <head><title>テストページ</title><script>alert('x')</script></head>
  <body>
    <nav><a href="/">ホーム</a><a href="/about">概要</a></nav>
    <article>
      <h1>記事タイトル</h1>
      <p>これは本文の最初の段落です。重要な情報が含まれています。</p>
      <p>これは二番目の段落です。さらに詳しい説明が続きます。</p>
    </article>
    <footer>Copyright 2026</footer>
  </body>
</html>
"""


def test_extract_returns_main_content():
    text = _extract(_SAMPLE_HTML)
    assert "本文の最初の段落" in text
    assert "二番目の段落" in text
    assert "alert" not in text  # script は除去される


def test_extract_unreadable_html_returns_message():
    assert "Could not extract" in _extract("<html><body></body></html>")


def test_extract_truncates_long_content():
    long_html = (
        "<html><body><article><h1>長い記事</h1>"
        + "".join(f"<p>段落{i}:" + "あ" * 200 + "</p>" for i in range(100))
        + "</article></body></html>"
    )
    text = _extract(long_html)
    assert len(text) < web_fetch._MAX_TEXT_CHARS + 100  # 切り詰め + 省略表記
    assert "省略" in text


def test_fetch_page_rejects_non_http_schemes(monkeypatch):
    def _fail(url):
        raise AssertionError("download should not be attempted")

    monkeypatch.setattr(web_fetch, "_download", _fail)
    assert "only http(s)" in fetch_page({"url": "file:///etc/passwd"})
    assert "only http(s)" in fetch_page({"url": "ftp://example.com/x"})


def test_fetch_page_returns_extracted_text(monkeypatch):
    monkeypatch.setattr(web_fetch, "_download", lambda url: _SAMPLE_HTML)
    result = fetch_page({"url": "https://example.com/article"})
    assert "本文の最初の段落" in result


def test_fetch_page_maps_http_status_error_to_message(monkeypatch):
    def _raise_404(url):
        request = httpx.Request("GET", url)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("404", request=request, response=response)

    monkeypatch.setattr(web_fetch, "_download", _raise_404)
    result = fetch_page({"url": "https://example.com/missing"})
    assert "HTTP 404" in result


def test_fetch_page_maps_timeout_to_message(monkeypatch):
    def _raise_timeout(url):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(web_fetch, "_download", _raise_timeout)
    result = fetch_page({"url": "https://example.com/slow"})
    assert "timed out" in result


def test_fetch_page_maps_network_error_to_message(monkeypatch):
    def _raise_network(url):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(web_fetch, "_download", _raise_network)
    result = fetch_page({"url": "https://example.com/down"})
    assert "failed to fetch" in result


def test_fetch_page_maps_oversize_to_message(monkeypatch):
    def _raise_too_large(url):
        raise ValueError("Content too large (> 5242880 bytes)")

    monkeypatch.setattr(web_fetch, "_download", _raise_too_large)
    result = fetch_page({"url": "https://example.com/huge"})
    assert "failed to fetch" in result


def test_tool_definition_and_indicator():
    assert fetch_page.definition["function"]["name"] == "fetch_page"
    assert "url" in fetch_page.definition["function"]["parameters"]["required"]
    assert fetch_page.indicator({"url": "https://x.jp"}) == "[fetch_page: https://x.jp]\n"
