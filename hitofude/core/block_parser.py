"""ソースを 1 行 1 個の `BlockInfo` に変換する（spec §3.4, §6.2）。

ブロック構造だけを markdown-it-py に任せる。ブロックトークンは
`token.map = [開始行, 終了行)` を持つので、行番号を確定できる（§3.4 / R8）。
インラインは `inline_scanner` の担当で、こちらは一切扱わない。

`highlightBlock()` は 1 行しか見えないため、リストの入れ子・表の範囲・
コードフェンスの範囲といった「行をまたぐ構造」はここでしか確定できない。
"""

import re
from dataclasses import replace

from markdown_it import MarkdownIt

from hitofude.core import frontmatter
from hitofude.core.models import BlockInfo, BlockType

_MD = MarkdownIt("commonmark").enable(["table", "strikethrough"])

_QUOTE_PREFIX_RE = re.compile(r"^(?:[ \t]*>[ \t]?)+")
_HEADING_MARKER_RE = re.compile(r"^[ \t]*#{1,6}[ \t]*")
_TASK_MARKER_RE = re.compile(r"^[ \t]*[-*+][ \t]+\[(?P<state>[ xX])\][ \t]+")
_BULLET_MARKER_RE = re.compile(r"^[ \t]*[-*+][ \t]+")
_ORDERED_MARKER_RE = re.compile(r"^[ \t]*\d{1,9}[.)][ \t]+")


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _front_matter_line_count(normalized: str) -> int:
    parsed = frontmatter.split(normalized)
    if not parsed.present:
        return 0
    return normalized[: parsed.body_offset].count("\n")


def parse(text: str) -> list[BlockInfo]:
    """ソース全体を解析し、**1 行につき 1 個**の `BlockInfo` を返す。

    返り値の長さは常に行数と一致する。`QTextBlock` と添字で対応させるため、
    ここがずれると装飾する行が 1 行ずれる。
    """
    normalized = _normalize(text)
    lines = normalized.split("\n")
    drafts: list[BlockInfo | None] = [None] * len(lines)
    quote_depths = [0] * len(lines)

    offset = _front_matter_line_count(normalized)
    for line in range(offset):
        drafts[line] = BlockInfo(line=line, type=BlockType.FRONT_MATTER)

    _apply_tokens(lines, offset, drafts, quote_depths)

    result: list[BlockInfo] = []
    for line, draft in enumerate(drafts):
        block = draft if draft is not None else _plain_block(line, lines[line])
        depth = quote_depths[line]
        if depth:
            block = _apply_quote(block, lines[line], depth)
        result.append(block)
    return result


def _plain_block(line: int, text: str) -> BlockInfo:
    kind = BlockType.BLANK if not text.strip() else BlockType.PARAGRAPH
    return BlockInfo(line=line, type=kind)


def _apply_quote(block: BlockInfo, text: str, depth: int) -> BlockInfo:
    """引用の深さを載せる。

    種別は**最も内側の構造**を保つ（`> - 項目` は箇条書き）。引用であることは
    `quote_depth` で表す。左の縦バー描画（§5.2）はこの値だけを見ればよい。
    """
    prefix = _QUOTE_PREFIX_RE.match(text)
    marker_len = prefix.end() if prefix else block.marker_len
    kind = BlockType.BLOCKQUOTE if block.type is BlockType.PARAGRAPH else block.type
    return replace(block, type=kind, quote_depth=depth, marker_len=marker_len)


def _apply_tokens(
    lines: list[str],
    offset: int,
    drafts: list[BlockInfo | None],
    quote_depths: list[int],
) -> None:
    """トークンを走査し、優先度の低い順に書き込む（後の代入が勝つ）。

    リスト項目の行は `paragraph_open` の範囲にも含まれるため、
    段落を先に、リストを後に適用する必要がある。
    """
    tokens = _MD.parse("\n".join(lines[offset:]))

    paragraphs: list[tuple[int, int]] = []
    tables: list[tuple[int, int]] = []
    delimiters: list[int] = []
    items: list[tuple[int, int, bool]] = []
    headings: list[tuple[int, int]] = []
    rules: list[int] = []
    fences: list[tuple[int, int, str, str]] = []

    quote_depth = 0
    list_depth = 0
    ordered = False

    for token in tokens:
        span = (token.map[0] + offset, token.map[1] + offset) if token.map is not None else (0, 0)
        match token.type:
            case "blockquote_open":
                quote_depth += 1
                for line in range(*span):
                    quote_depths[line] = max(quote_depths[line], quote_depth)
            case "blockquote_close":
                quote_depth -= 1
            case "bullet_list_open" | "ordered_list_open":
                list_depth += 1
                ordered = token.type == "ordered_list_open"
            case "bullet_list_close" | "ordered_list_close":
                list_depth -= 1
            case "list_item_open":
                items.append((span[0], list_depth, ordered))
            case "paragraph_open":
                paragraphs.append(span)
            case "heading_open":
                headings.append((span[0], int(token.tag[1:])))
            case "hr":
                rules.append(span[0])
            case "table_open":
                tables.append(span)
            case "thead_open":
                # 区切り行 `|---|` はトークンにならない。ヘッダの直後にある。
                delimiters.append(span[1])
            case "fence":
                fences.append((span[0], span[1], token.info.strip(), token.markup))
            case "code_block":
                # 4 スペースのインデントコード。フェンスは無いが中身はコード。
                for line in range(*span):
                    drafts[line] = BlockInfo(line=line, type=BlockType.CODE_FENCE_BODY)

    for start, end in paragraphs:
        for line in range(start, end):
            drafts[line] = BlockInfo(line=line, type=BlockType.PARAGRAPH)

    for start, end in tables:
        for line in range(start, end):
            drafts[line] = BlockInfo(line=line, type=BlockType.TABLE_ROW)
    for line in delimiters:
        drafts[line] = BlockInfo(line=line, type=BlockType.TABLE_DELIMITER)

    for line, level, is_ordered in items:
        drafts[line] = _list_block(line, lines[line], level, is_ordered=is_ordered)

    for line, level in headings:
        marker = _HEADING_MARKER_RE.match(_strip_quote(lines[line]))
        drafts[line] = BlockInfo(
            line=line,
            type=BlockType.HEADING,
            level=level,
            marker_len=marker.end() if marker else 0,
        )

    for line in rules:
        drafts[line] = BlockInfo(line=line, type=BlockType.HORIZONTAL_RULE)

    for start, end, info, markup in fences:
        _apply_fence(lines, drafts, start, end, info, markup)


def _strip_quote(text: str) -> str:
    prefix = _QUOTE_PREFIX_RE.match(text)
    return text[prefix.end() :] if prefix else text


def _list_block(line: int, text: str, level: int, *, is_ordered: bool) -> BlockInfo:
    body = _strip_quote(text)
    quote_len = len(text) - len(body)

    task = _TASK_MARKER_RE.match(body)
    if task is not None:
        return BlockInfo(
            line=line,
            type=BlockType.TASK_LIST_ITEM,
            level=level,
            marker_len=quote_len + task.end(),
            checked=task.group("state").lower() == "x",
        )

    pattern = _ORDERED_MARKER_RE if is_ordered else _BULLET_MARKER_RE
    marker = pattern.match(body)
    kind = BlockType.ORDERED_LIST_ITEM if is_ordered else BlockType.BULLET_LIST_ITEM
    return BlockInfo(
        line=line,
        type=kind,
        level=level,
        marker_len=quote_len + (marker.end() if marker else 0),
    )


def _apply_fence(
    lines: list[str],
    drafts: list[BlockInfo | None],
    start: int,
    end: int,
    info: str,
    markup: str,
) -> None:
    """コードフェンスを開始 / 中身 / 終了の 3 種に割り当てる。

    閉じフェンスの有無で最終行の扱いが変わる。入力途中は必ず未閉じになるので、
    ここで落ちると打っている最中に装飾が壊れる。
    """
    lang = info.split()[0] if info else None
    drafts[start] = BlockInfo(line=start, type=BlockType.CODE_FENCE_OPEN, lang=lang)

    last = end - 1
    closed = last > start and lines[last].strip().startswith(markup[0] * 3)
    body_end = last if closed else end

    for line in range(start + 1, body_end):
        drafts[line] = BlockInfo(line=line, type=BlockType.CODE_FENCE_BODY)
    if closed:
        drafts[last] = BlockInfo(line=last, type=BlockType.CODE_FENCE_CLOSE)
