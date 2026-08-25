"""Markdown のライブプレビュー用ハイライタ（spec §6.3, §6.4）。

**マーカーは削除も置換もしない。** `setFontPointSize(0.5)` で潰すだけ（R4）。
文字が実在し続けるので `QTextCursor` の位置とソース文字列のオフセットが
常に 1:1 で一致し、位置マッピングのテーブルが一切要らない。これが本方式の
最大の利点なので、ここを崩す変更をしてはいけない。

`highlightBlock()` は変更のあったブロックにだけ Qt が自動で呼ぶ。
全体再ハイライトはテーマ変更時と起動時に限る（R7）。
"""

from dataclasses import dataclass

from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QSyntaxHighlighter,
    QTextBlock,
    QTextBlockUserData,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QPlainTextDocumentLayout

from hitofude.core.block_parser import classify_line
from hitofude.core.code_tokens import tokenize
from hitofude.core.inline_scanner import image_only_line, scan
from hitofude.core.models import (
    UNKNOWN_NOTE_KIND,
    BlockInfo,
    BlockState,
    BlockType,
    InlineSpan,
    SpanType,
)
from hitofude.core.table import WrappedRow, fits, wrap_row, wrapped_columns
from hitofude.core.textpos import py_to_utf16, utf16_to_py
from hitofude.editor.painter_overlay import (
    BULLET_GAP_RATIO,
    CHECKBOX_GAP_RATIO,
    CODE_NAME_GAP,
    CODE_NAME_PAD_Y,
    CODE_NAME_SCALE,
    HIDDEN_POINT_SIZE,
    TABLE_FAMILIES,
    WRAP_CELL_PADDING,
    bullet_column,
    bullet_size,
    checkbox_size,
)
from hitofude.theme import LIGHT, ThemeColors

# 0.5pt にすると 1 文字あたり残る幅は約 0.5px（spec §3.3 の実測）。
# 0 は Qt が「未指定」と解釈するため使えない。
# 潰した文字の大きさは描く側（painter_overlay）に置いた。**2 か所に
# 持つと片方だけ直したときに「潰したのに点が出ない」になる**

INLINE_SCAN_LIMIT = 4000
"""1 行がこれを超えたらインライン装飾を諦める（レビュー指摘）。

**打鍵のたびにその行を丸ごと解析する。** 実測は 2,000 字 2.5ms /
4,000 字 4.9ms / 8,000 字 9.9ms / 20,000 字 10〜26ms（中身による）で、
§6.6 の予算は 16ms。ここは**予算の 3 割**に収まる線。

ふつうの文章はまず届かない（原稿用紙 10 枚ぶんが 1 行に入っている状態）。
届くのは貼り付けた JSON や Base64 で、そこに強調やリンクは無い。
"""

# `[ ]` の 3 文字。ここに箱を置く幅を持たせる（`_hide_checkbox_slot`）
CHECKBOX_SLOT_CHARS = 3

# 色を付けるコードブロックの上限（B-6）。打鍵のたびにブロック全体を解析し直す
# ので、長いほど遅くなる。**ウィジェットで実測した打鍵 p95**:
#
#     150 行  9.2ms / 200 行 11.6ms / 250 行 14.3ms / 300 行 17.5ms / 400 行 22.0ms
#
# §6.6 の基準は 16ms。250 行でも 14.3ms と余裕が無いので 200 行で打ち切る。
# **超えたら色を付けないだけ**で、コードはそのまま読める
MAX_HIGHLIGHT_LINES = 200

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
    {
        BlockType.CODE_FENCE_BODY,
        BlockType.CODE_FENCE_OPEN,
        BlockType.CODE_FENCE_CLOSE,
        # 数式の中の `_` や `*` は装飾ではない（B-5）
        BlockType.MATH_BODY,
        BlockType.MATH_DELIMITER,
    }
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
        # 複数行の数式の `$$` の行（B-5）。中身は背景で表すので記号は要らない
        BlockType.MATH_DELIMITER,
    }
)

# `:::note info` と閉じの `:::`（B-3）。囲みは縦線で表すので記号は要らない。
# **ただし種類の綴りが違うときは隠さない**（`_hide_block_markers`）。
# 隠すと灰色の線が出るだけで、何を間違えたかが画面から消える（ユーザー報告）

# 行頭マーカーを潰すブロック。リストは「記号自体が意味を持つ」ので含めない（§6.4）
_HIDDEN_MARKER_TYPES = frozenset({BlockType.HEADING, BlockType.BLOCKQUOTE})

_MONO_TYPES = frozenset({BlockType.TABLE_ROW, BlockType.TABLE_DELIMITER})

# 縁の行に残す高さ（px）。帯の中の 1 行目の呼吸になる。
# **開き側だけ。** 行間（leading）が各行の下側に付くフォントでは、
# 最終行が既に下の余白を持っており、閉じ側にも足すと下だけ大きく
# 空いて見える（ユーザー指摘）
BAND_EDGE_PADDING = 7.0


def _data_type(block: QTextBlock):
    """そのブロックの解析済みの種類。初回パスでまだ無ければ None。"""
    data = block.userData()
    return data.info.type if data is not None else None


def _decode_in_math(block: QTextBlock) -> bool:
    """そのブロックの終わりが数式の中か（開き $$ と閉じ $$ の見分け）。"""
    if not block.isValid():
        return False
    state = block.userState()
    if state == -1:
        return False
    return BlockState.decode(state).in_math


class BlockData(QTextBlockUserData):
    """`QTextBlock` にぶら下げる解析結果（spec §6.2）。

    `paintEvent()`（縦バーやチェックボックスの描画）と `block_decorator`
    （余白・インデント）はここから読む。Qt での標準的なやり方。
    """

    def __init__(
        self,
        info: BlockInfo,
        spans: list[InlineSpan],
        wrapped: WrappedRow | None = None,
        *,
        figure_latex: str | None = None,
        diagram: str | None = None,
        figure_band: bool = False,
    ) -> None:
        super().__init__()
        self.info = info
        self.spans = spans
        self.wrapped = wrapped
        """収まらない表の折り返し内容（ADR-0017）。折り返し表示中の行だけ持つ。"""
        self.figure_latex = figure_latex
        """数式ブロックの中身（I-1 / ADR-0020）。図で表示中の最初の本文行だけ持つ。"""
        self.figure_band = figure_band
        """帯を「図の色」で塗るか（数式 / mermaid。描画が読む）。"""
        self.diagram = diagram
        """Mermaid 図の中身（I-1 / ADR-0021）。図で表示中の最初の本文行だけ持つ。"""


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
        # 表 1 行に使える桁数（半角換算）。0 は「まだ分からない」
        self._table_columns = 0
        self._selection: tuple[int, int] | None = None
        self._source_mode = False
        # 巨大ファイルガード（§6.6 / R7）。True の間は何も描かない
        self._plain_mode = False
        self._cell_pad: QTextCharFormat | None = None
        self._checkbox_pad: QTextCharFormat | None = None
        self._bullet_pad: QTextCharFormat | None = None
        self._code_name_pad: QTextCharFormat | None = None
        # `setFormat` の位置変換用。`highlightBlock` の先頭で更新する
        self._line = ""
        self._line_is_bmp_only = True
        # 折り返し表示中の表の行（ADR-0017）。highlightBlock ごとに詰め直す
        self._pending_wrapped: WrappedRow | None = None
        # 数式ブロックの図（I-1 / ADR-0020）。最初の本文行にだけ載せる
        self._pending_figure: str | None = None
        # このブロックの帯は「図の色」か（数式 / mermaid。ユーザー要望）
        self._pending_band = False
        # 式の絵の大きさの問い合わせ口。エディタが挿す（画像と同じ分担）
        self._math_size: object = None
        # Mermaid 図の中身（ADR-0021）。最初の本文行にだけ載せる
        self._pending_diagram: str | None = None
        self._mermaid_size: object = None
        self._table_spacing_cache: tuple[float, float] | None = None
        self._build_formats()

    # ------------------------------------------------------------------ 設定

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._build_formats()
        self.rehighlight()  # テーマ変更は全体再ハイライトが許される数少ない場面（R7）

    @property
    def mono_family(self) -> str:
        """等幅フォント名。タブ幅の計算にも使う（`editor_widget._apply_tab_width`）。"""
        return self._mono_family

    def set_mono_family(self, family: str) -> None:
        """コード・表に使う等幅フォント（spec §5.2）。"""
        if family == self._mono_family:
            return
        self._mono_family = family
        self._build_formats()
        self.rehighlight()

    @property
    def base_point_size(self) -> float:
        """本文の大きさ。見出しやコードはここから決まる。"""
        return self._base_point_size

    def set_base_point_size(self, size: float) -> None:
        self._base_point_size = size
        self._build_formats()
        self.rehighlight()

    def set_image_width(self, width: int) -> bool:
        """画像の最大幅だけ差し替える（I-3）。変わったら True。

        呼び手はそのとき画像の行だけを掛け直す（全体再ハイライトは R7 違反）。
        """
        if width == self._image_width:
            return False
        self._image_width = width
        return True

    def set_mermaid_source(self, size_getter) -> None:
        """Mermaid 図の大きさの問い合わせ口（ADR-0021）。`str -> QSize | None`。

        描画は非同期で、出来ていない間は None が返る（生のまま見せる）。
        """
        self._mermaid_size = size_getter

    def set_math_source(self, size_getter) -> None:
        """数式の絵の大きさの問い合わせ口（I-1）。`str -> QSize | None`。

        エディタが挿す。大きさ・色・幅の決定はエディタ側にあり、
        ハイライタは高さの予約に使うだけ。
        """
        self._math_size = size_getter

    def set_image_source(self, cache, width: int) -> None:
        """画像行の高さを決めるための出どころ（タスク A-2）。

        繋がっていなければ画像行はふつうの文字として描く。
        """
        self._image_cache = cache
        self._image_width = width

    def set_table_columns(self, columns: int) -> None:
        """表 1 行に使える桁数を伝える（ユーザー報告 / ADR-0003 追記）。

        **ここでは再ハイライトしない。** 呼び出し側が `|` を含むブロック
        だけを掛け直す（R7）。幅が変わるのはウィンドウを動かしたときだけで、
        本文の大半は表ではない。
        """
        self._table_columns = max(0, int(columns))

    @property
    def table_columns(self) -> int:
        return self._table_columns

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

    def set_plain_mode(self, enabled: bool) -> None:
        """巨大ファイルガード（§6.6 / R7）。装飾を丸ごと止める。

        **ここでは再ハイライトしない。** ノートを開く直前に切り替える前提で、
        直後の `setPlainText()` が初回ハイライトを走らせる（走っても即
        return するので何も起きない）。
        """
        self._plain_mode = enabled

    @property
    def plain_mode(self) -> bool:
        return self._plain_mode

    # ------------------------------------------------------------- ハイライト

    def highlightBlock(self, text: str) -> None:
        if self._plain_mode:
            # 巨大ファイル（§6.6 / R7）。解析ごと止める。userData を
            # 付けないので paintEvent の装飾も何も描かれない
            return
        block = self.currentBlock()
        # `text` は Python 単位（🍎 = 1 文字）、`setFormat` と `block.position()`
        # は UTF-16 単位（🍎 = 2）。この行の解析はすべて Python 単位で行い、
        # `setFormat` / `format` のオーバーライドが境界で変換する
        self._line = text
        self._line_is_bmp_only = text.isascii() or all(ord(char) < 0x10000 for char in text)
        self._pending_wrapped = None
        self._pending_figure = None
        self._pending_diagram = None
        self._pending_band = False
        state = BlockState.decode(self.previousBlockState())
        info, next_state = classify_line(text, block.blockNumber(), state)

        in_code = info.type in _CODE_BLOCK_TYPES
        # **長すぎる行は装飾を諦める**（レビュー指摘）。打鍵のたびにその行を
        # 丸ごと解析するので、巨大な JSON や Base64 を貼ると 1 行で予算
        # （§6.6 の 16ms）を使い切る。実測: 2,000 字 2.5ms / 4,000 字 4.9ms /
        # 8,000 字 9.9ms / 20,000 字 10〜26ms（中身による）。
        # `core/stats.is_huge` は行数と総量しか見ておらず、**短いファイルの
        # 中の 1 行**は素通りしていた
        spans = [] if in_code or len(text) > INLINE_SCAN_LIMIT else scan(text)
        reveal = self._reveal_for(block.position(), block.length(), text)

        # 区切り行より前にある表の行がヘッダ。区切り行が in_table を立てるので、
        # 引き継いだ状態が False なら「まだ区切り行に達していない」= ヘッダ
        image = None if in_code else self._image_state(text)
        if image is True:
            # 絵として描くので記号は見せない。**カーソルが入っても高さを変えない**
            # （行高が動くと下の全部が飛ぶ。§2 の「行の高さが変わらない」約束）
            self.setCurrentBlockUserData(
                BlockData(info, spans, self._pending_wrapped, figure_latex=self._pending_figure)
            )
            self.setCurrentBlockState(next_state.encode())
            return
        if image is False:
            # 読めない画像。潰すと**空行にしか見えない**ので記号ごと見せる。
            # 壊れていることが分かるほうが直せる
            reveal = _Reveal(everything=True, caret_column=None)

        is_header = info.type is BlockType.TABLE_ROW and not state.in_table
        self._apply_block_format(text, info, header=is_header)
        if info.type is BlockType.CODE_FENCE_BODY:
            self._apply_code_colors(block, text)
        if not in_code:
            self._apply_spans(text, spans, reveal)
        self._hide_block_markers(text, info, reveal)

        self.setCurrentBlockUserData(
            BlockData(
                info,
                spans,
                self._pending_wrapped,
                figure_latex=self._pending_figure,
                diagram=self._pending_diagram,
                figure_band=self._pending_band,
            )
        )
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

        大きくした 1 文字は**透明にする**。絵が上に描かれるので隠れる、と
        思っていたが、背景が透けている PNG では下の `!` が見えてしまう。
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
        # **透明にする。** 絵が上に描かれるので隠れる、と思っていたが、
        # 背景が透けている PNG（Mermaid の図など）では**巨大な `!` が
        # 透けて見えた**（ユーザー報告）。絵の不透明さに頼らない
        tall.setForeground(QColor("transparent"))
        self.setFormat(0, 1, tall)
        return True

    def _point_size_for(self, height: float) -> float:
        """その高さの行になる文字サイズ。"""
        ratio = line_height_ratio(self.document().defaultFont())
        return max(1.0, height / ratio)

    def _mermaid_band(self, info: BlockInfo) -> bool:
        """このフェンスは mermaid か（帯の色分け用）。

        閉じの有無は問わない（打ちかけでも色は図側にしておく。閉じた
        瞬間に帯の色が変わるとチラつく）。今のブロック自身は `info` で
        見る（初回パスでは userData がまだ無い）。
        """
        if info.type is BlockType.CODE_FENCE_OPEN:
            return info.lang == "mermaid"
        block = self.currentBlock()
        probe = block.previous()
        steps = 0
        while probe.isValid() and steps <= MAX_HIGHLIGHT_LINES:
            kind = _data_type(probe)
            if kind is BlockType.CODE_FENCE_OPEN:
                data = probe.userData()
                return data is not None and data.info.lang == "mermaid"
            if kind is not BlockType.CODE_FENCE_BODY:
                return False
            probe = probe.previous()
            steps += 1
        return False

    def _mermaid_run(self, info: BlockInfo) -> tuple[int, int, str] | None:
        """この行が属する Mermaid ブロックの（開始行, 終了行, ソース）。

        開始 = ```mermaid、終了 = 閉じフェンス（含む）。mermaid 以外の
        フェンスや、閉じていないフェンスなら None。

        **今のブロック自身は `info` で見る。** 初回ハイライト中は自分の
        userData がまだ無く、頼ると依頼すら出ない（回帰テストあり）。
        """
        block = self.currentBlock()
        start = block
        if info.type is BlockType.CODE_FENCE_CLOSE:
            start = start.previous()
        while start.isValid():
            kind = info.type if start == block else _data_type(start)
            if kind is not BlockType.CODE_FENCE_BODY:
                break
            start = start.previous()
        if not start.isValid():
            return None
        if (info.type if start == block else _data_type(start)) is not BlockType.CODE_FENCE_OPEN:
            return None
        lang = info.lang if start == block else start.userData().info.lang
        if lang != "mermaid":
            return None

        lines: list[str] = []
        probe = start.next()
        while probe.isValid() and len(lines) <= MAX_HIGHLIGHT_LINES:
            kind = info.type if probe == block else _data_type(probe)
            if kind is BlockType.CODE_FENCE_CLOSE:
                return start.blockNumber(), probe.blockNumber(), "\n".join(lines)
            if kind is None and probe.text().strip().startswith("```"):
                # 初回パスでは後続の userData がまだ無い（`_fence_body` と同じ）
                return start.blockNumber(), probe.blockNumber(), "\n".join(lines)
            if kind is not None and kind is not BlockType.CODE_FENCE_BODY:
                return None
            lines.append(probe.text())
            probe = probe.next()
        return None

    def _apply_mermaid_figure(self, text: str, info: BlockInfo) -> bool:
        """Mermaid ブロックを図で表示する。できなければ False（生のまま）。

        数式（`_apply_math_figure`）と同じ形。描画は非同期なので、
        絵が出来ていない間（size が None）は生のまま見せ、出来た時点で
        エディタが掛け直す（`MermaidCache.rendered`）。
        """
        run = self._mermaid_run(info)
        if run is None:
            return False
        start, end, source = run
        if not source.strip() or self._caret_in_lines(start, end):
            return False
        size = self._mermaid_size(source)
        if size is None:
            return False  # 依頼中か、描けない図。生のまま
        self._hide(0, len(text))
        number = self.currentBlock().blockNumber()
        if number == start + 1:
            tall = QTextCharFormat()
            tall.setFontPointSize(self._point_size_for(size.height() + IMAGE_PADDING * 2))
            tall.setForeground(QColor("transparent"))
            self.setFormat(0, 1, tall)
            self._pending_diagram = source
        elif number == start:
            self._pad_band_edge(text)  # 開きのフェンスは帯の縁の余白になる
        return True

    def _math_run(self) -> tuple[int, int, str] | None:
        """この行が属する数式ブロックの（開始行, 終了行, LaTeX）。

        開始・終了は $$ の行（含む）。閉じていなければ None（打ちかけの
        式を絵にすると、書いている途中で行が消える）。上へ辿って開きを
        探し、下へ辿って閉じまでを集める（`_fence_body` と同じ手）。
        """
        block = self.currentBlock()
        start = block
        while start.isValid():
            data = start.userData()
            kind = data.info.type if data is not None else None
            if kind is BlockType.MATH_DELIMITER and not _decode_in_math(start.previous()):
                break  # 開きの $$（前の行が式の中ではない）
            if kind not in (BlockType.MATH_BODY, BlockType.MATH_DELIMITER) and start is not block:
                return None
            start = start.previous()
        if not start.isValid():
            return None

        lines: list[str] = []
        probe = start.next()
        while probe.isValid() and len(lines) <= MAX_HIGHLIGHT_LINES:
            data = probe.userData()
            if data is not None and data.info.type is BlockType.MATH_DELIMITER:
                return start.blockNumber(), probe.blockNumber(), "\n".join(lines)
            if data is None and probe.text().strip() == "$$":
                # 初回パスでは後続の userData がまだ無い（`_fence_body` と同じ）
                return start.blockNumber(), probe.blockNumber(), "\n".join(lines)
            lines.append(probe.text())
            probe = probe.next()
        return None

    def _apply_math_figure(self, text: str) -> bool:
        """数式ブロックを図で表示する。できなければ False（生のまま）。

        画像（ADR-0004）と同じ手口で行を隠して高さを予約する。リビールは
        表（ADR-0017）と同じ考え方だが、行単位ではなく**式全体**:
        キャレットがどの行に入っても式全体が生の LaTeX に戻る。
        途中の行だけ生に戻ると、式の断片と絵が同時に見えて読めない。
        """
        run = self._math_run()
        if run is None:
            return False
        start, end, latex = run
        if not latex.strip() or self._caret_in_lines(start, end):
            return False
        size = self._math_size(latex)
        if size is None:
            return False  # 壊れた式。生のまま見せて直せるようにする

        self._hide(0, len(text))
        number = self.currentBlock().blockNumber()
        if number == start + 1:
            tall = QTextCharFormat()
            tall.setFontPointSize(self._point_size_for(size.height() + IMAGE_PADDING * 2))
            tall.setForeground(QColor("transparent"))
            self.setFormat(0, 1, tall)
            self._pending_figure = latex
        elif number == start:
            self._pad_band_edge(text)  # 開きの $$ は帯の縁の余白になる
        return True

    def _caret_in_lines(self, start: int, end: int) -> bool:
        """キャレット（または選択）が行の範囲 [start, end] に触れているか。"""
        document = self.document()
        positions = []
        if self._reveal_position is not None:
            positions.append(self._reveal_position)
        if self._selection is not None:
            positions.extend(self._selection)
        numbers = [document.findBlock(position).blockNumber() for position in positions]
        if any(start <= number <= end for number in numbers):
            return True
        # 選択が式をまたいで両端とも外にある場合
        if self._selection is not None and len(numbers) >= 2:
            return numbers[-2] <= start and end <= numbers[-1]
        return False

    def _pad_band_edge(self, text: str) -> None:
        """隠した縁の行（``` / $$ / :::）に帯の余白ぶんの高さを残す。

        文字は透明のまま少しだけ大きくする（ADR-0004 と同じレバー。
        R4/R5 に触れない）。**行末の 1 文字**に載せる: 先頭は「隠れて
        いれば 0.5pt」という既存の検査・ファイル名バッジ・図の高さ予約が
        使っているため。
        """
        if not text or self.format(0).fontPointSize() > HIDDEN_POINT_SIZE:
            return  # 既に高さを持っている（ファイル名バッジ・図の予約）
        pad = QTextCharFormat()
        pad.setFontPointSize(self._point_size_for(BAND_EDGE_PADDING))
        pad.setForeground(QColor("transparent"))
        self.setFormat(len(text) - 1, 1, pad)

    def _table_run_texts(self) -> list[str]:
        """このブロックが属する表の全行。折り返しの列幅は表全体から決まる。

        userData には頼らない（初回パスではまだ無い。`_fence_body` と同じ理由）。
        `|` で始まる行の連続を表の並びと見なす。上限は保険（巨大な表で
        打鍵ごとの走査が膨らまないように）。
        """
        block = self.currentBlock()
        rows = [block.text()]
        probe = block.previous()
        while probe.isValid() and probe.text().lstrip().startswith("|") and len(rows) < 200:
            rows.insert(0, probe.text())
            probe = probe.previous()
        probe = block.next()
        while probe.isValid() and probe.text().lstrip().startswith("|") and len(rows) < 200:
            rows.append(probe.text())
            probe = probe.next()
        return rows

    def _reserve_wrapped_row(self, text: str, run: list[str]) -> None:
        """収まらない表の行を隠し、折り返しぶんの高さを予約する（ADR-0017）。

        画像（ADR-0004）と同じ手口: 全文字を 0.5pt に潰し、先頭 1 文字だけを
        **透明のまま**拡大して高さを作る。中身は paintEvent が
        `BlockData.wrapped` から描くので、ソースには触らない（R1/R4 無傷）。
        """
        widths = wrapped_columns(run, self._table_columns)
        if not widths:
            return
        cells = wrap_row(text, widths)
        wrapped = WrappedRow(tuple(widths), tuple(tuple(lines) for lines in cells))

        self._hide(0, len(text))
        tall = QTextCharFormat()
        height = wrapped.lines * self._table_line_spacing() + WRAP_CELL_PADDING * 2
        tall.setFontPointSize(self._point_size_for(height))
        tall.setForeground(QColor("transparent"))
        self.setFormat(0, 1, tall)
        self._pending_wrapped = wrapped

    def _table_line_spacing(self) -> float:
        """折り返しセル 1 行ぶんの高さ。描画側（paintEvent）と同じフォントで測る。"""
        size = self.document().defaultFont().pointSizeF()
        if self._table_spacing_cache and self._table_spacing_cache[0] == size:
            return self._table_spacing_cache[1]
        font = QFont()
        font.setFamilies(TABLE_FAMILIES)
        font.setPointSizeF(size)
        spacing = float(QFontMetricsF(font).lineSpacing())
        self._table_spacing_cache = (size, spacing)
        return spacing

    def _reveal_for(self, block_start: int, block_length: int, text: str) -> _Reveal:
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
            # キャレット位置は UTF-16 単位。スパン（Python 単位）と比べる前に直す
            column = utf16_to_py(text, self._reveal_position - block_start)
            return _Reveal(everything=False, caret_column=column)
        return _Reveal(everything=False, caret_column=None)

    # ----------------------------------------------------------- 書式の適用

    def _apply_block_format(self, text: str, info: BlockInfo, *, header: bool = False) -> None:
        if not text:
            return
        match info.type:
            case BlockType.HEADING:
                self.setFormat(0, len(text), self._heading[info.level])
            case BlockType.MATH_BODY | BlockType.MATH_DELIMITER:
                # 図になるブロックはコードより薄い背景（ユーザー要望）
                self._pending_band = True
                self.setFormat(0, len(text), self._figure_block)
            case BlockType.CODE_FENCE_BODY | BlockType.CODE_FENCE_OPEN | BlockType.CODE_FENCE_CLOSE:
                if self._mermaid_band(info):
                    self._pending_band = True
                    self.setFormat(0, len(text), self._figure_block)
                else:
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
        if not text:
            return
        if (
            info.type in (BlockType.MATH_BODY, BlockType.MATH_DELIMITER)
            and not self._source_mode
            and self._math_size is not None
            and self._apply_math_figure(text)
        ):
            # 図で表示した（I-1 / ADR-0020）。リビールは**式全体**で判定
            # 済みなので、ブロック単位の reveal には進まない
            return
        if (
            info.type
            in (BlockType.CODE_FENCE_OPEN, BlockType.CODE_FENCE_BODY, BlockType.CODE_FENCE_CLOSE)
            and not self._source_mode
            and self._mermaid_size is not None
            and self._apply_mermaid_figure(text, info)
        ):
            return
        if info.type is BlockType.FRONT_MATTER:
            # **Raw でも出さない。** `id` や `created` はアプリの管理情報で、
            # 書く人が触るものではない。Raw は「Markdown の記号を出して直す」
            # ためのモードなので、記法でないものまで出す必要がない
            self._hide(0, len(text))
            return
        if reveal.block_marker:
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
                if text.strip() != ":::":
                    self._pad_band_edge(text)  # 開き（:::note 種類）だけ
        elif info.type in _FULLY_HIDDEN_TYPES and info.type is not BlockType.TABLE_DELIMITER:
            self._hide(0, len(text))
            if info.type is BlockType.CODE_FENCE_OPEN or (
                info.type is BlockType.MATH_DELIMITER
                and not _decode_in_math(self.currentBlock().previous())
            ):
                self._pad_band_edge(text)  # 帯の開き側の余白
        elif info.type in _HIDDEN_MARKER_TYPES:
            self._hide(0, info.marker_len)
        elif info.type in (BlockType.TABLE_ROW, BlockType.TABLE_DELIMITER):
            # 折り返すか（ADR-0017）は**表全体**で決める。1 行だけ折り返すと
            # 列の線が行ごとにずれて表にならない
            run = self._table_run_texts()
            wrapped_mode = self._table_columns > 0 and any(
                not fits(row, self._table_columns) for row in run
            )
            if info.type is BlockType.TABLE_DELIMITER:
                # 区切り行は折り返し表示でも隠す（線は paintEvent が引く）。
                # 収まる表と同じ扱いで、薄い 1 行として残る
                if wrapped_mode or fits(text, self._table_columns):
                    self._hide(0, len(text))
            elif wrapped_mode:
                self._reserve_wrapped_row(text, run)
            else:
                # `|` は罫線として描く（§5.2 の描画フック）。文字は残すので
                # キャレット位置とソースのオフセットは 1:1 のまま（R4）
                for index, character in enumerate(text):
                    if character == "|":
                        self._hide(index, 1)
        elif info.type is BlockType.BULLET_LIST_ITEM:
            # `-` / `*` を潰して点を描く（ユーザー要望 2026-08-22）。**空白は
            # 残す**ので、本文の始まる位置は今までどおり
            marker = bullet_column(text, info.marker_len)
            if marker >= 0:
                self._hide_bullet_slot(marker)
        elif info.type is BlockType.TASK_LIST_ITEM:
            # `[ ]` を潰して箱を描く（§6.4）。**`- ` も潰す**（ADR-0026）。
            # 箱が意味を担うので、生の `-` が残ると点の行と不揃いに見える。
            # ここには点を描かない（箱と二重になる）
            marker = bullet_column(text, info.marker_len)
            if marker >= 0:
                self._hide(marker, 1)
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

    def _apply_code_colors(self, block: QTextBlock, text: str) -> None:
        """コードブロックの中に色を付ける（B-6）。

        **1 行だけを見て解析してはいけない。** 複数行の文字列やコメントは
        行をまたぐので、その中の `def` が予約語に見えてしまう。ブロック全体を
        1 回解析して、この行の分だけを取り出す（解析結果は `core/code_tokens`
        が覚えているので、打っていない間は解析し直さない）。
        """
        found = self._fence_body(block)
        if found is None:
            return
        lang, body, index = found
        if body.count("\n") >= MAX_HIGHLIGHT_LINES:
            return  # 長すぎるものは色を付けない。打鍵が重くなるほうが困る

        lines = tokenize(body, lang, dark=self._theme.is_dark)
        if index >= len(lines):
            return
        for span in lines[index]:
            if span.start + span.length > len(text):
                continue
            colored = QTextCharFormat(self._code_block)
            colored.setForeground(QColor(span.color))
            colored.setFontWeight(QFont.Weight.Bold if span.bold else QFont.Weight.Normal)
            colored.setFontItalic(span.italic)
            self.setFormat(span.start, span.length, colored)

    def _fence_body(self, block: QTextBlock) -> tuple[str, str, int] | None:
        """この行が属するコードブロックの `(言語, 中身, 何行目か)`。

        言語が分からなければ None。**上へ辿って開始行を探し、下へ辿って
        終了行までを集める。** 行単位のハイライタからブロック全体を見るには
        こうするしかない。
        """
        start = block.previous()
        offset = 0
        while start.isValid():
            data = start.userData()
            if data is None or data.info.type is not BlockType.CODE_FENCE_BODY:
                break
            start = start.previous()
            offset += 1

        opening = start.userData() if start.isValid() else None
        if opening is None or opening.info.type is not BlockType.CODE_FENCE_OPEN:
            return None
        if not opening.info.lang:
            return None  # 言語の指定が無ければ色を付けない

        # 閉じフェンスをテキストで見分けるための記号と長さ。
        # `` ```` `` で開いたブロックは ` ``` ` では閉じない（CommonMark）
        opening_text = start.text().lstrip()
        fence_char = opening_text[0] if opening_text[:1] in ("`", "~") else "`"
        fence_len = len(opening_text) - len(opening_text.lstrip(fence_char))

        lines = []
        probe = start.next()
        while probe.isValid():
            data = probe.userData()
            if data is not None:
                if data.info.type is not BlockType.CODE_FENCE_BODY:
                    break
            else:
                # 初回パスでは後続ブロックの userData がまだ無い。ここで
                # 止まらないと文書末尾まで集めてしまい、200 行ガードに
                # 当たって「開いた直後だけ色が付かない」が起きる
                stripped = probe.text().strip()
                if stripped and set(stripped) == {fence_char} and len(stripped) >= fence_len:
                    break
            if len(lines) > MAX_HIGHLIGHT_LINES:
                break  # どうせ色を付けない長さ。走査もここで打ち切る
            lines.append(probe.text())
            probe = probe.next()
        return opening.info.lang, "\n".join(lines), offset

    def _code_name_slot(self) -> QTextCharFormat:
        """ファイル名を描く高さを作る書式（`painter_overlay` が上に文字を描く）。

        高さは R4 と同じ「文字の大きさ」で作る。`QTextBlockFormat` は
        使えない（R5）。ADR-0004 が画像の行高で使ったのと同じ手。
        """
        slot = self._code_name_pad
        if slot is None:
            # バッジ（文字 + 上下の余白）と、コード本体との隙間のぶんを確保する
            label = QFont(self.document().defaultFont())
            label.setPointSizeF(max(self._base_point_size * CODE_NAME_SCALE, 1.0))
            height = QFontMetricsF(label).height() + CODE_NAME_PAD_Y * 2 + CODE_NAME_GAP
            slot = QTextCharFormat()
            slot.setFontPointSize(self._point_size_for(height))
            slot.setForeground(QColor("transparent"))
            self._code_name_pad = slot
        return slot

    def _hide_bullet_slot(self, start: int) -> None:
        """`-` の 1 文字を潰しつつ、**点を置く幅だけ残す**。

        チェックの箱（`_hide_checkbox_slot`）と同じ手。字送りで幅を作るので
        文字は足さず、キャレット位置とソースのオフセットは 1:1（R4）。
        """
        pad = self._bullet_pad
        if pad is None:
            reserve = bullet_size(self.document().defaultFont()) * (1 + BULLET_GAP_RATIO)
            pad = QTextCharFormat()
            pad.setFontPointSize(HIDDEN_POINT_SIZE)
            pad.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
            pad.setFontLetterSpacing(reserve)
            self._bullet_pad = pad
        self.setFormat(start, 1, pad)

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

    # ------------------------------------------------- 位置の単位変換（R4 の境界）

    def setFormat(self, start: int, count: int, char_format: QTextCharFormat) -> None:
        """Python 単位の位置を UTF-16 へ直してから Qt に渡す。

        この行の解析（スキャナ・`len(text)`・`enumerate`）はすべて
        Python 単位なので、境界をここ 1 か所に集める。BMP 内だけの行は
        単位が一致するので、そのまま通す（大半の行がこちら）。
        """
        if self._line_is_bmp_only:
            super().setFormat(start, count, char_format)
            return
        begin = py_to_utf16(self._line, start)
        end = py_to_utf16(self._line, start + count)
        super().setFormat(begin, end - begin, char_format)

    def format(self, position: int) -> QTextCharFormat:
        """`setFormat` の逆向き。読むときも同じ変換を通す（`_merge` / `_hide`）。"""
        if self._line_is_bmp_only:
            return super().format(position)
        return super().format(py_to_utf16(self._line, position))

    # --------------------------------------------------------------- 書式定義

    def _build_formats(self) -> None:
        self._cell_pad = None
        self._checkbox_pad = None
        self._bullet_pad = None
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
        # 図（数式・mermaid）の生表示。文字はコードと同じ等幅で、
        # 背景だけ薄い図の色にする（ユーザー要望）
        self._figure_block = QTextCharFormat(self._code_block)
        self._figure_block.setBackground(QColor(theme.figure_background))

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

        # 背景は付けない。帯は paintEvent が上に余白を持たせて描く
        # （ユーザー要望。QTextCharFormat の背景では上の余白が作れない）
        code = QTextCharFormat()
        code.setFontFamilies(mono_families(self._mono_family))
        code.setForeground(QColor(theme.code_foreground))

        strike = QTextCharFormat()
        strike.setFontStrikeOut(True)

        # ハイライトも帯は paintEvent（同上）。文字書式としては何も持たない
        highlight = QTextCharFormat()

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
            # ノート間リンク（E-6）。**行き先があるかで色を変えない。**
            # 変えると、他のノートを作った / 消しただけで全体を塗り直す
            # 必要が出て、R7（全体再ハイライトの禁止）と衝突する
            SpanType.WIKI_LINK: link,
            SpanType.IMAGE: image,
            SpanType.TAG: tag,
            # 脚注の参照（B-3）。リンクと同じ扱いにする。飛び先を持つ印という
            # 意味では同じもので、色を分けても覚えることが増えるだけ
            SpanType.FOOTNOTE: link,
            # 数式（B-5）。画面では組版しないので、**等幅にして式だと分かる**
            # ようにする。絵にするには matplotlib（実測 74MB）が要る
            SpanType.MATH: code,
        }
