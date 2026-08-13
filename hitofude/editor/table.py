"""表の整形（spec §1.2「等幅フォント + 罫線揃え」）。

記法は GFM / Qiita と同じ。`|` で区切り、2 行目の `---` で列を確定し、
`:---` `---:` `:---:` で寄せを指定する。

v1 は WYSIWYG な表エディタを作らない（§1.2 の非ゴール）。代わりに
**ソースの縦線を揃える**。等幅フォントで表示しているので、揃えば表に見える。

要点は**日本語の幅**。等幅フォントでは全角が 2 桁ぶんを占めるため、
文字数で揃えると縦線がずれる。`display_width()` で表示幅を数える。
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum, auto

MIN_DELIMITER_WIDTH = 1

# 行頭の引用マーカーは表の一部ではないので、揃える前に外して後で戻す
_PREFIX_RE = re.compile(r"^(?:[ \t]*>[ \t]?)*[ \t]*")
# 区切り行は `-` を必ず含み、`|` `:` `-` と空白だけでできている
_DELIMITER_CELL_RE = re.compile(r"^:?-+:?$")


class Alignment(Enum):
    NONE = auto()
    LEFT = auto()
    RIGHT = auto()
    CENTER = auto()


@dataclass(frozen=True, slots=True)
class _Row:
    prefix: str
    cells: list[str]


# 全角として数える East Asian Width。`A`（Ambiguous）を入れているのが要点で、
# `→ ① ± § Ω` などは環境によって幅が変わるが、**日本語フォントでは全角**
# （表に使う BIZ UDGothic 15pt での実測は 5 つとも半角のちょうど 2 倍）。
# 半角として数えていたので、これらを含む行だけ桁がずれていた（実測 20px / C-1）
_WIDE_WIDTHS = "WFA"

# GFM でセルの中のリテラルなパイプを表す書き方
ESCAPED_PIPE = "\\|"


def display_width(text: str) -> int:
    """等幅フォントで占める桁数。全角は 2、半角は 1。

    **絵文字は揃わないことがある。** 🍎 の実測は半角の 2.30 倍で、
    空白（1 桁）を足し引きしても合わせようがない。

    `\\|`（エスケープしたパイプ）は 2 文字だが画面には 1 文字として出るので、
    1 桁として数える。
    """
    counted = text.replace(ESCAPED_PIPE, "|")
    return sum(2 if unicodedata.east_asian_width(char) in _WIDE_WIDTHS else 1 for char in counted)


def split_cells(body: str) -> list[str]:
    """行の中身をセルに割る。

    **`\\|` は区切りにしない。** GFM ではセルの中のリテラルなパイプを表す。
    見ずに割ると行が壊れ、整形が表全体をその列数に揃えてしまう
    （`docs/manual_test.md` が 3 列から 16 列に増えた。ユーザー報告）。
    """
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body) and body[index + 1] == "|":
            current.append(ESCAPED_PIPE)
            index += 2
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current))
    return cells


def _split_row(line: str) -> _Row:
    prefix = _PREFIX_RE.match(line).group(0)
    body = line[len(prefix) :].strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith(ESCAPED_PIPE):
        body = body[:-1]
    return _Row(prefix=prefix, cells=[cell.strip() for cell in split_cells(body)])


def _is_row(line: str) -> bool:
    body = _PREFIX_RE.sub("", line).strip()
    return body.startswith("|")


def _is_delimiter(line: str) -> bool:
    row = _split_row(line)
    return bool(row.cells) and all(_DELIMITER_CELL_RE.match(cell) for cell in row.cells)


def _alignment_of(cell: str) -> Alignment:
    left = cell.startswith(":")
    right = cell.endswith(":")
    if left and right:
        return Alignment.CENTER
    if right:
        return Alignment.RIGHT
    if left:
        return Alignment.LEFT
    return Alignment.NONE


def _pad(text: str, width: int, alignment: Alignment) -> str:
    space = max(0, width - display_width(text))
    match alignment:
        case Alignment.RIGHT:
            return " " * space + text
        case Alignment.CENTER:
            left = space // 2
            return " " * left + text + " " * (space - left)
        case _:
            return text + " " * space


def _delimiter_cell(width: int, alignment: Alignment) -> str:
    match alignment:
        case Alignment.LEFT:
            return ":" + "-" * max(MIN_DELIMITER_WIDTH, width - 1)
        case Alignment.RIGHT:
            return "-" * max(MIN_DELIMITER_WIDTH, width - 1) + ":"
        case Alignment.CENTER:
            return ":" + "-" * max(MIN_DELIMITER_WIDTH, width - 2) + ":"
        case _:
            return "-" * max(MIN_DELIMITER_WIDTH, width)


def format_table(lines: list[str]) -> list[str] | None:
    """表のソースを整形する。表でなければ None。

    列数が足りない行は空セルで埋め、多い行は捨てずに残す。
    **書いた内容を失わないほうを優先する。**
    """
    if len(lines) < 2:
        return None

    delimiter_index = next((i for i, line in enumerate(lines) if _is_delimiter(line)), None)
    if delimiter_index is None or delimiter_index == 0:
        return None

    rows = [_split_row(line) for line in lines]
    alignments = [_alignment_of(cell) for cell in rows[delimiter_index].cells]
    columns = max(len(row.cells) for row in rows)
    alignments += [Alignment.NONE] * (columns - len(alignments))

    widths = [MIN_DELIMITER_WIDTH] * columns
    for index, row in enumerate(rows):
        if index == delimiter_index:
            continue
        for column, cell in enumerate(row.cells):
            widths[column] = max(widths[column], display_width(cell))

    formatted: list[str] = []
    for index, row in enumerate(rows):
        if index == delimiter_index:
            cells = [_delimiter_cell(widths[c], alignments[c]) for c in range(columns)]
        else:
            padded = list(row.cells) + [""] * (columns - len(row.cells))
            cells = [_pad(padded[c], widths[c], alignments[c]) for c in range(columns)]
        formatted.append(f"{row.prefix}| " + " | ".join(cells) + " |")

    return formatted


def find_table(lines: list[str], line: int) -> tuple[int, int] | None:
    """`line` を含む表の範囲 `[開始, 終了)` を返す。表の中でなければ None。

    区切り行が無いものは表と見なさない。これが無いと、本文に `|` を含む
    ただの文（`価格は 100 | 税込`）まで表として扱ってしまう。
    """
    if not 0 <= line < len(lines) or not _is_row(lines[line]):
        return None

    start = line
    while start > 0 and _is_row(lines[start - 1]):
        start -= 1
    end = line + 1
    while end < len(lines) and _is_row(lines[end]):
        end += 1

    block = lines[start:end]
    if len(block) < 2 or not any(_is_delimiter(entry) for entry in block[1:]):
        return None
    return start, end
