"""Markdown のライブプレビュー用ハイライタ（spec §6.3, §6.4）。

**マーカーは削除も置換もしない。** `setFontPointSize(0.5)` で潰すだけ（R4）。
文字が実在し続けるので `QTextCursor` の位置とソース文字列のオフセットが
常に 1:1 で一致し、位置マッピングのテーブルが一切要らない。これが本方式の
最大の利点なので、ここを崩す変更をしてはいけない。

`highlightBlock()` は変更のあったブロックにだけ Qt が自動で呼ぶ。
全体再ハイライトはテーマ変更時と起動時に限る（R7）。
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextBlockUserData,
    QTextCharFormat,
    QTextDocument,
)

from hitofude.core.block_parser import classify_line
from hitofude.core.inline_scanner import scan
from hitofude.core.models import BlockInfo, BlockState, BlockType, InlineSpan, SpanType
from hitofude.theme import LIGHT, ThemeColors

# 0.5pt にすると 1 文字あたり残る幅は約 0.5px（spec §3.3 の実測）。
# 0 は Qt が「未指定」と解釈するため使えない。
HIDDEN_POINT_SIZE = 0.5

DEFAULT_MONO_FAMILY = "Menlo"

# `SF Mono` は spec §5.2 の指定だが、macOS はアプリに公開していないため
# 指定しても解決されない（Qt が "missing font family" を警告する）。
# 実在するものへ順に落とす。指定フォントが無い環境でも行の高さが暴れない
MONO_FALLBACKS = ["Menlo", "Monaco", "Courier New"]


def mono_families(preferred: str) -> list[str]:
    """指定フォントに実在するフォールバックを足した並び。"""
    return [preferred, *(name for name in MONO_FALLBACKS if name != preferred)]


# spec §5.2 の見出しサイズ（本文サイズに対する倍率）
HEADING_SCALE = {1: 1.8, 2: 1.5, 3: 1.25, 4: 1.1, 5: 1.0, 6: 0.95}

# 装飾を一切適用しないブロック（§6.4「コードブロックの中では装飾が効かない」）
_CODE_BLOCK_TYPES = frozenset(
    {BlockType.CODE_FENCE_BODY, BlockType.CODE_FENCE_OPEN, BlockType.CODE_FENCE_CLOSE}
)

# 行全体を潰すブロック。記号ではなく描画（背景・線）で表現する（§5.2）
_FULLY_HIDDEN_TYPES = frozenset(
    {
        BlockType.CODE_FENCE_OPEN,
        BlockType.CODE_FENCE_CLOSE,
        BlockType.HORIZONTAL_RULE,
        BlockType.FRONT_MATTER,
    }
)

# 行頭マーカーを潰すブロック。リストは「記号自体が意味を持つ」ので含めない（§6.4）
_HIDDEN_MARKER_TYPES = frozenset({BlockType.HEADING, BlockType.BLOCKQUOTE})

_MONO_TYPES = frozenset({BlockType.TABLE_ROW, BlockType.TABLE_DELIMITER})


class BlockData(QTextBlockUserData):
    """`QTextBlock` にぶら下げる解析結果（spec §6.2）。

    `paintEvent()`（縦バーやチェックボックスの描画）と `block_decorator`
    （余白・インデント）はここから読む。Qt での標準的なやり方。
    """

    def __init__(self, info: BlockInfo, spans: list[InlineSpan]) -> None:
        super().__init__()
        self.info = info
        self.spans = spans


@dataclass(frozen=True, slots=True)
class _Reveal:
    """このブロックで何を現すかの判定結果。"""

    everything: bool
    caret_column: int | None

    def span(self, span: InlineSpan) -> bool:
        if self.everything:
            return True
        return self.caret_column is not None and span.contains(self.caret_column)

    @property
    def block_marker(self) -> bool:
        """ブロックマーカーはブロック内にキャレットがあれば現す（§6.4）。"""
        return self.everything or self.caret_column is not None


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(
        self,
        document: QTextDocument,
        theme: ThemeColors = LIGHT,
        *,
        base_point_size: float = 15.0,
        mono_family: str = DEFAULT_MONO_FAMILY,
    ) -> None:
        super().__init__(document)
        self._theme = theme
        self._base_point_size = base_point_size
        self._mono_family = mono_family
        self._reveal_position: int | None = None
        self._selection: tuple[int, int] | None = None
        self._source_mode = False
        self._build_formats()

    # ------------------------------------------------------------------ 設定

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._build_formats()
        self.rehighlight()  # テーマ変更は全体再ハイライトが許される数少ない場面（R7）

    def set_mono_family(self, family: str) -> None:
        """コード・表に使う等幅フォント（spec §5.2）。"""
        if family == self._mono_family:
            return
        self._mono_family = family
        self._build_formats()
        self.rehighlight()

    def set_base_point_size(self, size: float) -> None:
        self._base_point_size = size
        self._build_formats()
        self.rehighlight()

    def set_reveal(self, position: int | None, selection: tuple[int, int] | None = None) -> None:
        """キャレット位置と選択範囲を伝える。

        **ここでは再ハイライトしない。** 呼び出し側が旧/新の 2 ブロックだけを
        `rehighlightBlock()` する（R7）。全体を掛け直すと G5 が壊れる。
        """
        self._reveal_position = position
        self._selection = selection

    def set_source_mode(self, enabled: bool) -> None:
        """`Cmd+/`。全マーカーを表示する（§6.4）。"""
        self._source_mode = enabled

    @property
    def source_mode(self) -> bool:
        return self._source_mode

    # ------------------------------------------------------------- ハイライト

    def highlightBlock(self, text: str) -> None:
        block = self.currentBlock()
        state = BlockState.decode(self.previousBlockState())
        info, next_state = classify_line(text, block.blockNumber(), state)

        in_code = info.type in _CODE_BLOCK_TYPES
        spans = [] if in_code else scan(text)
        reveal = self._reveal_for(block.position(), block.length())

        self._apply_block_format(text, info)
        if not in_code:
            self._apply_spans(text, spans, reveal)
        self._hide_block_markers(text, info, reveal)

        self.setCurrentBlockUserData(BlockData(info, spans))
        self.setCurrentBlockState(next_state.encode())

    def _reveal_for(self, block_start: int, block_length: int) -> _Reveal:
        if self._source_mode:
            return _Reveal(everything=True, caret_column=None)

        # `length()` は改行を含むので、末尾にキャレットを置いた状態も内側に入る
        block_end = block_start + block_length - 1

        if self._selection is not None:
            start, end = self._selection
            if not (end < block_start or start > block_end):
                return _Reveal(everything=True, caret_column=None)
            return _Reveal(everything=False, caret_column=None)

        if self._reveal_position is not None and block_start <= self._reveal_position <= block_end:
            return _Reveal(everything=False, caret_column=self._reveal_position - block_start)
        return _Reveal(everything=False, caret_column=None)

    # ----------------------------------------------------------- 書式の適用

    def _apply_block_format(self, text: str, info: BlockInfo) -> None:
        if not text:
            return
        match info.type:
            case BlockType.HEADING:
                self.setFormat(0, len(text), self._heading[info.level])
            case BlockType.CODE_FENCE_BODY | BlockType.CODE_FENCE_OPEN | BlockType.CODE_FENCE_CLOSE:
                self.setFormat(0, len(text), self._code_block)
            case BlockType.BLOCKQUOTE:
                self.setFormat(0, len(text), self._quote)
            case _ if info.type in _MONO_TYPES:
                self.setFormat(0, len(text), self._mono)
            case _:
                pass

    def _apply_spans(self, text: str, spans: list[InlineSpan], reveal: _Reveal) -> None:
        for span in spans:
            content = self._span_formats.get(span.type)
            if content is not None and span.content_end > span.content_start:
                self._merge(span.content_start, span.content_end - span.content_start, content)
            if reveal.span(span):
                continue
            if span.type is SpanType.LINK_URL:
                # URL は記号だけでなく中身ごと隠す（§6.4）
                self._hide(span.start, span.end - span.start)
                continue
            self._hide(span.open_start, span.open_len)
            self._hide(span.close_start, span.close_len)

    def _hide_block_markers(self, text: str, info: BlockInfo, reveal: _Reveal) -> None:
        if reveal.block_marker or not text:
            return
        if info.type in _FULLY_HIDDEN_TYPES:
            self._hide(0, len(text))
        elif info.type in _HIDDEN_MARKER_TYPES:
            self._hide(0, info.marker_len)
        elif info.type is BlockType.TASK_LIST_ITEM:
            # `- ` は残し `[ ]` だけ潰す。記号は paintEvent が ☐ で描く（§6.4）
            bracket = text.find("[", 0, info.marker_len)
            if bracket >= 0:
                self._hide(bracket, 3)

    def _merge(self, start: int, length: int, extra: QTextCharFormat) -> None:
        """すでに載っている書式に重ねる。

        単に `setFormat()` すると外側の書式が消える。スパンは外側が先に
        並んでいる（`inline_scanner.scan()` の約束）ので、先頭位置の書式を
        読んで重ねれば入れ子が正しく合成される。
        """
        if length <= 0:
            return
        merged = QTextCharFormat(self.format(start))
        merged.merge(extra)
        self.setFormat(start, length, merged)

    def _hide(self, start: int, length: int) -> None:
        if length <= 0:
            return
        merged = QTextCharFormat(self.format(start))
        # フォントファミリは本文のまま、サイズだけ潰す。ファミリを変えると
        # 行の高さ計算が跳ねる（§3.3 の注意点）。
        merged.setFontPointSize(HIDDEN_POINT_SIZE)
        self.setFormat(start, length, merged)

    # --------------------------------------------------------------- 書式定義

    def _build_formats(self) -> None:
        theme = self._theme
        base = self._base_point_size

        self._heading = {}
        for level, scale in HEADING_SCALE.items():
            fmt = QTextCharFormat()
            fmt.setFontPointSize(base * scale)
            fmt.setFontWeight(QFont.Weight.Bold)
            if level >= 5:
                fmt.setForeground(QColor(theme.muted_foreground))
            self._heading[level] = fmt

        self._code_block = QTextCharFormat()
        self._code_block.setFontFamilies(mono_families(self._mono_family))
        self._code_block.setForeground(QColor(theme.code_foreground))
        self._code_block.setBackground(QColor(theme.code_background))

        self._quote = QTextCharFormat()
        self._quote.setForeground(QColor(theme.quote_foreground))

        self._mono = QTextCharFormat()
        self._mono.setFontFamilies(mono_families(self._mono_family))

        strong = QTextCharFormat()
        strong.setFontWeight(QFont.Weight.Bold)

        em = QTextCharFormat()
        em.setFontItalic(True)

        strong_em = QTextCharFormat()
        strong_em.setFontWeight(QFont.Weight.Bold)
        strong_em.setFontItalic(True)

        code = QTextCharFormat()
        code.setFontFamilies(mono_families(self._mono_family))
        code.setBackground(QColor(theme.code_background))
        code.setForeground(QColor(theme.code_foreground))

        strike = QTextCharFormat()
        strike.setFontStrikeOut(True)

        highlight = QTextCharFormat()
        highlight.setBackground(QColor(theme.highlight_background))

        link = QTextCharFormat()
        link.setForeground(QColor(theme.accent))
        link.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)

        image = QTextCharFormat()
        image.setForeground(QColor(theme.accent))

        tag = QTextCharFormat()
        tag.setForeground(QColor(theme.tag_foreground))
        tag.setBackground(QColor(theme.tag_background))

        self._span_formats: dict[SpanType, QTextCharFormat] = {
            SpanType.STRONG: strong,
            SpanType.EM: em,
            SpanType.STRONG_EM: strong_em,
            SpanType.CODE: code,
            SpanType.STRIKE: strike,
            SpanType.HIGHLIGHT: highlight,
            SpanType.LINK_TEXT: link,
            SpanType.AUTOLINK: link,
            SpanType.IMAGE: image,
            SpanType.TAG: tag,
        }

        # 未使用だが、リンクのクリック判定（Phase 6）で色を引くために保持する
        self._link_color = QColor(theme.accent)
        self._rule_color = QColor(theme.rule)
        self._cursor_shape = Qt.CursorShape.IBeamCursor
