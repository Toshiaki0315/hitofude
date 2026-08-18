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


def fits(text: str, columns: int) -> bool:
    """表の行が `columns` 桁（半角換算）に収まるか（ユーザー報告 / ADR-0003 追記）。

    収まらない行は画面で折り返し、**「ソースの 1 行 = 画面の 1 行」が崩れる**。
    崩れると `|` の x 座標が折り返し先の行の座標に戻るので、そこへ罫線を
    引いても意味を持たない。描けないときは描かず、記号を出して直せるようにする。

    `|` は隠れていて幅を持たないので数えない。`columns` が 0 以下のとき
    （幅がまだ分からないとき）は**収まる扱い**にする。起動直後に表が
    生の Markdown で出てしまうより、そのあと折り返して気づくほうがまし。
    """
    if columns <= 0:
        return True
    return display_width(text) - text.count("|") <= columns


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


# ------------------------------------------------------- セル折り返し（ADR-0017）
#
# 幅に収まらない表は、以前は生の Markdown へ落としていた。案 B では
# 表示側だけ折り返して描く（ソースは触らない = R1 無傷）。ここはその
# 「何をどこで折るか」の純ロジックで、描画は editor/ 側の仕事。

# 折り返しでもこれより狭くしない（全角 3 文字ぶん）。これを下回ると
# 1 行 1〜2 文字の縦書きのようになり、読めない
MIN_WRAP_COLUMN = 6

# 1 列あたりの飾りの取り分（縦線 1 + 左右の余白 2）。行末の縦線に +1
CELL_OVERHEAD = 3


def wrap_cell(text: str, width: int) -> list[str]:
    """セルの中身を表示幅 `width`（半角換算）で折り返す。

    空白があればそこで折る（英単語の途中で切らない）。1 語が幅を
    超えるときだけ字の途中で切る。全角は 2 桁で数える（ADR-0003）。
    """
    if width <= 0:
        return [text]
    lines: list[str] = []
    current = ""
    current_width = 0
    for word in _wrap_pieces(text):
        piece_width = display_width(word)
        if current and current_width + piece_width > width:
            lines.append(current.rstrip())
            current, current_width = "", 0
            if word == " ":
                continue  # 折り目の空白は行頭に持ち込まない
        if piece_width > width:
            # 1 語が幅より長い。字単位で詰める
            for char in word:
                char_width = display_width(char)
                if current and current_width + char_width > width:
                    lines.append(current.rstrip())
                    current, current_width = "", 0
                current += char
                current_width += char_width
            continue
        current += word
        current_width += piece_width
    lines.append(current.rstrip())
    return lines or [""]


def _wrap_pieces(text: str) -> list[str]:
    """折り返しの単位。空白を独立した piece にして折り目の候補にする。"""
    pieces: list[str] = []
    current = ""
    for char in text:
        if char == " ":
            if current:
                pieces.append(current)
                current = ""
            pieces.append(" ")
        else:
            current += char
    if current:
        pieces.append(current)
    return pieces


def wrapped_columns(rows: list[str], available: int) -> list[int]:
    """収まらない表の列幅（半角換算）を決める。

    自然幅（各列の最長セル。区切り行は書き手の癖なので数えない）が
    使える幅に収まればそのまま。溢れたら**いちばん広い列から** 1 ずつ
    削る。狭い列を道連れにしないため。`MIN_WRAP_COLUMN` より下には
    削らない（全列が最低幅でも収まらないなら、そこで止める）。
    """
    bodies = [_split_row(line).cells for line in rows if not _is_delimiter(line)]
    count = max((len(cells) for cells in bodies), default=0)
    if count == 0:
        return []

    widths = [
        max((display_width(cells[i]) for cells in bodies if i < len(cells)), default=0)
        for i in range(count)
    ]
    usable = available - (CELL_OVERHEAD * count + 1)
    while sum(widths) > usable:
        widest = max(range(count), key=lambda i: widths[i])
        if widths[widest] <= MIN_WRAP_COLUMN:
            break  # これ以上削ると読めない。溢れは描画側がはみ出しで吸収する
        widths[widest] -= 1
    return widths


def wrap_row(line: str, col_widths: list[int]) -> list[list[str]]:
    """1 行ぶんのセルを列幅で折り返す。列数が足りない分は空セル。"""
    cells = _split_row(line).cells
    return [
        wrap_cell(cells[i] if i < len(cells) else "", col_widths[i]) for i in range(len(col_widths))
    ]


@dataclass(frozen=True, slots=True)
class WrappedRow:
    """折り返した 1 行ぶんの表示内容（ADR-0017）。

    ハイライタが組み立てて `BlockData` に載せ、描画（paintEvent）が読む。
    ソースには一切触れない（R1）。
    """

    col_widths: tuple[int, ...]
    cells: tuple[tuple[str, ...], ...]

    @property
    def lines(self) -> int:
        """この行が使う見た目の行数 = いちばん高いセル。"""
        return max((len(cell) for cell in self.cells), default=1)
