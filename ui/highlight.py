import re
from typing import Iterator
from prompt_toolkit.formatted_text import StyleAndTextTuples

_FENCE_RE = re.compile(r'```(\w*)\n(.*?)(?:```|$)', re.DOTALL)


def iter_content(text: str) -> Iterator[tuple[bool, str | None, str]]:
    """(is_code, lang, text) を順に yield する"""
    last = 0
    for m in _FENCE_RE.finditer(text):
        if m.start() > last:
            yield False, None, text[last:m.start()]
        lang = m.group(1).strip() or None
        yield True, lang, m.group(2)
        last = m.end()
    if last < len(text):
        yield False, None, text[last:]


def highlight_code(code: str, lang: str | None) -> StyleAndTextTuples:
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.lexers.special import TextLexer
    from pygments.util import ClassNotFound
    from prompt_toolkit.formatted_text import PygmentsTokens, to_formatted_text

    try:
        lexer = get_lexer_by_name(lang, stripnl=False) if lang else guess_lexer(code, stripnl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False)

    return list(to_formatted_text(PygmentsTokens(list(lexer.get_tokens(code)))))
