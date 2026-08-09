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
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QPlainTextDocumentLayout

from hitofude.core.block_parser import classify_line
from hitofude.core.inline_scanner import image_only_line, scan
from hitofude.core.models import (
    UNKNOWN_NOTE_KIND,
    BlockInfo,
    BlockState,
    BlockType,
    InlineSpan,
    SpanType,
)
from hitofude.editor.painter_overlay import (
    CHECKBOX_GAP_RATIO,
    CODE_NAME_SCALE,
    checkbox_size,
)
from hitofude.theme import LIGHT, ThemeColors

# 0.5pt にすると 1 文字あたり残る幅は約 0.5px（spec §3.3 の実測）。
# 0 は Qt が「未指定」と解釈するため使えない。
HIDDEN_POINT_SIZE = 0.5

# `[ ]` の 3 文字。ここに箱を置く幅を持たせる（`_hide_checkbox_slot`）
CHECKBOX_SLOT_CHARS = 3

# 画像行の余白（絵の上下）。詰まりすぎると本文と見分けが付かない
IMAGE_PADDING = 8.0
# 行高の比を測るときの基準サイズ。小さすぎると丸め誤差が効く
_PROBE_POINT_SIZE = 100.0
_HEIGHT_RATIOS: dict[tuple[str, float], float] = {}


def line_height_ratio(font: QFont) -> float:
    """そのフォントで「1pt あたり何 px の行になるか」。

    **`QFontMetrics` では予測できない。** 実測では Hiragino Sans が 1.500、
    Menlo が 1.005、Helvetica が 1.000 と、フォントごとに違う。Qt の組版が
    使う値と `QFontMetricsF.height()` が一致しないため、実際に 1 行組んで測る。

    フォントごとに 1 回だけ測って覚える。
    """
    key = (font.family(), font.pointSizeF())
    found = _HEIGHT_RATIOS.get(key)
    if found is not None:
        return found

    document = QTextDocument()
    document.setDocumentLayout(QPlainTextDocumentLayout(document))
    document.setDefaultFont(font)
    document.setPlainText("X")

    cursor = QTextCursor(document)
    cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
    probe = QTextCharFormat()
    probe.setFontPointSize(_PROBE_POINT_SIZE)
    cursor.setCharFormat(probe)

    height = document.documentLayout().blockBoundingRect(document.firstBlock()).height()
    ratio = height / _PROBE_POINT_SIZE if height > 0 else 1.0
    _HEIGHT_RATIOS[key] = ratio
    return ratio


DEFAULT_MONO_FAMILY = "Menlo"

# `SF Mono` は spec §5.2 の指定だが、macOS はアプリに公開していないため
# 指定しても解決されない（Qt が "missing font family" を警告する）。
# 実在するものへ順に落とす。指定フォントが無い環境でも行の高さが暴れない
MONO_FALLBACKS = ["Menlo", "Monaco", "Courier New"]

# 表は**日本語も含めて**等幅でないと縦線が揃わない。Menlo など通常の
# 等幅フォントは CJK グリフを持たず、フォールバック先の全角幅が半角の
# ちょうど 2 倍にならないため桁がずれる（実測: Menlo 1.66 倍）。
# BIZ UDGothic は macOS 標準で、全角:半角 = 2:1 が成立する数少ないフォント。
TABLE_FAMILIES = ["BIZ UDGothic", "Menlo", "Monaco", "Courier New"]

# セルの余白。文字が罫線に接していると読みにくい。
# **テキストは変えない**（R1）。`|` は罫線として描くので画面に出ないから、
# その透明な文字に大きさ（上下）と字送り（左右）を持たせて余白にする。
#
# 上下は点数で足す。行の高さは実際に並ぶ文字（和文か欧文か、フォントが
# その字を持つか）で決まり、px を狙って逆算しても当たらない（実測で確認）。
CELL_PADDING_POINTS = 10.0
CELL_PADDING = 5.0


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
        # 区切り行（`|---|---|`）は罫線として描くので文字は見せない
        BlockType.TABLE_DELIMITER,
    }
)

# `:::note info` と閉じの `:::`（B-3）。囲みは縦線で表すので記号は要らない。
# **ただし種類の綴りが違うときは隠さない**（`_hide_block_markers`）。
# 隠すと灰色の線が出るだけで、何を間違えたかが画面から消える（ユーザー報告）

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
        self._image_cache = None
        self._image_width = 0
        self._selection: tuple[int, int] | None = None
        self._source_mode = False
        self._cell_pad: QTextCharFormat | None = None
        self._checkbox_pad: QTextCharFormat | None = None
        self._code_name_pad: QTextCharFormat | None = None
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

    def set_image_source(self, cache, width: int) -> None:
        """画像行の高さを決めるための出どころ（タスク A-2）。

        繋がっていなければ画像行はふつうの文字として描く。
        """
        self._image_cache = cache
        self._image_width = width

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

        # 区切り行より前にある表の行がヘッダ。区切り行が in_table を立てるので、
        # 引き継いだ状態が False なら「まだ区切り行に達していない」= ヘッダ
        image = None if in_code else self._image_state(text)
        if image is True:
            # 絵として描くので記号は見せない。**カーソルが入っても高さを変えない**
            # （行高が動くと下の全部が飛ぶ。§2 の「行の高さが変わらない」約束）
            self.setCurrentBlockUserData(BlockData(info, spans))
            self.setCurrentBlockState(next_state.encode())
            return
        if image is False:
            # 読めない画像。潰すと**空行にしか見えない**ので記号ごと見せる。
            # 壊れていることが分かるほうが直せる
            reveal = _Reveal(everything=True, caret_column=None)

        is_header = info.type is BlockType.TABLE_ROW and not state.in_table
        self._apply_block_format(text, info, header=is_header)
        if not in_code:
            self._apply_spans(text, spans, reveal)
        self._hide_block_markers(text, info, reveal)

        self.setCurrentBlockUserData(BlockData(info, spans))
        self.setCurrentBlockState(next_state.encode())

    def _pad_cells(self, text: str) -> None:
        """セルの余白を作る。

        **`|` の隣の空白に持たせる。** 空白は元から画面に出ないので、
        大きくしても字送りを足しても見た目が変わらない。点サイズが行の
        高さ（上下）、字送りが幅（左右）になる。

        パイプ自体に持たせると、カーソルを入れて `|` を表示したときに
        余白ごと消えて**行の高さが変わってしまう**（§2 の約束を破る）。

        `format_table()` が `| A |` の形に整えるので、区切りの両隣には
        空白がある。整っていない行は余白が付かないだけで壊れない。
        """
        pad = self._cell_pad
        if pad is None:
            pad = QTextCharFormat(self._mono)
            pad.setFontPointSize(self._base_point_size + CELL_PADDING_POINTS)
            pad.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
            pad.setFontLetterSpacing(CELL_PADDING)
            self._cell_pad = pad

        for index, character in enumerate(text):
            if character != "|":
                continue
            for side in (index - 1, index + 1):
                if 0 <= side < len(text) and text[side] == " ":
                    self.setFormat(side, 1, pad)

    def _image_state(self, text: str) -> bool | None:
        """画像行の扱いを決める。

        - `True` … 絵として描くので高さを確保した
        - `False` … 画像行だが読めない（記号ごと見せる）
        - `None` … 画像行ではない

        **R5 に触れない。** `QTextBlockFormat` は使わず、R4 と同じ
        「文字の大きさ」というレバーだけで高さを作る。記号は 0.5pt に潰し、
        **1 文字だけ**大きくする。行全体を大きくすると横に伸びて折り返し、
        高さが跳ねる（実測: 240pt で 788px）。
        """
        url = image_only_line(text) if text else None
        if url is None:
            return None
        if self._source_mode or self._image_cache is None or self._image_width <= 0:
            return None

        size = self._image_cache.size(url, self._image_width)
        if size is None:
            return False

        hidden = QTextCharFormat()
        hidden.setFontPointSize(HIDDEN_POINT_SIZE)
        self.setFormat(0, len(text), hidden)

        tall = QTextCharFormat()
        tall.setFontPointSize(self._point_size_for(size[1] + IMAGE_PADDING * 2))
        self.setFormat(0, 1, tall)
        return True

    def _point_size_for(self, height: float) -> float:
        """その高さの行になる文字サイズ。"""
        ratio = line_height_ratio(self.document().defaultFont())
        return max(1.0, height / ratio)

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

    def _apply_block_format(self, text: str, info: BlockInfo, *, header: bool = False) -> None:
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
                self.setFormat(0, len(text), self._table_header if header else self._mono)
                self._pad_cells(text)
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
        if info.type is BlockType.CODE_FENCE_OPEN and info.code_name:
            # 記号は隠すが、**ファイル名を書く高さだけ残す**（ユーザー要望）。
            # 文字は透明にする。0.5pt にすると 1px 未満になって書いても
            # 見えず、素の大きさだとバッククォートが出てしまう
            self._hide(0, len(text))
            self.setFormat(0, 1, self._code_name_slot())
        elif info.type is BlockType.NOTE_DELIMITER:
            if info.note_kind != UNKNOWN_NOTE_KIND:
                self._hide(0, len(text))
        elif info.type in _FULLY_HIDDEN_TYPES:
            self._hide(0, len(text))
        elif info.type in _HIDDEN_MARKER_TYPES:
            self._hide(0, info.marker_len)
        elif info.type is BlockType.TABLE_ROW:
            # `|` は罫線として描く（§5.2 の描画フック）。文字は残すので
            # キャレット位置とソースのオフセットは 1:1 のまま（R4）
            for index, character in enumerate(text):
                if character == "|":
                    self._hide(index, 1)
        elif info.type is BlockType.TASK_LIST_ITEM:
            # `- ` は残し `[ ]` だけ潰す。箱は paintEvent が描く（§6.4）
            bracket = text.find("[", 0, info.marker_len)
            if bracket >= 0:
                self._hide_checkbox_slot(bracket)

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

    def _code_name_slot(self) -> QTextCharFormat:
        """ファイル名を描く高さを作る書式（`painter_overlay` が上に文字を描く）。

        高さは R4 と同じ「文字の大きさ」で作る。`QTextBlockFormat` は
        使えない（R5）。ADR-0004 が画像の行高で使ったのと同じ手。
        """
        slot = self._code_name_pad
        if slot is None:
            slot = QTextCharFormat()
            slot.setFontPointSize(max(self._base_point_size * CODE_NAME_SCALE, 1.0))
            slot.setForeground(QColor("transparent"))
            self._code_name_pad = slot
        return slot

    def _hide_checkbox_slot(self, start: int) -> None:
        """`[ ]` を潰しつつ、**箱を置く幅だけ残す**。

        潰しただけだと 3 文字の幅が 7.7px しか無く、そこへ箱を描くと本文に
        食い込む（ユーザー報告。実測で 4.5px 重なっていた）。

        幅は**字送り**で作る。表のセルの余白（`_pad_cells`）と同じ手で、
        文字を足さないのでキャレット位置とソースのオフセットは 1:1 のまま
        （R4）。`QTextBlockFormat` のインデントは使えない（R5）。
        """
        pad = self._checkbox_pad
        if pad is None:
            reserve = checkbox_size(self.document().defaultFont()) * (1 + CHECKBOX_GAP_RATIO)
            pad = QTextCharFormat()
            pad.setFontPointSize(HIDDEN_POINT_SIZE)
            pad.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
            pad.setFontLetterSpacing(reserve / CHECKBOX_SLOT_CHARS)
            self._checkbox_pad = pad
        self.setFormat(start, CHECKBOX_SLOT_CHARS, pad)

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
        self._cell_pad = None
        self._checkbox_pad = None
        self._code_name_pad = None
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
        self._mono.setFontFamilies(TABLE_FAMILIES)

        self._table_header = QTextCharFormat(self._mono)
        self._table_header.setFontWeight(QFont.Weight.Bold)

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
            # 脚注の参照（B-3）。リンクと同じ扱いにする。飛び先を持つ印という
            # 意味では同じもので、色を分けても覚えることが増えるだけ
            SpanType.FOOTNOTE: link,
        }

        # 未使用だが、リンクのクリック判定（Phase 6）で色を引くために保持する
        self._link_color = QColor(theme.accent)
        self._rule_color = QColor(theme.rule)
        self._cursor_shape = Qt.CursorShape.IBeamCursor
