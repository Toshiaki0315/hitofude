"""コードの字句解析（B-6 / 画面用）。

書き出し（`core/html.py`）は Pygments に HTML を組ませればよいが、画面は
`QSyntaxHighlighter` が**行単位**で動くので、行ごとの位置と色が要る。

**1 行ずつ解析してはいけない。** 複数行の文字列やコメントは行をまたぐので、
その行だけを見ると中身の `def` が予約語に見えてしまう。コードブロック全体を
1 回解析して、結果を行に割る。

`core/` にあるので PySide6 に依存しない（R3）。
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

from pygments.lexers import get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound

from hitofude.core.html import DARK_CODE_STYLE, LIGHT_CODE_STYLE

logger = logging.getLogger(__name__)

# 同じコードを何度も解析しない。打鍵のたびにブロック全体を解析し直すので、
# カーソル移動だけで色が変わらない場面では効く
_CACHE_SIZE = 8


@dataclass(frozen=True, slots=True)
class CodeSpan:
    """1 行の中の色を付ける範囲。`[start, start + length)`。"""

    start: int
    length: int
    color: str
    """`#RRGGBB`。"""

    bold: bool = False
    italic: bool = False


def tokenize(code: str, lang: str, *, dark: bool = False) -> list[list[CodeSpan]]:
    """コードを行ごとの `CodeSpan` に分ける。

    知らない言語では空のリストを返す（色を付けない）。**付けられないより、
    素で出るほうがよい。**
    """
    return [list(line) for line in _tokenize_cached(code, lang, dark)]


@lru_cache(maxsize=_CACHE_SIZE)
def _tokenize_cached(code: str, lang: str, dark: bool) -> tuple[tuple[CodeSpan, ...], ...]:
    lines: list[list[CodeSpan]] = [[] for _ in range(code.count("\n") + 1)]
    lexer = _lexer(lang)
    if lexer is None:
        return tuple(tuple(line) for line in lines)

    styles = _styles(dark)
    line, column = 0, 0
    for _, token_type, value in lexer.get_tokens_unprocessed(code):
        style = styles.get(token_type)
        for index, piece in enumerate(value.split("\n")):
            if index:
                line, column = line + 1, 0
            if piece and style is not None and line < len(lines):
                lines[line].append(
                    CodeSpan(column, len(piece), style[0], bold=style[1], italic=style[2])
                )
            column += len(piece)
    return tuple(tuple(entry) for entry in lines)


@lru_cache(maxsize=4)
def _lexer(lang: str):
    if not lang:
        return None
    try:
        return get_lexer_by_name(lang, stripnl=False)
    except ClassNotFound:
        logger.debug("知らない言語: %s", lang)
        return None


@lru_cache(maxsize=2)
def _styles(dark: bool) -> dict:
    """トークンの種類 → `(色, 太字, 斜体)`。

    Pygments の配色をそのまま引く。**書き出し（`core/html.py`）と同じ配色**を
    使う。画面と書き出しで色が違うと、どちらが本当か分からなくなる。
    """
    style = get_style_by_name(DARK_CODE_STYLE if dark else LIGHT_CODE_STYLE)
    found = {}
    for token_type, entry in style:
        if entry["color"]:
            found[token_type] = (f"#{entry['color']}", bool(entry["bold"]), bool(entry["italic"]))
    return found
