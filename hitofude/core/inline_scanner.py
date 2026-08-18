"""1 行のインライン記法を文字オフセットで確定する（spec §6.5, ADR-0001）。

markdown-it-py のインライントークンは `map=None` で文字オフセットを持たないため、
`highlightBlock()` からは使えない（§3.4 / R8）。ここを自作するのは妥協ではなく必然。

**マスク方式**: 優先順の高い規則から順に走査し、確定した範囲をマスクする。
後続の規則はマスク済みの範囲に触れない。

マスクの粒度が設計の肝:

- コード・URL は**範囲全体**をマスクする。内側を一切解釈させないため
- 強調・取り消し線・ハイライトは**マーカーだけ**をマスクする。内容領域が空いて
  いるので、`**bold *em* here**` のような入れ子が追加の再帰なしに成立する

この関数は毎キー入力ごとに呼ばれる。正規表現はすべてモジュールレベルで
コンパイル済み（§6.6）。
"""

import re
import unicodedata

from hitofude.core.models import InlineSpan, SpanType
from hitofude.core.tags import TAG_RE, normalize

# --- 全体をマスクする規則 -------------------------------------------------

_CODE_RE = re.compile(r"(?P<ticks>`+)(?P<body>.+?)(?P=ticks)")
# URL はバランスした括弧を 1 段だけ許す（CommonMark と同じ）。
# Wikipedia 型（`…/Qt_(framework)`）を弾くと、リンクごと不成立になって
# `[` `]` が生の文字として残る
_URL_CHARS = r"(?:\([^()\s]*\)|[^()\s])*"
_IMAGE_RE = re.compile(rf"!\[(?P<text>[^\[\]]*)\]\((?P<url>{_URL_CHARS})\)")
# 行まるごとが画像 1 つのときだけ、本文中に絵として描く（タスク A-2）
_IMAGE_LINE_RE = re.compile(r"\A\s*!\[[^\[\]]*\]\((?P<url>(?:\([^()\s]*\)|[^()\s])+)\)\s*\Z")
_LINK_RE = re.compile(rf"(?<!!)\[(?P<text>[^\[\]]*)\]\((?P<url>{_URL_CHARS})\)")
# ノート間リンク `[[ノート名]]`（E-6）。**`|` を含むものは拾わない。**
# 別名（`[[名前|表示]]`）は未対応で、中途半端に拾うと名前が壊れる
_WIKI_LINK_RE = re.compile(r"\[\[(?P<name>[^\[\]|]+)\]\]")
# 脚注の参照 `[^1]` と定義の頭 `[^1]:`（B-3 / Qiita 記法）。
# `[1]` は拾わない。ただの角括弧と見分けが付かなくなる
_FOOTNOTE_RE = re.compile(r"\[\^(?P<label>[^\[\]\s]+)\]")
# インライン数式 `$...$`（B-5）。書き出し側（`core/html.py`）と同じ厳しさにする。
# **記号の内側に空白を許さず、前後に数字があるものも採らない。**
# 許すと `価格は $100 と $200 です。` が数式になる
# `$$...$$` を先に見る。あとにすると `$$a$$` が `$` + `$a$` に割れて範囲がずれる。
# 二重のほうは中の空白を許す（独立した式は `$$ x = 1 $$` とも書かれる）
_MATH_BLOCK_RE = re.compile(r"(?<!\$)\$\$(?P<body>[^$]+?)\$\$(?!\$)")
_MATH_RE = re.compile(r"(?<![\d$])\$(?P<body>[^\s$][^$]*?[^\s$]|[^\s$])\$(?![\d$])")
# かな・漢字を含むものは取り違え。数式に日本語は出てこない
_MATH_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿々〆、。]")
_AUTOLINK_RE = re.compile(r"<(?P<url>[A-Za-z][A-Za-z0-9+.\-]*:[^<>\s]+|[^@<>\s]+@[^@<>\s]+)>")
# 裸の URL もバランスした括弧 1 段を許す（GFM の自動リンクと同じ）。
# 単独の `)` は含めないので、`(https://…)` のように括弧で包んだ書き方は壊れない
_BARE_URL_RE = re.compile(r"(?<![\w/])(?P<url>https?://(?:\([^\s()]*\)|[^\s<>()\[\]\"'、。])+)")

# --- デリミタ対で表す規則 -------------------------------------------------
# spec §6.5 規則 4: 長いデリミタから先に確定する。
# `relaxed=True` は「前後が空白でなければよい」という緩めた条件（R4）。
# `_` だけは CommonMark の flanking 規則を厳密に適用し、snake_case を守る。
_DELIMITER_PASSES: tuple[tuple[str, int, SpanType, bool], ...] = (
    ("*", 3, SpanType.STRONG_EM, True),
    ("*", 2, SpanType.STRONG, True),
    ("*", 1, SpanType.EM, True),
    ("_", 3, SpanType.STRONG_EM, False),
    ("_", 2, SpanType.STRONG, False),
    ("_", 1, SpanType.EM, False),
    ("~", 2, SpanType.STRIKE, True),
    (":", 2, SpanType.HIGHLIGHT, True),
)


def _is_free(mask: bytearray, start: int, end: int) -> bool:
    return not any(mask[start:end])


def _mark(mask: bytearray, start: int, end: int) -> None:
    mask[start:end] = b"\x01" * (end - start)


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P") or unicodedata.category(char).startswith("S")


def _flanking(text: str, start: int, end: int) -> tuple[bool, bool]:
    """CommonMark の left-flanking / right-flanking を判定する。"""
    preceding = text[start - 1] if start > 0 else ""
    following = text[end] if end < len(text) else ""

    prev_space = not preceding or preceding.isspace()
    next_space = not following or following.isspace()
    prev_punct = bool(preceding) and _is_punctuation(preceding)
    next_punct = bool(following) and _is_punctuation(following)

    left = not next_space and (not next_punct or prev_space or prev_punct)
    right = not prev_space and (not prev_punct or next_space or next_punct)
    return left, right


def _can_open(text: str, start: int, end: int, *, relaxed: bool) -> bool:
    """このデリミタ列が開きマーカーになれるか。"""
    if relaxed:
        # 日本語は分かち書きしないため、CommonMark の句読点条件を外して
        # 「直後が空白でなければ開ける」に緩める（R4）。
        # `「**強調**」` や `**強調**。` を成立させるために必要。
        following = text[end] if end < len(text) else ""
        return bool(following) and not following.isspace()

    left, right = _flanking(text, start, end)
    preceding = text[start - 1] if start > 0 else ""
    # `_` は単語内では開きにならない。これが snake_case を守っている。
    return left and (not right or (bool(preceding) and _is_punctuation(preceding)))


def _can_close(text: str, start: int, end: int, *, relaxed: bool) -> bool:
    """このデリミタ列が閉じマーカーになれるか。"""
    if relaxed:
        preceding = text[start - 1] if start > 0 else ""
        return bool(preceding) and not preceding.isspace()

    left, right = _flanking(text, start, end)
    following = text[end] if end < len(text) else ""
    return right and (not left or (bool(following) and _is_punctuation(following)))


def _runs(text: str, char: str, length: int, mask: bytearray) -> list[tuple[int, int]]:
    """`char` がちょうど `length` 個連続し、まだマスクされていない区間。"""
    found: list[tuple[int, int]] = []
    index = 0
    size = len(text)
    while index < size:
        if text[index] != char:
            index += 1
            continue
        end = index
        while end < size and text[end] == char:
            end += 1
        if end - index == length and _is_free(mask, index, end):
            found.append((index, end))
        index = end
    return found


def _ascii_word_at(text: str, index: int) -> bool:
    """その位置が ASCII の単語文字（識別子の一部）か。範囲外は False。"""
    if not 0 <= index < len(text):
        return False
    char = text[index]
    return char.isascii() and (char.isalnum() or char == "_")


def _scan_delimited(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    for char, length, span_type, relaxed in _DELIMITER_PASSES:
        # `::` は ASCII の単語に食い込んでいるときはマーカーにしない。
        # `std::vector::size` の `::` は識別子の一部で、散文に書いただけで
        # ハイライトになっていた。日本語は ASCII 単語文字ではないので、
        # `これは::目立つ::です` には影響しない
        word_guard = char == ":"
        open_stack: list[tuple[int, int]] = []
        for start, end in _runs(text, char, length, mask):
            if word_guard and _ascii_word_at(text, start - 1) and _ascii_word_at(text, end):
                continue  # 両側とも単語の中。識別子の一部で確定
            if open_stack and _can_close(text, start, end, relaxed=relaxed):
                open_start, open_end = open_stack.pop()
                spans.append(
                    InlineSpan(
                        type=span_type,
                        open_start=open_start,
                        open_end=open_end,
                        close_start=start,
                        close_end=end,
                    )
                )
                # マーカーだけをマスクする。内容領域を空けておくことで
                # 入れ子（**bold *em* here**）が自然に成立する。
                _mark(mask, open_start, open_end)
                _mark(mask, start, end)
            elif _can_open(text, start, end, relaxed=relaxed):
                open_stack.append((start, end))


def _scan_code(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    for match in _CODE_RE.finditer(text):
        start, end = match.span()
        if not _is_free(mask, start, end):
            continue
        ticks = len(match.group("ticks"))
        spans.append(
            InlineSpan(
                type=SpanType.CODE,
                open_start=start,
                open_end=start + ticks,
                close_start=end - ticks,
                close_end=end,
            )
        )
        _mark(mask, start, end)


def _scan_links(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    """画像 → リンクの順（spec §6.5 規則 3）。`!` の有無で区別する。

    本文（`[...]`）はマーカーだけをマスクし、中の強調を生かす。
    URL（`(...)`）は全体をマスクする。URL 内の記号は装飾ではない。
    """
    for pattern, text_type in ((_IMAGE_RE, SpanType.IMAGE), (_LINK_RE, SpanType.LINK_TEXT)):
        for match in pattern.finditer(text):
            start, end = match.span()
            if not _is_free(mask, start, end):
                continue
            url = match.group("url")
            bracket_open = match.start("text") - 1
            bracket_close = match.end("text")
            paren_open = bracket_close + 1

            spans.append(
                InlineSpan(
                    type=text_type,
                    open_start=start,
                    open_end=match.start("text"),
                    close_start=bracket_close,
                    close_end=paren_open,
                    payload=url,
                )
            )
            spans.append(
                InlineSpan(
                    type=SpanType.LINK_URL,
                    open_start=paren_open,
                    open_end=match.start("url"),
                    close_start=match.end("url"),
                    close_end=end,
                    payload=url,
                )
            )
            _mark(mask, start, bracket_open + 1)  # '[' または '!['
            _mark(mask, bracket_close, end)  # '](url)'


def _scan_wiki_links(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    """`[[ノート名]]`（E-6）。

    **ふつうのリンクより先に見る。** `[[a]](b)` のような書き方をされたとき、
    あとに回すと `[a]` の部分がリンクとして先に確定して範囲がずれる。

    名前の中は**全部マスクする**。`[[a_b_c]]` の `_` は名前の一部であって
    強調ではない。装飾にすると飛び先が変わって見える。
    """
    for match in _WIKI_LINK_RE.finditer(text):
        start, end = match.span()
        if not _is_free(mask, start, end):
            continue
        name = match.group("name").strip()
        if not name:
            continue  # `[[   ]]` は名前が無い。ただの文字として残す
        spans.append(
            InlineSpan(
                type=SpanType.WIKI_LINK,
                open_start=start,
                open_end=start + 2,
                close_start=end - 2,
                close_end=end,
                payload=name,
            )
        )
        _mark(mask, start, end)


def _scan_autolinks(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    for match in _AUTOLINK_RE.finditer(text):
        start, end = match.span()
        if not _is_free(mask, start, end):
            continue
        spans.append(
            InlineSpan(
                type=SpanType.AUTOLINK,
                open_start=start,
                open_end=start + 1,
                close_start=end - 1,
                close_end=end,
                payload=match.group("url"),
            )
        )
        _mark(mask, start, end)

    for match in _BARE_URL_RE.finditer(text):
        start, end = match.span()
        if not _is_free(mask, start, end):
            continue
        # マーカーを持たない。全体が内容。
        spans.append(
            InlineSpan(
                type=SpanType.AUTOLINK,
                open_start=start,
                open_end=start,
                close_start=end,
                close_end=end,
                payload=match.group("url"),
            )
        )
        _mark(mask, start, end)


def _scan_math(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    for pattern, marker_len in ((_MATH_BLOCK_RE, 2), (_MATH_RE, 1)):
        for match in pattern.finditer(text):
            start, end = match.span()
            body = match.group("body")
            if _MATH_CJK_RE.search(body) or not _is_free(mask, start, end):
                continue
            spans.append(
                InlineSpan(
                    type=SpanType.MATH,
                    open_start=start,
                    open_end=start + marker_len,
                    close_start=end - marker_len,
                    close_end=end,
                    payload=body.strip(),
                )
            )
            _mark(mask, start, end)


def _scan_footnotes(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    for match in _FOOTNOTE_RE.finditer(text):
        start, end = match.span()
        if not _is_free(mask, start, end):
            continue
        spans.append(
            InlineSpan(
                type=SpanType.FOOTNOTE,
                open_start=start,
                open_end=start,
                close_start=end,
                close_end=end,
                payload=match.group("label"),
            )
        )
        _mark(mask, start, end)


def _scan_tags(text: str, mask: bytearray, spans: list[InlineSpan]) -> None:
    for match in TAG_RE.finditer(text):
        start, end = match.span()
        if not _is_free(mask, start, end):
            continue
        spans.append(
            InlineSpan(
                type=SpanType.TAG,
                open_start=start,
                open_end=start,
                close_start=end,
                close_end=end,
                payload=normalize(match.group("name")),
            )
        )
        _mark(mask, start, end)


def scan(text: str) -> list[InlineSpan]:
    """1 行を走査してインライン要素を返す。純関数。

    返り値は開始位置の昇順。同じ位置から始まる場合は**外側が先**になるので、
    ハイライタは順に `setFormat()` するだけで内側の書式が上書きされる。
    """
    mask = bytearray(len(text))
    spans: list[InlineSpan] = []

    # ADR-0001: リンクを裸の URL より先に確定する。
    # 逆順だと [text](url) の URL が先にマスクされ、リンクが成立しない。
    _scan_code(text, mask, spans)
    # **リンクより先に見る。** `[^1]` はリンクの形に噛まないが、順を後ろに
    # すると `[^1]: 注釈` の定義行で取り合いになる
    _scan_footnotes(text, mask, spans)
    _scan_math(text, mask, spans)
    # **ふつうのリンクより先。** `[[名前]]` の内側が `[名前]` として
    # 先に確定すると、範囲が 1 文字ずれる
    _scan_wiki_links(text, mask, spans)
    _scan_links(text, mask, spans)
    _scan_autolinks(text, mask, spans)
    _scan_delimited(text, mask, spans)
    _scan_tags(text, mask, spans)

    spans.sort(key=lambda span: (span.start, -span.end))
    return spans


def image_only_line(text: str) -> str | None:
    """行まるごとが画像 1 つならその URL を返す。違えば None。

    段落の途中にある画像は対象にしない。行の途中に高さを作るのは別の
    難しさで、実用上ほぼ「1 行 1 画像」のため。行頭マーカー（`- ` など）が
    付いている行も外す。記号自体が意味を持つので潰せない（§6.4）。
    """
    match = _IMAGE_LINE_RE.match(text)
    return match.group("url") if match else None
