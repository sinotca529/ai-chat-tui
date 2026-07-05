from ui.highlight import highlight_code, iter_content


def test_plain_text_only():
    assert list(iter_content("hello world")) == [(False, None, "hello world")]


def test_fenced_code_with_language():
    text = "before\n```python\nprint(1)\n```\nafter"
    segments = list(iter_content(text))
    assert segments == [
        (False, None, "before\n"),
        (True, "python", "print(1)\n"),
        (False, None, "\nafter"),
    ]


def test_fence_without_language():
    segments = list(iter_content("```\nplain code\n```"))
    assert segments == [(True, None, "plain code\n")]


def test_unterminated_fence_streams_as_code():
    """ストリーミング途中の未閉鎖フェンスもコードとして扱う。
    非貪欲マッチ + $ の仕様上、末尾の改行はコード外の平文になる。"""
    segments = list(iter_content("say:\n```python\nx = 1\n"))
    assert segments == [
        (False, None, "say:\n"),
        (True, "python", "x = 1"),
        (False, None, "\n"),
    ]


def test_highlight_code_returns_style_text_tuples():
    result = highlight_code("x = 1\n", "python")
    assert "".join(text for _, text in result) == "x = 1\n"
    assert any(style for style, _ in result)  # 何らかのスタイルが付与される


def test_highlight_code_unknown_language_falls_back_to_plain():
    result = highlight_code("some text\n", "no-such-lang")
    assert "".join(text for _, text in result) == "some text\n"
