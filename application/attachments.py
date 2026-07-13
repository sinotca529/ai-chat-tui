import os
import re

# 読み込んだ内容の文字数上限（超過分は切り詰め）
MAX_ATTACHMENT_CHARS = 20_000
# 読み込むファイルサイズの上限
MAX_FILE_BYTES = 5 * 1024 * 1024

# @"引用" / @'引用' / @エスケープ可能な非空白列 の 3 形式
_TOKEN_RE = re.compile(r'@(?:"([^"]+)"|\'([^\']+)\'|((?:\\ |\S)+))')
# これらで始まるトークンは「パスのつもり」とみなし、存在しなければエラーにする
_PATHISH_PREFIXES = ("/", "~", "./", "../")
# Windows のドライブレター形式 (C:\ / C:/) と MSYS (Git Bash) 形式 (/c/...)
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_MSYS_RE = re.compile(r"^/([A-Za-z])(/.*)?$")


def _is_pathish(raw: str, quoted: bool) -> bool:
    return (
        quoted
        or raw.startswith(_PATHISH_PREFIXES)
        or bool(_DRIVE_RE.match(raw))
        or raw.startswith("\\\\")  # UNC パス
    )


def _resolve_path(raw: str) -> str:
    """~ を展開し、必要なら MSYS 形式を Windows 形式に読み替えて返す。

    Git Bash (Windows Terminal) では /c/Users/... 形式が入力され得るが、
    Windows 版 Python はこれを解決できないため、存在しない場合に限り
    C:/Users/... へ読み替えて再試行する。
    """
    path = os.path.expanduser(raw)
    if os.path.exists(path):
        return path
    m = _MSYS_RE.match(raw)
    if m:
        alt = f"{m.group(1)}:{m.group(2) or '/'}"
        if os.path.exists(alt):
            return alt
    return path


def load_attachments(text: str) -> tuple[dict, ...]:
    """メッセージ中の @パス トークンを読み込み、スナップショットのタプルを返す。

    - `@"path with spaces"` / `@'path'` / `@path\\ with\\ spaces` に対応（D&D の
      ペースト形式を吸収）。`~` は展開する
    - パス風トークン（/ ~ ./ ../ 始まりまたは引用付き）が存在しない場合は
      ValueError（送信を中止して入力欄を復元させる）
    - パス風でないトークン（メールアドレス等の @）は、実在するファイルを
      指していない限り無視する
    """
    result: list[dict] = []
    seen: set[str] = set()
    for m in _TOKEN_RE.finditer(text):
        quoted = m.group(1) or m.group(2)
        raw = quoted if quoted is not None else m.group(3).replace("\\ ", " ")
        path = _resolve_path(raw)
        if not os.path.exists(path):
            if _is_pathish(raw, quoted is not None):
                raise ValueError(f"添付ファイルが見つかりません: {raw}")
            continue
        if os.path.isdir(path):
            raise ValueError(f"ディレクトリは添付できません: {raw}")
        if path in seen:
            continue
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise ValueError(f"添付ファイルが大きすぎます (> 5 MiB): {raw}")
        with open(path, "rb") as f:
            data = f.read()
        if b"\x00" in data[:8192]:
            raise ValueError(f"バイナリファイルは添付できません: {raw}")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"UTF-8 として読めないため添付できません: {raw}")
        if len(content) > MAX_ATTACHMENT_CHARS:
            omitted = len(content) - MAX_ATTACHMENT_CHARS
            content = content[:MAX_ATTACHMENT_CHARS] + f"\n...(以下 {omitted} 文字省略)"
        seen.add(path)
        result.append({"path": path, "content": content})
    return tuple(result)


def expand_message(content: str, attachments: tuple, max_chars: int | None = None) -> str:
    """API 送信用に、本文の後ろへ添付内容をフェンス付きで展開する。

    max_chars を指定すると各添付の内容をその長さに切り詰める
    （古いノードの添付を縮約して送るために使う）。
    """
    if not attachments:
        return content
    parts = [content]
    for a in attachments:
        body = a["content"]
        if max_chars is not None and len(body) > max_chars:
            omitted = len(body) - max_chars
            body = body[:max_chars] + f"\n...(古い添付のため以下 {omitted} 文字省略)"
        parts.append(f"[添付ファイル: {a['path']}]\n```\n{body}\n```")
    return "\n\n".join(parts)
