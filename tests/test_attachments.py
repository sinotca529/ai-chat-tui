import pytest

from application import attachments
from application.attachments import expand_message, load_attachments


@pytest.fixture
def spec_file(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("仕様書の中身", encoding="utf-8")
    return f


def test_load_plain_path(spec_file):
    result = load_attachments(f"これを読んで @{spec_file}")
    assert len(result) == 1
    assert result[0]["path"] == str(spec_file)
    assert result[0]["content"] == "仕様書の中身"


def test_load_quoted_paths_with_spaces(tmp_path):
    f = tmp_path / "my file.txt"
    f.write_text("スペース入り", encoding="utf-8")
    for token in (f'@"{f}"', f"@'{f}'", "@" + str(f).replace(" ", "\\ ")):
        result = load_attachments(f"読んで {token}")
        assert result[0]["content"] == "スペース入り", token


def test_tilde_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "note.md").write_text("ホームのメモ", encoding="utf-8")
    result = load_attachments("@~/note.md を見て")
    assert result[0]["content"] == "ホームのメモ"


def test_non_path_at_tokens_are_ignored():
    assert load_attachments("メールは taro@example.com です") == ()
    assert load_attachments("Python の @dataclass について教えて") == ()


def test_missing_pathish_token_raises(tmp_path):
    with pytest.raises(ValueError, match="見つかりません"):
        load_attachments(f"@{tmp_path}/no_such_file.md を読んで")
    with pytest.raises(ValueError, match="見つかりません"):
        load_attachments("@~/no_such_file_xyz.md")
    with pytest.raises(ValueError, match="見つかりません"):
        load_attachments('@"/no/such/quoted path.md"')


def test_directory_raises(tmp_path):
    with pytest.raises(ValueError, match="ディレクトリ"):
        load_attachments(f"@{tmp_path}")


def test_binary_file_raises(tmp_path):
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\x00\x1a\ndata")
    with pytest.raises(ValueError, match="バイナリ"):
        load_attachments(f"@{f}")


def test_non_utf8_raises(tmp_path):
    f = tmp_path / "sjis.txt"
    f.write_bytes("日本語".encode("cp932"))
    with pytest.raises(ValueError, match="UTF-8"):
        load_attachments(f"@{f}")


def test_oversize_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 10)
    f = tmp_path / "big.txt"
    f.write_text("12345678901", encoding="utf-8")
    with pytest.raises(ValueError, match="大きすぎます"):
        load_attachments(f"@{f}")


def test_long_content_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_ATTACHMENT_CHARS", 100)
    f = tmp_path / "long.txt"
    f.write_text("あ" * 150, encoding="utf-8")
    result = load_attachments(f"@{f}")
    assert result[0]["content"].startswith("あ" * 100)
    assert "50 文字省略" in result[0]["content"]


def test_duplicate_paths_deduped(spec_file):
    result = load_attachments(f"@{spec_file} と @{spec_file}")
    assert len(result) == 1


def test_expand_message_appends_fenced_content(spec_file):
    atts = load_attachments(f"@{spec_file}")
    expanded = expand_message("読んで", atts)
    assert expanded.startswith("読んで\n\n")
    assert f"[添付ファイル: {spec_file}]" in expanded
    assert "```\n仕様書の中身\n```" in expanded


def test_expand_message_truncates_for_old_nodes(spec_file):
    atts = ({"path": str(spec_file), "content": "x" * 600},)
    expanded = expand_message("読んで", atts, max_chars=500)
    assert "x" * 500 in expanded
    assert "x" * 501 not in expanded
    assert "省略" in expanded


def test_expand_message_without_attachments_is_identity():
    assert expand_message("そのまま", ()) == "そのまま"
