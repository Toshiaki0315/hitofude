"""ソースを 1 行 1 個の `BlockInfo` に変換する（spec §3.4, §6.2）。

ブロック構造だけを markdown-it-py に任せる。ブロックトークンは
`token.map = [開始行, 終了行)` を持つので、行番号を確定できる（§3.4 / R8）。
インラインは `inline_scanner` の担当で、こちらは一切扱わない。

`highlightBlock()` は 1 行しか見えないため、リストの入れ子・表の範囲・
コードフェンスの範囲といった「行をまたぐ構造」はここでしか確定できない。
"""

import re
from dataclasses import dataclass, field, replace

from markdown_it import MarkdownIt

from hitofude.core import frontmatter
from hitofude.core.models import (
    DEFAULT_NOTE_KIND,
    NOTE_KINDS,
    UNKNOWN_NOTE_KIND,
    BlockInfo,
    BlockState,
    BlockType,
)

_MD = MarkdownIt("commonmark").enable(["table", "strikethrough"])

_QUOTE_PREFIX_RE = re.compile(r"^(?:[ \t]*>[ \t]?)+")
INDENTED_CODE_WIDTH = 4
_LIST_TYPES = frozenset(
    {BlockType.BULLET_LIST_ITEM, BlockType.ORDERED_LIST_ITEM, BlockType.TASK_LIST_ITEM}
)
_HEADING_MARKER_RE = re.compile(r"^[ \t]*#{1,6}[ \t]*")
_TASK_MARKER_RE = re.compile(r"^[ \t]*[-*+][ \t]+\[(?P<state>[ xX])\][ \t]+")
_BULLET_MARKER_RE = re.compile(r"^[ \t]*[-*+][ \t]+")
_ORDERED_MARKER_RE = re.compile(r"^[ \t]*\d{1,9}[.)][ \t]+")

# --- 行単位分類（§6.3）で使う ---------------------------------------------
# 見出しは `#` の後ろが空白か行末でなければならない（CommonMark）。
# これを見ないと `####### x` が見出しレベル 6 になり、`#tag` も見出しになる。
_HEADING_LINE_RE = re.compile(r"^[ \t]*(?P<hashes>#{1,6})(?:[ \t]+|$)")
_FENCE_LINE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_FRONT_MATTER_DELIM_RE = re.compile(r"^---[ \t]*$")
# `:::note info`（B-3 / Qiita 記法）。行頭から始まるものだけを見る。
# `> :::note` は引用の本文であって囲みではない
_NOTE_OPEN_RE = re.compile(r"^:::[ \t]*note(?:[ \t]+(?P<kind>\S+))?[ \t]*$")
_NOTE_CLOSE_RE = re.compile(r"^:::[ \t]*$")
# 複数行の数式（B-5）。`$$` だけの行。1 行に書いた `$$x$$` は行内の数式で、
# `inline_scanner` が拾う
_MATH_FENCE_RE = re.compile(r"^\$\$[ \t]*$")
_RULE_LINE_RE = re.compile(r"^ {0,3}(?P<char>[-*_])(?:[ \t]*(?P=char)){2,}[ \t]*$")
# 表の区切り行は `|` を必ず含み、`-` を必ず含み、それ以外は揃え指定と空白だけ。
_TABLE_DELIM_LINE_RE = re.compile(r"^(?=[^\n]*\|)(?=[^\n]*-)[ \t|:\-]+$")

# リストの入れ子はインデント 2 文字を 1 段と見なす（あくまで目安）。
_INDENT_PER_LEVEL = 2


def _fence_info(info: str) -> tuple[str | None, str | None]:
    """フェンスの情報文字列を「言語」と「ファイル名」に分ける（B-3 / Qiita 記法）。

    `` ```python:aaa.py `` → `("python", "aaa.py")`、`` ```:メモ `` → `(None, "メモ")`。
    **言語に `python:aaa.py` を入れない。** 色分けの仕組みが言語を
    見つけられなくなる（`core/html.py` の描画規則と同じ理由）。
    """
    head = info.split()[0] if info else ""
    if not head:
        return None, None
    lang, separator, name = head.partition(":")
    return (lang or None), (name or None if separator else None)


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
    kind = _quoted_type(block.type)
    return replace(block, type=kind, quote_depth=depth, marker_len=marker_len)


def _quoted_type(kind: BlockType) -> BlockType:
    """引用の中身の種別。

    `> ` だけの行は中身が空でも**引用行**であって空行ではない。BLANK のままだと
    Enter を押したときの引用解除（§5.5-6）が発火しない。
    """
    return BlockType.BLOCKQUOTE if kind in (BlockType.PARAGRAPH, BlockType.BLANK) else kind


@dataclass(slots=True)
class _Collected:
    """トークン走査で拾った、行と種別の対応。

    走査と書き込みを分けるのは**書き込む順序に意味がある**ため。
    リスト項目の行は `paragraph_open` の範囲にも含まれるので、段落を先に、
    リストを後に書く必要がある（後の代入が勝つ）。走査しながら書くと
    この順序を保てない。
    """

    indented_code: list[tuple[int, int]] = field(default_factory=list)
    paragraphs: list[tuple[int, int]] = field(default_factory=list)
    tables: list[tuple[int, int]] = field(default_factory=list)
    delimiters: list[int] = field(default_factory=list)
    items: list[tuple[int, int, bool]] = field(default_factory=list)
    headings: list[tuple[int, int]] = field(default_factory=list)
    rules: list[int] = field(default_factory=list)
    fences: list[tuple[int, int, str, str]] = field(default_factory=list)


def _collect(tokens, offset: int, quote_depths: list[int]) -> _Collected:
    """トークンを種別ごとに仕分ける。引用の深さだけはここで確定する。"""
    found = _Collected()
    quote_depth = 0
    # True = 番号付き。**スタックで持つ。** 単一のブールだと、入れ子の
    # 番号リストを閉じたあとも True のままになり、外側の箇条書きの
    # 後続項目が番号付き扱いになる
    list_stack: list[bool] = []

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
                list_stack.append(token.type == "ordered_list_open")
            case "bullet_list_close" | "ordered_list_close":
                if list_stack:
                    list_stack.pop()
            case "list_item_open":
                ordered = bool(list_stack) and list_stack[-1]
                found.items.append((span[0], len(list_stack), ordered))
            case "paragraph_open":
                found.paragraphs.append(span)
            case "heading_open":
                found.headings.append((span[0], int(token.tag[1:])))
            case "hr":
                found.rules.append(span[0])
            case "table_open":
                found.tables.append(span)
            case "thead_open":
                # 区切り行 `|---|` はトークンにならない。ヘッダの直後にある。
                found.delimiters.append(span[1])
            case "fence":
                found.fences.append((span[0], span[1], token.info.strip(), token.markup))
            case "code_block":
                # 4 スペースのインデントコード。フェンスは無いが中身はコード。
                found.indented_code.append(span)

    return found


def _write(found: _Collected, lines: list[str], drafts: list[BlockInfo | None]) -> None:
    """拾ったものを**優先度の低い順に**書き込む。後の代入が勝つ。"""
    for start, end in found.indented_code:
        for line in range(start, end):
            drafts[line] = BlockInfo(line=line, type=BlockType.CODE_FENCE_BODY)

    for start, end in found.paragraphs:
        for line in range(start, end):
            drafts[line] = BlockInfo(line=line, type=BlockType.PARAGRAPH)

    for start, end in found.tables:
        for line in range(start, end):
            drafts[line] = BlockInfo(line=line, type=BlockType.TABLE_ROW)
    for line in found.delimiters:
        drafts[line] = BlockInfo(line=line, type=BlockType.TABLE_DELIMITER)

    for line, level, is_ordered in found.items:
        drafts[line] = _list_block(line, lines[line], level, is_ordered=is_ordered)

    for line, level in found.headings:
        marker = _HEADING_MARKER_RE.match(_strip_quote(lines[line]))
        drafts[line] = BlockInfo(
            line=line,
            type=BlockType.HEADING,
            level=level,
            marker_len=marker.end() if marker else 0,
        )

    for line in found.rules:
        drafts[line] = BlockInfo(line=line, type=BlockType.HORIZONTAL_RULE)

    for start, end, info, markup in found.fences:
        _apply_fence(lines, drafts, start, end, info, markup)


def _apply_tokens(
    lines: list[str],
    offset: int,
    drafts: list[BlockInfo | None],
    quote_depths: list[int],
) -> None:
    """markdown-it の結果を行ごとの種別へ落とす（§3.4, R8）。"""
    tokens = _MD.parse("\n".join(lines[offset:]))
    _write(_collect(tokens, offset, quote_depths), lines, drafts)


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
    lang, name = _fence_info(info)
    drafts[start] = BlockInfo(line=start, type=BlockType.CODE_FENCE_OPEN, lang=lang, code_name=name)

    last = end - 1
    # CommonMark: 閉じは開きと同じ記号・同じ長さ以上の run だけの行。
    # `startswith("```")` だと `````` を ``` で閉じたことにしてしまい、
    # classify_line 側の判定（fence_len を比べる）と食い違う
    closing = lines[last].strip()
    closed = last > start and len(closing) >= len(markup) and set(closing) == {markup[0]}
    body_end = last if closed else end

    for line in range(start + 1, body_end):
        drafts[line] = BlockInfo(line=line, type=BlockType.CODE_FENCE_BODY)
    if closed:
        drafts[last] = BlockInfo(line=last, type=BlockType.CODE_FENCE_CLOSE)


# --------------------------------------------------------------------------
# 行単位分類（spec §6.3）
#
# `highlightBlock()` は 1 行しか見えず、前の行から引き継げるのは int 1 個だけ。
# そのため文書全体を見る `parse()` とは別に、行 + 引き継ぎ状態だけで判定する
# 経路が要る。両者は単純な文書では一致する（回帰テストで担保）。
#
# 行をまたぐ構造（リストの正確な入れ子、表のヘッダ行）はここでは確定できない。
# デバウンスした `parse()` の結果で補正する前提（§6.6 / R9）。
# --------------------------------------------------------------------------


def classify_line(text: str, line: int, state: BlockState) -> tuple[BlockInfo, BlockState]:
    """1 行を、前の行から引き継いだ状態とあわせて分類する。

    戻り値は `(この行の BlockInfo, 次の行へ渡す状態)`。
    """
    if state.in_front_matter or (line == 0 and _FRONT_MATTER_DELIM_RE.match(text)):
        return _classify_front_matter(text, line, state)

    if state.in_code:
        return _in_note(_classify_inside_fence(text, line, state), state.note_kind)

    if state.in_math:
        if _MATH_FENCE_RE.match(text):
            block = BlockInfo(line=line, type=BlockType.MATH_DELIMITER)
            return _in_note((block, BlockState(note_kind=state.note_kind)), state.note_kind)
        block = BlockInfo(line=line, type=BlockType.MATH_BODY)
        return _in_note((block, state), state.note_kind)

    if _MATH_FENCE_RE.match(text):
        block = BlockInfo(line=line, type=BlockType.MATH_DELIMITER)
        opened = BlockState(in_math=True, note_kind=state.note_kind)
        return _in_note((block, opened), state.note_kind)

    note = _classify_note_delimiter(text, line, state)
    if note is not None:
        return note

    fence = _FENCE_LINE_RE.match(text)
    if fence is not None:
        info = fence.group("info").strip()
        marker = fence.group("fence")
        lang, name = _fence_info(info)
        block = BlockInfo(
            line=line,
            type=BlockType.CODE_FENCE_OPEN,
            lang=lang,
            code_name=name,
        )
        return _in_note(
            (
                block,
                BlockState(
                    in_code=True, fence_char=marker[0], fence_len=len(marker), quote_depth=0
                ),
            ),
            state.note_kind,
        )

    return _in_note(_classify_body(text, line, state=state), state.note_kind)


def _classify_note_delimiter(
    text: str, line: int, state: BlockState
) -> tuple[BlockInfo, BlockState] | None:
    """`:::note info` と閉じの `:::`（B-3 / Qiita 記法）。囲みの行でなければ None。"""
    if state.in_note and _NOTE_CLOSE_RE.match(text):
        block = BlockInfo(line=line, type=BlockType.NOTE_DELIMITER, note_kind=state.note_kind)
        return block, BlockState()

    opened = None if state.in_note else _NOTE_OPEN_RE.match(text)
    if opened is None:
        return None

    kind = opened.group("kind") or DEFAULT_NOTE_KIND
    if kind not in NOTE_KINDS:
        # 綴り違い。囲みにはするが**別扱いにして見て分かるようにする**
        # （`info` に寄せると青い線が出るだけで気づけない。ユーザー報告）
        kind = UNKNOWN_NOTE_KIND
    block = BlockInfo(line=line, type=BlockType.NOTE_DELIMITER, note_kind=kind)
    return block, BlockState(note_kind=kind)


def _in_note(classified: tuple[BlockInfo, BlockState], kind: str) -> tuple[BlockInfo, BlockState]:
    """囲みの中であることを、行の情報と次の行へ渡す状態の両方に足す。

    **他の分類はそのまま通す。** 囲みの中でも見出しは見出し、コードはコード。
    ここで型を塗り替えると、囲みを使った瞬間に中の装飾が全部死ぬ。

    フェンスや front matter の分岐は状態を作り直すので、通り道すべてで
    足し直さないと囲みが途中で切れる（実際にテストで落ちた）。
    """
    if not kind:
        return classified
    info, state = classified
    return replace(info, note_kind=kind), replace(state, note_kind=kind)


def _classify_front_matter(text: str, line: int, state: BlockState) -> tuple[BlockInfo, BlockState]:
    block = BlockInfo(line=line, type=BlockType.FRONT_MATTER)
    if state.in_front_matter and _FRONT_MATTER_DELIM_RE.match(text):
        return block, BlockState()  # 閉じ区切り
    return block, BlockState(in_front_matter=True)


def _classify_inside_fence(text: str, line: int, state: BlockState) -> tuple[BlockInfo, BlockState]:
    fence = _FENCE_LINE_RE.match(text)
    closes = (
        fence is not None
        and fence.group("fence")[0] == state.fence_char
        and len(fence.group("fence")) >= state.fence_len
        and not fence.group("info").strip()  # 閉じフェンスに情報文字列は付けられない
    )
    if closes:
        return BlockInfo(line=line, type=BlockType.CODE_FENCE_CLOSE), BlockState()
    return BlockInfo(line=line, type=BlockType.CODE_FENCE_BODY), state


def _classify_body(
    text: str, line: int, *, state: BlockState | None = None
) -> tuple[BlockInfo, BlockState]:
    context = state or BlockState()
    quote = _QUOTE_PREFIX_RE.match(text)
    quote_len = quote.end() if quote else 0
    quote_depth = text.count(">", 0, quote_len) if quote else 0
    body = text[quote_len:]
    blank = not body.strip()

    if _is_indented_code(body, context, blank=blank):
        block = BlockInfo(line=line, type=BlockType.CODE_FENCE_BODY)
        if quote_depth:
            block = replace(block, quote_depth=quote_depth, marker_len=quote_len)
        return block, replace(
            context,
            quote_depth=quote_depth,
            in_table=False,
            after_blank=False,
            in_indented_code=True,
        )

    block = _classify_leaf(body, line, quote_len, in_table=context.in_table)
    in_table = block.type in (BlockType.TABLE_DELIMITER, BlockType.TABLE_ROW)

    if quote_depth:
        kind = _quoted_type(block.type)
        marker_len = quote_len if kind is BlockType.BLOCKQUOTE else block.marker_len
        block = replace(block, type=kind, quote_depth=quote_depth, marker_len=marker_len)

    return block, BlockState(
        quote_depth=quote_depth,
        in_table=in_table,
        after_blank=blank,
        in_list=_next_in_list(block.type, context, blank=blank),
        # 空行はコードを終わらせない。次の字下げ行で続きになる（CommonMark）
        in_indented_code=context.in_indented_code and blank,
    )


def _is_indented_code(body: str, state: BlockState, *, blank: bool) -> bool:
    """その行がインデントコードか。

    **行だけを見て決めるには文脈が要る。** 4 スペース下がっていても、
    段落の続き（前の行が空行でない）なら段落だし、リストの中なら入れ子の
    項目になる（§6.4）。`parse()` は markdown-it が文書全体を見て決めるが、
    ハイライタは 1 行ずつしか見られないので、`BlockState` に持たせている。
    """
    if blank or state.in_list:
        return False
    if _indent_width(body) < INDENTED_CODE_WIDTH:
        return False
    return state.in_indented_code or state.after_blank


def _indent_width(body: str) -> int:
    """タブを 4 桁として数えた字下げ幅。"""
    width = 0
    for char in body:
        if char == " ":
            width += 1
        elif char == "\t":
            width += INDENTED_CODE_WIDTH
        else:
            break
    return width


def _next_in_list(kind: BlockType, state: BlockState, *, blank: bool) -> bool:
    """次の行がリストの中にいるか。

    リストは空行を挟んでも続きうるので、空行では判断を変えない。
    字下げのない別のブロックが来たところで終わる。
    """
    if kind in _LIST_TYPES:
        return True
    if blank:
        return state.in_list
    return False


def _classify_leaf(body: str, line: int, quote_len: int, *, in_table: bool = False) -> BlockInfo:
    if not body.strip():
        return BlockInfo(line=line, type=BlockType.BLANK)

    heading = _HEADING_LINE_RE.match(body)
    if heading is not None:
        return BlockInfo(
            line=line,
            type=BlockType.HEADING,
            level=len(heading.group("hashes")),
            marker_len=quote_len + heading.end(),
        )

    if _RULE_LINE_RE.match(body):
        return BlockInfo(line=line, type=BlockType.HORIZONTAL_RULE)

    if _TABLE_DELIM_LINE_RE.match(body):
        return BlockInfo(line=line, type=BlockType.TABLE_DELIMITER)

    task = _TASK_MARKER_RE.match(body)
    if task is not None:
        return BlockInfo(
            line=line,
            type=BlockType.TASK_LIST_ITEM,
            level=_indent_level(body),
            marker_len=quote_len + task.end(),
            checked=task.group("state").lower() == "x",
        )

    for pattern, kind in (
        (_BULLET_MARKER_RE, BlockType.BULLET_LIST_ITEM),
        (_ORDERED_MARKER_RE, BlockType.ORDERED_LIST_ITEM),
    ):
        marker = pattern.match(body)
        if marker is not None:
            return BlockInfo(
                line=line,
                type=kind,
                level=_indent_level(body),
                marker_len=quote_len + marker.end(),
            )

    # `|` を含むだけでは表にしない。`価格は 100 | 税込` のような普通の文が
    # 等幅フォントになってしまう。行頭が `|` か、区切り行の後ろにいることを要求する
    if body.lstrip().startswith("|") or (in_table and "|" in body):
        return BlockInfo(line=line, type=BlockType.TABLE_ROW)

    return BlockInfo(line=line, type=BlockType.PARAGRAPH)


def _indent_level(body: str) -> int:
    """インデント幅から入れ子の深さを見積もる。

    正確な深さは親のマーカー幅に依存するため、行単位では決まらない。
    表示上のぶら下げインデントに使う目安で、確定値は `parse()` が出す。
    """
    indent = len(body) - len(body.lstrip(" \t"))
    return indent // _INDENT_PER_LEVEL + 1
