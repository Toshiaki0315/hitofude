"""`paintEvent` で描くブロックレベルの装飾（spec §5.2, ADR-0002）。

`QSyntaxHighlighter` は文字書式しか適用できないため、背景の帯・縦バー・
水平線・チェックボックス記号は描けない。ADR-0002 で `QTextBlockFormat` を
使わないと決めたので、**ブロックレベルの見た目はすべてここが担う**。

構造を 2 段に分けている:

- `visible_decorations()` … 可視ブロックを走査して「どこに何を描くか」を組み立てる
- `paint()` … 組み立てた結果を `QPainter` に流す

前者は QPainter を持たずに検査できるので、描画のロジックをピクセル比較なしで
テストできる。
"""

from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QTextBlock

from hitofude.core.inline_scanner import image_only_line
from hitofude.core.models import BlockType, SpanType
from hitofude.core.table import Alignment
from hitofude.core.textpos import py_to_utf16
from hitofude.theme import ThemeColors

# spec §5.2
QUOTE_BAR_WIDTH = 3
QUOTE_BAR_STEP = 10
# `:::note` の縦線（B-3）。引用より太くして、引用と区別が付くようにする
NOTE_BAR_WIDTH = 4
# ファイル名を書き出す位置（`paintEvent` で描く）。左端に寄せすぎると
# 背景の角に食い込む
CODE_NAME_INSET = 8.0
# ファイル名バッジ（ユーザー要望 / Qiita 風）。文字の周りの余白と、
# バッジとコード本体のあいだの隙間。高さの予約（highlighter）も同じ値を見る
CODE_NAME_PAD_X = 8.0
CODE_NAME_PAD_Y = 3.0
CODE_NAME_GAP = 8.0
# 折り返した表のセルの上下余白（ADR-0017）。線と文字がくっつくと読みにくい。
# 高さの予約（highlighter）と文字の描画（ここ）の両方が使う
WRAP_CELL_PADDING = 4.0

# 表は**日本語も含めて**等幅でないと縦線が揃わない。Menlo など通常の
# 等幅フォントは CJK グリフを持たず、フォールバック先の全角幅が半角の
# ちょうど 2 倍にならないため桁がずれる（実測: Menlo 1.66 倍）。
# BIZ UDGothic は macOS 標準で、全角:半角 = 2:1 が成立する数少ないフォント。
# 定義がここにあるのは依存の向きの都合（highlighter がこのモジュールを
# import する。逆はできない）
# 表のセルの左右の余白（px）。縦線と文字が貼り付くと読みにくい
CELL_PAD = 9.0
# ファイル名の大きさ（本文に対する比）。見出しとして読めて、かつ主張しない
CODE_NAME_SCALE = 0.85
# インラインの帯の上下の余白と角の丸み。**文字の実寸（ascent+descent）を
# 基準**に上下対称で付ける。行ボックス（line.height()）を使うと、行間
# （leading）が下側に付くフォントで帯の下だけ大きく空く（ユーザー指摘）
INLINE_BAND_PAD = 3.0
INLINE_BAND_RADIUS = 3.0

# ブロックの帯（コード・図・注釈）の左右の内寄せと角の丸み
# （ユーザー要望 2026-08-26 / Qiita 風）。紙の端まで伸ばさず、角を丸める。
# 本文は動かせない（R5）ので、CONTENT_MARGIN との差（24 - 12 = 12px）が
# そのまま帯の中の左右の余白になる。**本文の余白より狭く保つ**——
# 逆転すると帯の縁から文字がはみ出す
BAND_MARGIN = 12.0
BAND_RADIUS = 6.0

RULE_HEIGHT = 1
LEFT_INSET = 2

# チェックボックスの状態（`Decoration.text` に載せる）。
#
# **フォントの記号（☐ / ☑）は使わない。** 実測で ☐ が 17.8x17.2px、
# ☑ が 10.1x10.5px と、別々の書体から拾われて大きさが揃わなかった
# （ユーザー報告）。枠は自分で描く。
CHECKED = "checked"
UNCHECKED = "unchecked"

# 箱の一辺と、箱と本文のあいだ。どちらも**文字の高さに対する比**。
# ハイライタは同じ比から「潰した `[ ]` に持たせる幅」を決めるので、
# ここを変えると本文の開始位置も一緒に動く（`highlighter._hide_checkbox_slot`）
CHECKBOX_SIZE_RATIO = 0.70
# 箱と本文のあいだ。`[ ]` の後ろの空白 1 つ（4px 前後）も間に入るので、
# ここは小さくてよい。0.30 だと合計 11px 空いて離れすぎだった（実測）
CHECKBOX_GAP_RATIO = 0.10
CHECKBOX_STROKE = 1.4

BULLET_SIZE_RATIO = 0.30
"""点の直径 ÷ 行の高さ。**箱（0.70）より小さい。** 印ではなく目印なので、
本文より目立つと読みの邪魔になる。"""

BULLET_STROKE = 1.2
"""白丸の輪郭。細すぎると 2 段目が消えて見える。"""

BULLET_SQUARE_INSET = 0.12
"""四角の内側の詰め。塗った四角は同じ大きさだと丸より重く見える。"""

BULLET_SHAPES = ("disc", "circle", "square")
"""深さごとの形（HTML の `list-style-type` と同じ並び）。**4 段目より
深いところは四角のまま**（記号を増やしても見分けが付かない）。"""

# 見出しの開閉三角の一辺（I-4）。ADR-0016 の左余白 12px に収める
FOLD_MARKER_SIZE = 8.0
FOLDED = "folded"
OPEN = "open"

_CODE_TYPES = frozenset(
    {
        BlockType.CODE_FENCE_OPEN,
        BlockType.CODE_FENCE_BODY,
        BlockType.CODE_FENCE_CLOSE,
        # 数式も同じ背景で表す（B-5）。中身が LaTeX なのは同じ性質
        BlockType.MATH_BODY,
        BlockType.MATH_DELIMITER,
    }
)

_TABLE_TYPES = frozenset({BlockType.TABLE_ROW, BlockType.TABLE_DELIMITER})


# spec §5.4 のフォーカスモード。現在段落以外をこの不透明度で覆う
FOCUS_DIM_ALPHA = 150


class DecorationKind(Enum):
    FOCUS_DIM = auto()
    TABLE_HEADER = auto()
    TABLE_RULE = auto()
    CODE_BACKGROUND = auto()
    INLINE_BAND = auto()
    """インラインコード / ハイライトの帯（ユーザー要望）。種類は `text`。

    QTextCharFormat の背景は文字の箱にぴったりで上の余白が作れない。
    帯をこちらで描いて、上に少しはみ出させる。"""

    FIGURE_BACKGROUND = auto()
    """組版される図（数式・Mermaid）の帯。コードより薄い色（ユーザー要望）。"""

    CODE_NAME = auto()
    """` ```python:aaa.py ` のファイル名（B-3）。"""

    BULLET = auto()
    """箇条書きの点（ユーザー要望 2026-08-22）。形は `text`（`disc` /
    `circle` / `square`）。**記号のままだと、書き手の癖で見た目が変わる。**"""

    QUOTE_BAR = auto()
    NOTE_BACKGROUND = auto()
    """`:::note` の背景の帯（ユーザー要望）。種類は `text` に入れる。"""

    NOTE_BAR = auto()
    """`:::note` の囲み（B-3）。種類は `Decoration.text` に入れる。"""

    RULE = auto()
    CHECKBOX = auto()
    IMAGE = auto()
    TABLE_TEXT = auto()
    """折り返した表のセルの中身（ADR-0017）。`text` に 1 行ぶんが入る。"""

    TABLE_TEXT_HEADER = auto()
    """折り返した表のヘッダ行のセル。太字・白抜きで描く。"""

    TABLE_STRIPE = auto()
    """表の本体の偶数行に敷く縞（ユーザー要望 2026-08-26）。"""

    FOLD_MARKER = auto()
    """見出しの開閉三角（I-4 / ADR-0019）。状態は `text`（open / folded）。"""

    MATH = auto()
    """数式ブロックの組版結果（I-1 / ADR-0020）。絵は `pixmap` に入る。"""

    MERMAID = auto()
    """Mermaid ブロックの図（I-1 / ADR-0021）。絵は `pixmap` に入る。"""


@dataclass(frozen=True, slots=True)
class Decoration:
    kind: DecorationKind
    rect: QRectF
    text: str = ""
    align: Alignment = Alignment.NONE
    """`TABLE_TEXT*` のときの寄せ（`---:` など。ADR-0029）。"""

    kinds: frozenset = frozenset()
    """`TABLE_TEXT*` のときのインライン記法の種類（`SpanType` の集合）。

    セルの中の `**強調**` や `` `コード` `` を描き分ける（2026-08-26）。
    """
    pixmap: object = None
    """`IMAGE` のときだけ入る。読み込みと縮小は `editor/image_cache.py`。"""


def focus_dim_rects(editor) -> list[Decoration]:
    """フォーカスモードで覆う矩形（spec §5.4）。

    キャレットのあるブロック以外を減光する。ハイライタ側でやると
    カーソル移動のたびに広範囲を掛け直すことになり R7 に反するので、
    **描画だけで表現する**。
    """
    current = editor.textCursor().blockNumber()
    rects: list[Decoration] = []
    block = editor.firstVisibleBlock()
    offset = editor.contentOffset()
    height = editor.viewport().height()

    while block.isValid():
        if not block.isVisible():
            block = block.next()
            continue
        geometry = editor.blockBoundingGeometry(block).translated(offset)
        if geometry.top() > height:
            break
        if block.blockNumber() != current:
            rects.append(Decoration(DecorationKind.FOCUS_DIM, QRectF(geometry)))
        block = block.next()
    return rects


def visible_decorations(editor) -> list[Decoration]:
    """画面に見えているブロックについて描画内容を組み立てる。

    可視ブロックだけを走査するのが要点（§6.6）。5,000 行の文書でも
    毎フレームの仕事量は画面に入る数十行分に収まる。
    """
    # ソースモード（Raw）では飾りを描かない。記号を見せるモードなのに
    # 罫線や縦線が残ると、`|` の上に罫線が、`[ ]` の上にチェック記号が重なる。
    # フォーカスモードの減光だけは残す（記法の飾りではなく読む助け）
    if editor.highlighter.source_mode:
        return focus_dim_rects(editor) if editor.focus_mode else []

    decorations: list[Decoration] = []
    block = editor.firstVisibleBlock()
    offset = editor.contentOffset()
    viewport_height = editor.viewport().height()

    entries: list[tuple[QTextBlock, object, QRectF]] = []
    while block.isValid():
        if not block.isVisible():
            # 折りたたみで隠れた行（I-4）。高さ 0 でも装飾を作ると、
            # 表の罫線が 1px の線のゴミとして残る
            block = block.next()
            continue
        geometry = editor.blockBoundingGeometry(block).translated(offset)
        if geometry.top() > viewport_height:
            break
        data = block.userData()
        if data is not None:
            entries.append((block, data.info, QRectF(geometry)))
            decorations.extend(_for_block(editor, block, data.info, geometry))
        image = _image_for(editor, block, geometry)
        if image is not None:
            decorations.append(image)
        block = block.next()

    decorations.extend(table_decorations(editor, entries))
    decorations.extend(figure_decorations(editor, entries))
    return decorations


def figure_decorations(editor, entries) -> list[Decoration]:
    """数式（ADR-0020）と Mermaid（ADR-0021）の絵。

    高さはハイライタが予約済み（画像と同じ ADR-0004 の手口）。中身は
    最初の本文行の `BlockData`（figure_latex / diagram）に載っている。
    キャレットがブロックに入っている間は載らない（生のソースが見えている）。
    """
    result: list[Decoration] = []
    for block, _info, rect in entries:
        data = block.userData()
        latex = getattr(data, "figure_latex", None)
        diagram = getattr(data, "diagram", None)
        if latex is not None:
            kind, pixmap = DecorationKind.MATH, editor.math_pixmap(latex)
        elif diagram is not None:
            kind, pixmap = DecorationKind.MERMAID, editor.mermaid_pixmap(diagram)
        else:
            continue
        if pixmap is None:
            continue
        width = pixmap.width() / pixmap.devicePixelRatio()
        height = pixmap.height() / pixmap.devicePixelRatio()
        left = editor.contentOffset().x() + editor.document().documentMargin()
        top = rect.top() + max(0.0, (rect.height() - height) / 2)
        result.append(Decoration(kind, QRectF(left, top, width, height), pixmap=pixmap))
    return result


def _image_for(editor, block, geometry) -> Decoration | None:
    """画像行に絵を置く。高さはハイライタが既に確保している。

    絵は本文の左端から描く。中央寄せにすると、文章の左端が揃わなくなる。
    """
    cache = getattr(editor, "image_cache", None)
    if cache is None:
        return None

    url = image_only_line(block.text())
    if url is None:
        return None

    pixmap = cache.pixmap(url, editor.image_width())
    if pixmap is None:
        return None

    left = editor.contentOffset().x() + editor.document().documentMargin()
    top = geometry.top() + (geometry.height() - pixmap.height()) / 2
    rect = QRectF(left, top, pixmap.width(), pixmap.height())
    return Decoration(kind=DecorationKind.IMAGE, rect=rect, pixmap=pixmap)


def cell_font(base: QFont, mono_family: str, *, header: bool, kinds: frozenset) -> QFont:
    """セルの断片を描くフォント。

    **測る側（`_CellMetrics`）と描く側（`paint_foreground`）で共有する。**
    別々に組むと、測った幅と描いた幅がずれて右端が欠けたり重なったりする
    （ヘッダの太字で実際に踏んだ轍）。
    """
    if SpanType.CODE in kinds:
        font = QFont(mono_family)
        font.setPointSizeF(base.pointSizeF())
    else:
        font = QFont(base)
    font.setBold(header or SpanType.STRONG in kinds or SpanType.STRONG_EM in kinds)
    font.setItalic(SpanType.EM in kinds or SpanType.STRONG_EM in kinds)
    font.setStrikeOut(SpanType.STRIKE in kinds)
    return font


class _CellMetrics:
    """断片の幅を、描くときと同じフォントで測る（種類ごとに使い回す）。"""

    def __init__(self, base: QFont, mono_family: str) -> None:
        self._base = base
        self._mono_family = mono_family
        self._cache: dict[tuple, QFontMetricsF] = {}

    def width(self, fragment, *, header: bool) -> float:
        key = (header, fragment.kinds)
        metrics = self._cache.get(key)
        if metrics is None:
            metrics = QFontMetricsF(
                cell_font(self._base, self._mono_family, header=header, kinds=fragment.kinds)
            )
            self._cache[key] = metrics
        return metrics.horizontalAdvance(fragment.text)


def table_decorations(editor, entries) -> list[Decoration]:
    """表の罫線とヘッダ背景（spec §5.2 の描画フック）。

    表は**常に描画側が組む**（ADR-0029。本文と同じフォントで描くため、
    列の位置は桁数ではなくピクセルで決める）。リビールは行単位で、
    キャレットの行だけ生の Markdown に戻り、その行のぶん線が途切れる。
    """
    result: list[Decoration] = []
    for run in _table_runs(entries):
        result.extend(_wrapped_table(editor, run))
    return result


def _wrapped_table(editor, run) -> list[Decoration]:
    """収まらない表をセル折り返しで描く（ADR-0017）。

    行の高さはハイライタが予約済み（画像と同じ ADR-0004 の手口）。ここでは
    `BlockData.wrapped` の中身を**本文と同じフォント**で描く（ADR-0029）。
    列の位置はピクセル（ハイライタが本文フォントで実測した列幅）。

    キャレットの行は生表示（`wrapped` が無い）なので、その行だけ描かず、
    罫線もその行のぶん途切れる。区切り行は薄い 1 行として線だけ引く。
    """
    metrics = QFontMetricsF(editor.font())
    spacing = metrics.lineSpacing()
    metrics_of = _CellMetrics(editor.font(), editor.mono_family())

    rows: list[tuple[QRectF, object, bool]] = []
    widths: tuple[float, ...] | None = None
    alignments: tuple = ()
    for block, info, rect in run:
        wrapped = getattr(block.userData(), "wrapped", None)
        rows.append((rect, wrapped, info.type is BlockType.TABLE_DELIMITER))
        if widths is None and wrapped is not None:
            widths = wrapped.col_widths
            alignments = wrapped.alignments
    if not widths:
        return []  # 全行が生表示（複数行選択など）。飾りも引かない

    left = editor.contentOffset().x() + editor.document().documentMargin()
    # 縦線の位置（px）。列ごとに 縦線 + 余白 + 中身 + 余白
    bounds = [0.0]
    for width in widths:
        bounds.append(bounds[-1] + RULE_HEIGHT + CELL_PAD + width + CELL_PAD)
    table_width = bounds[-1] + RULE_HEIGHT

    result: list[Decoration] = []
    has_delimiter = any(delimiter for _rect, _wrapped, delimiter in rows)
    below_delimiter = False
    body_count = 0
    for rect, wrapped, delimiter in rows:
        # 縞は**行の位置**で数える（ユーザー要望 2026-08-26）。リビール中の
        # 行も数に入れないと、キャレットの出入りで縞が引っ越してちらつく
        striped = False
        if below_delimiter and not delimiter:
            body_count += 1
            striped = body_count % 2 == 0
        if wrapped is None and not delimiter:
            continue  # キャレットの行。生の Markdown が見えている

        is_header = has_delimiter and not below_delimiter and not delimiter
        if delimiter:
            below_delimiter = True
        if is_header:
            result.append(
                Decoration(
                    DecorationKind.TABLE_HEADER,
                    QRectF(left, rect.top(), table_width, rect.height()),
                )
            )
        if striped:
            result.append(
                Decoration(
                    DecorationKind.TABLE_STRIPE,
                    QRectF(left, rect.top(), table_width, rect.height()),
                )
            )

        # 罫線。隣の行と 1px 重なるだけなので、行ごとに上下とも引いてよい
        for y in (rect.top(), rect.bottom()):
            result.append(
                Decoration(DecorationKind.TABLE_RULE, QRectF(left, y, table_width, RULE_HEIGHT))
            )
        for offset in bounds:
            result.append(
                Decoration(
                    DecorationKind.TABLE_RULE,
                    QRectF(left + offset, rect.top(), RULE_HEIGHT, rect.height()),
                )
            )
        if wrapped is None:
            continue

        kind = DecorationKind.TABLE_TEXT_HEADER if is_header else DecorationKind.TABLE_TEXT
        for column, cell_lines in enumerate(wrapped.cells[: len(widths)]):
            cell_left = left + bounds[column] + RULE_HEIGHT + CELL_PAD
            cell_width = widths[column]
            align = alignments[column] if column < len(alignments) else Alignment.NONE
            for line_index, fragments in enumerate(cell_lines):
                if not fragments:
                    continue
                y = rect.top() + WRAP_CELL_PADDING + line_index * spacing
                # 断片ごとに置き場を決める（2026-08-26）。寄せは drawText の
                # フラグではなく、ここで開始位置に折り込む。**測るフォントは
                # 描くフォントと同じ**（cell_font）なので、隙間も欠けも出ない
                advances = [metrics_of.width(f, header=is_header) for f in fragments]
                slack = cell_width - sum(advances)
                x = cell_left + max(
                    0.0,
                    {Alignment.RIGHT: slack, Alignment.CENTER: slack / 2}.get(align, 0.0),
                )
                for fragment, advance in zip(fragments, advances, strict=True):
                    result.append(
                        Decoration(
                            kind,
                            QRectF(x, y, advance, spacing),
                            fragment.text,
                            align,
                            kinds=fragment.kinds,
                        )
                    )
                    x += advance
    return result


def _table_runs(entries) -> list[list]:
    """連続する表の行をまとめる。"""
    runs: list[list] = []
    current: list = []
    for entry in entries:
        if entry[1].type in _TABLE_TYPES:
            current.append(entry)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return [run for run in runs if len(run) >= 2]


def _for_block(editor, block: QTextBlock, info, geometry: QRectF) -> list[Decoration]:
    result: list[Decoration] = []

    # 帯は紙の端まで伸ばさない（BAND_MARGIN。ユーザー要望 2026-08-26）
    banded = QRectF(geometry).adjusted(BAND_MARGIN, 0, -BAND_MARGIN, 0)
    if info.type in _CODE_TYPES:
        band = (
            DecorationKind.FIGURE_BACKGROUND
            if getattr(block.userData(), "figure_band", False)
            else DecorationKind.CODE_BACKGROUND
        )
        result.append(Decoration(band, QRectF(banded)))

    if info.type is BlockType.CODE_FENCE_OPEN and info.code_name:
        result.append(
            Decoration(
                DecorationKind.CODE_NAME,
                QRectF(banded).adjusted(CODE_NAME_INSET, 0, 0, 0),
                info.code_name,
            )
        )

    if info.note_kind:
        # 種類は `text` に載せる。色を決めるのは描く側（`paint`）で、
        # ここはテーマを知らないままでいられる。帯を先に、縦線をその上に
        result.append(Decoration(DecorationKind.NOTE_BACKGROUND, QRectF(banded), info.note_kind))
        result.append(
            Decoration(
                DecorationKind.NOTE_BAR,
                QRectF(
                    banded.left() + LEFT_INSET, geometry.top(), NOTE_BAR_WIDTH, geometry.height()
                ),
                info.note_kind,
            )
        )

    # 囲みの中では引用の縦線を右へ逃がす。同じ位置だと 2 本が重なって
    # どちらも読めなくなる。囲みの帯が内寄せなら縦線も一緒に寄る
    # 縦線は紙の縁に貼り付けず、帯と同じだけ内側から始める（2026-08-26）
    quote_inset = BAND_MARGIN + LEFT_INSET + (NOTE_BAR_WIDTH + LEFT_INSET if info.note_kind else 0)
    for depth in range(info.quote_depth):
        left = geometry.left() + quote_inset + depth * QUOTE_BAR_STEP
        result.append(
            Decoration(
                DecorationKind.QUOTE_BAR,
                QRectF(left, geometry.top(), QUOTE_BAR_WIDTH, geometry.height()),
            )
        )

    if info.type is BlockType.HORIZONTAL_RULE:
        middle = geometry.top() + geometry.height() / 2
        result.append(
            Decoration(
                DecorationKind.RULE,
                QRectF(geometry.left(), middle, geometry.width(), RULE_HEIGHT),
            )
        )

    if info.type is BlockType.TASK_LIST_ITEM and info.checked is not None:
        result.append(_checkbox(editor, block, info, geometry))

    if info.type is BlockType.BULLET_LIST_ITEM and _marker_hidden(block, info):
        result.append(_bullet(editor, block, info, geometry))

    if info.type is BlockType.HEADING:
        marker = _fold_marker(editor, block, geometry)
        if marker is not None:
            result.append(marker)

    data = block.userData()
    # 描画側が組んでいる表の行（wrapped あり）には帯を出さない
    # （ユーザー報告 2026-08-26）。行は 0.5pt に潰れて見えないのに帯だけが
    # 残り、左端に灰色の粒として出ていた。セルの中身は断片（ADR-0031）が
    # 自前の下地を持つ。キャレットの行は wrapped が無く、生の Markdown に
    # 本文と同じ帯が付く
    if getattr(data, "wrapped", None) is None:
        for span in getattr(data, "spans", []):
            name = _INLINE_BAND_NAMES.get(span.type)
            if name is None:
                continue
            for rect in _span_rects(block, geometry, span.content_start, span.content_end):
                result.append(Decoration(DecorationKind.INLINE_BAND, rect, name))

    return result


# 帯を敷くインライン装飾。数式（$x$）は等幅で見せているのでコードと同色
_INLINE_BAND_NAMES = {
    SpanType.CODE: "code",
    SpanType.MATH: "code",
    SpanType.HIGHLIGHT: "highlight",
}


def _span_rects(block: QTextBlock, geometry: QRectF, start: int, end: int) -> list[QRectF]:
    """文中の範囲 [start, end)（Python 単位）が占める矩形。折り返しは行ごと。

    帯は文字の実寸（ascent + descent）の上下に INLINE_BAND_PAD ずつ。
    """
    if end <= start:
        return []
    layout = block.layout()
    if layout is None or layout.lineCount() == 0:
        return []
    text = block.text()
    begin16 = py_to_utf16(text, start)
    end16 = py_to_utf16(text, end)
    first = layout.lineForTextPosition(begin16)
    last = layout.lineForTextPosition(max(begin16, end16 - 1))
    if not first.isValid() or not last.isValid():
        return []

    found: list[QRectF] = []
    for number in range(first.lineNumber(), last.lineNumber() + 1):
        line = layout.lineAt(number)
        line_begin = max(begin16, line.textStart())
        line_end = min(end16, line.textStart() + line.textLength())
        x1 = line.cursorToX(line_begin)
        x2 = line.cursorToX(line_end)
        x1 = float(x1[0]) if isinstance(x1, tuple) else float(x1)
        x2 = float(x2[0]) if isinstance(x2, tuple) else float(x2)
        if x2 <= x1:
            continue
        found.append(
            QRectF(
                geometry.left() + x1,
                geometry.top() + line.y() - INLINE_BAND_PAD,
                x2 - x1,
                line.ascent() + line.descent() + INLINE_BAND_PAD * 2,
            )
        )
    return found


def _fold_marker(editor, block: QTextBlock, geometry: QRectF) -> Decoration | None:
    """見出しの開閉三角（I-4）。畳める見出しにだけ出す。

    置き場は ADR-0016 で生まれた左余白（documentMargin 12px）。
    本文の開始位置は変えない。
    """
    line = block.blockNumber()
    folded = editor.is_folded(line)
    if not folded and not editor.foldable(line):
        return None
    height = QFontMetricsF(editor.font()).height()
    side = FOLD_MARKER_SIZE
    top = geometry.top() + max(0.0, (height - side)) / 2 + 2
    # 余白の**真ん中**に置く（ユーザー要望 2026-08-26）。縁（x=2）に
    # 貼り付けると、縁→三角→本文の左側だけ窮屈に見える
    inset = (editor.document().documentMargin() - side) / 2
    return Decoration(
        DecorationKind.FOLD_MARKER,
        QRectF(geometry.left() + inset, top, side, side),
        FOLDED if folded else OPEN,
    )


def checkbox_size(font: QFont) -> float:
    """箱の一辺。

    **行の高さではなく文字の高さから決める。** ハイライタは幅を確保する時点で
    行の高さを知らない（まだ組まれていない）。両方が同じ font metrics を見れば、
    確保した幅と描く箱が必ず揃う。
    """
    return QFontMetricsF(font).height() * CHECKBOX_SIZE_RATIO


def checkbox_rect(editor, block: QTextBlock, info, geometry: QRectF) -> QRectF | None:
    """チェックの印を描く矩形。クリック判定にも使う（E-1）。

    **描く側と当たり判定を同じ式にする。** 別々に持つと、片方を直したときに
    「見えている場所と押せる場所が違う」というずれ方をする。
    """
    if info.checked is None:
        return None
    return _checkbox(editor, block, info, geometry).rect


def _first_line(block: QTextBlock, geometry: QRectF) -> tuple[float, float]:
    """ブロックの **1 行目の文字の実寸**（上端と ascent + descent）。

    折り返した項目でブロック全体の高さから中央を出すと、点や箱が
    2 行目の横に浮く（ユーザー報告 2026-08-27）。記号は 1 行目の文字の
    横に付くもの。

    高さは行ボックス（line.height()）ではなく**文字の実寸**で返す。
    行間（leading）が下側に付くフォント（Hiragino Sans）では、行ボックスの
    中心は文字より下に見える（同日の続報。帯 INLINE_BAND と同じ理由）。
    レイアウトがまだ無ければブロック全体で代用する。
    """
    layout = block.layout()
    if layout is not None and layout.lineCount() > 0:
        line = layout.lineAt(0)
        return geometry.top() + line.y(), line.ascent() + line.descent()
    return geometry.top(), geometry.height()


def _checkbox(editor, block: QTextBlock, info, geometry: QRectF) -> Decoration:
    """潰した `[ ]` の位置に箱を描く（§6.4）。"""
    column = block.text().find("[", 0, info.marker_len)
    x = geometry.left() + _column_x(block, max(column, 0))
    line_top, line_height = _first_line(block, geometry)
    size = min(checkbox_size(editor.font()), line_height)
    top = line_top + (line_height - size) / 2
    return Decoration(
        DecorationKind.CHECKBOX,
        QRectF(x, top, size, size),
        CHECKED if info.checked else UNCHECKED,
    )


HIDDEN_POINT_SIZE = 0.5
"""潰した文字の大きさ（R4）。**消さずに残す**ので、キャレット位置と
ソースのオフセットは 1:1 のまま。ハイライタと同じ値を見る。"""

BULLET_MARKS = "-*+"
"""どれで書いても同じ点にする（`-` と `*` は CommonMark で同じ意味）。"""

BULLET_GAP_RATIO = 0.9
"""点と本文のあいだ。**接していると読みにくい**（箱と同じ考え方）。"""


def bullet_column(text: str, marker_len: int) -> int:
    """`- ` の記号そのものの位置。字下げのぶんは飛ばす。**無ければ -1。**

    描く側と潰す側で同じ式を使う（別々に持つと、片方を直したときに
    「潰した場所と描く場所が違う」というずれ方をする）。
    """
    for index, character in enumerate(text[:marker_len]):
        if character in BULLET_MARKS:
            return index
    return -1


def _marker_hidden(block: QTextBlock, info) -> bool:
    """`- ` が潰されているか（＝カーソルが行の外にあるか）。

    **カーソルを入れたら記号を返す**のがマーカー隠しの約束（§3.3）。
    描く側もそれに従わないと、生の `-` と点が並んで出る。
    """
    layout = block.layout()
    column = bullet_column(block.text(), info.marker_len)
    if layout is None or column < 0:
        return False
    for run in layout.formats():
        if run.start <= column < run.start + run.length:
            return run.format.fontPointSize() == HIDDEN_POINT_SIZE
    return False


def _bullet(editor, block: QTextBlock, info, geometry: QRectF) -> Decoration:
    """潰した `- ` の位置に点を描く（ユーザー要望 2026-08-22）。

    **深さで形を替える**（HTML と同じ ● ○ ■）。同じ形が続くと入れ子が
    読めない。4 段目より深いところは四角のまま（記号を増やしても
    見分けが付かない）。
    """
    column = max(bullet_column(block.text(), info.marker_len), 0)
    x = geometry.left() + _column_x(block, column)
    size = bullet_size(editor.font())
    line_top, line_height = _first_line(block, geometry)
    top = line_top + (line_height - size) / 2
    return Decoration(
        DecorationKind.BULLET,
        QRectF(x, top, size, size),
        # `level` は 1 始まり（いちばん外側が 1）
        BULLET_SHAPES[min(max(info.level - 1, 0), len(BULLET_SHAPES) - 1)],
    )


def bullet_size(font) -> float:
    """点の直径。**文字の大きさに連れて変わる**（箱と同じ考え方）。"""
    return QFontMetricsF(font).height() * BULLET_SIZE_RATIO


def _column_x(block: QTextBlock, column: int) -> float:
    """ブロック内の文字位置（Python 単位）の x 座標。レイアウトが無ければ 0。"""
    layout = block.layout()
    if layout is None or layout.lineCount() == 0:
        return 0.0
    # 呼び出し側は `block.text()`（Python 単位）で数えた位置を渡してくる。
    # レイアウトの API は UTF-16 単位なので、絵文字を含む行では変換が要る
    position = py_to_utf16(block.text(), column)
    line = layout.lineForTextPosition(position)
    if not line.isValid():
        return 0.0
    x = line.cursorToX(position)
    # PySide6 は (x, cursorPos) のタプルを返すことがある
    return float(x[0]) if isinstance(x, tuple) else float(x)


def _note_color(kind: str, theme: ThemeColors) -> str:
    """`:::note` の種類から色を引く（B-3）。"""
    # 知らない綴りは**灰色**。`info` の青にすると、間違えたことに
    # 気づく手掛かりが無くなる（ユーザー報告）
    return {
        "info": theme.note_info,
        "warn": theme.note_warn,
        "alert": theme.note_alert,
    }.get(kind, theme.muted_foreground)


def _note_background(kind: str, theme: ThemeColors) -> str:
    """`:::note` の背景色（ユーザー要望）。

    知らない綴りは**コードブロックと同じ無彩色**。種類の色を出すと、
    綴りの間違いに気づけない（縦線の灰色と同じ理屈）。
    """
    return {
        "info": theme.note_info_background,
        "warn": theme.note_warn_background,
        "alert": theme.note_alert_background,
    }.get(kind, theme.code_background)


_BLOCK_BAND_KINDS = frozenset(
    {
        DecorationKind.CODE_BACKGROUND,
        DecorationKind.FIGURE_BACKGROUND,
        DecorationKind.NOTE_BACKGROUND,
    }
)


def _band_color(decoration: Decoration, theme: ThemeColors) -> str:
    match decoration.kind:
        case DecorationKind.CODE_BACKGROUND:
            return theme.code_background
        case DecorationKind.FIGURE_BACKGROUND:
            return theme.figure_background
        case _:
            return _note_background(decoration.text, theme)


def _band_runs(decorations: list[Decoration], theme: ThemeColors) -> list[tuple[QRectF, str]]:
    """ブロックの帯を、続きの行どうしで 1 つの矩形にまとめる。

    ブロックごとに角を丸めると、行の境目がくびれて縞になる。装飾は
    ブロック順に並んでいるので、同じ種類・同じ色で上下が接していれば
    同じ帯として伸ばす。
    """
    runs: list[tuple[QRectF, str]] = []
    for decoration in decorations:
        if decoration.kind not in _BLOCK_BAND_KINDS:
            continue
        color = _band_color(decoration, theme)
        if runs:
            rect, last_color = runs[-1]
            if (
                last_color == color
                and abs(rect.bottom() - decoration.rect.top()) < 1.5
                and rect.left() == decoration.rect.left()
                and rect.width() == decoration.rect.width()
            ):
                rect.setBottom(decoration.rect.bottom())
                continue
        runs.append((QRectF(decoration.rect), color))
    return runs


def paint(painter: QPainter, decorations: list[Decoration], theme: ThemeColors) -> None:
    """組み立てた装飾を描く。背景に属するものだけを扱う。"""
    painter.save()
    painter.setPen(QColor("transparent"))

    # ブロックの帯（コード・図・注釈）は続きの行をまとめ、角を丸めて先に
    # 敷く（ユーザー要望 2026-08-26 / Qiita 風）。縦線や文字はこの上に乗る
    for rect, color in _band_runs(decorations, theme):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(rect, BAND_RADIUS, BAND_RADIUS)
        painter.restore()

    for decoration in decorations:
        match decoration.kind:
            case kind if kind in _BLOCK_BAND_KINDS:
                pass  # まとめて描いた
            case DecorationKind.INLINE_BAND:
                color = (
                    theme.highlight_background
                    if decoration.text == "highlight"
                    else theme.code_background
                )
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(decoration.rect, INLINE_BAND_RADIUS, INLINE_BAND_RADIUS)
                painter.restore()
            case DecorationKind.TABLE_HEADER:
                painter.fillRect(decoration.rect, QColor(theme.table_header_background))
            case DecorationKind.TABLE_STRIPE:
                painter.fillRect(decoration.rect, QColor(theme.table_stripe_background))
            case DecorationKind.TABLE_RULE:
                painter.fillRect(decoration.rect, QColor(theme.rule))
            case DecorationKind.QUOTE_BAR:
                painter.fillRect(decoration.rect, QColor(theme.quote_bar))
            case DecorationKind.NOTE_BAR:
                painter.fillRect(decoration.rect, QColor(_note_color(decoration.text, theme)))
            case DecorationKind.RULE:
                painter.fillRect(decoration.rect, QColor(theme.rule))
            case DecorationKind.CHECKBOX:
                pass  # 文字なので前景で描く
            case DecorationKind.FOCUS_DIM:
                pass  # 本文の上に重ねるので前景で描く
            case DecorationKind.FOLD_MARKER:
                _paint_fold_marker(painter, decoration, theme)
    painter.restore()


def _paint_fold_marker(painter: QPainter, decoration: Decoration, theme: ThemeColors) -> None:
    """開閉三角。開いていれば下向き、畳んでいれば右向き（慣習どおり）。"""
    box = decoration.rect
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("transparent"))
    painter.setBrush(QColor(theme.muted_foreground))
    if decoration.text == FOLDED:
        points = [box.topLeft(), QPointF(box.right(), box.center().y()), box.bottomLeft()]
    else:
        points = [box.topLeft(), box.topRight(), QPointF(box.center().x(), box.bottom())]
    painter.drawPolygon(points)
    painter.restore()


def _cell_band(kinds: frozenset, theme: ThemeColors) -> str | None:
    """断片の下地の色。本文の帯（INLINE_BAND）と同じ配色を使う。"""
    if SpanType.CODE in kinds:
        return theme.code_background
    if SpanType.HIGHLIGHT in kinds:
        return theme.highlight_background
    if SpanType.TAG in kinds:
        return theme.tag_background
    return None


def _cell_pen(kinds: frozenset, theme: ThemeColors, *, header: bool) -> str:
    """断片の文字色。下地に乗るものは本文と同じ専用色。"""
    if SpanType.CODE in kinds:
        return theme.code_foreground
    if SpanType.TAG in kinds:
        return theme.tag_foreground
    return theme.table_header_foreground if header else theme.foreground


def paint_foreground(
    painter: QPainter,
    decorations: list[Decoration],
    theme: ThemeColors,
    font: QFont,
    mono_family: str = "",
) -> None:
    """本文の上に重ねる要素（チェックボックス記号・画像）を描く。"""
    for decoration in decorations:
        if (
            decoration.kind in (DecorationKind.IMAGE, DecorationKind.MATH, DecorationKind.MERMAID)
            and decoration.pixmap is not None
        ):
            painter.drawPixmap(decoration.rect.topLeft(), decoration.pixmap)

    dim = QColor(theme.background)
    dim.setAlpha(FOCUS_DIM_ALPHA)
    for decoration in decorations:
        if decoration.kind is DecorationKind.FOCUS_DIM:
            painter.fillRect(decoration.rect, dim)

    names = [d for d in decorations if d.kind is DecorationKind.CODE_NAME]
    if names:
        # バッジで囲む（ユーザー要望 / Qiita 風）。コードの背景と違う色の
        # 板に白抜きで、名前が浮いて見える。板は行の上端に寄せ、下の
        # 隙間（CODE_NAME_GAP）はハイライタが行高で確保している
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        label = QFont(font)
        label.setPointSizeF(max(font.pointSizeF() * CODE_NAME_SCALE, 1.0))
        painter.setFont(label)
        metrics = QFontMetricsF(label)
        for decoration in names:
            badge = QRectF(
                decoration.rect.left(),
                decoration.rect.top() + 1,
                metrics.horizontalAdvance(decoration.text) + CODE_NAME_PAD_X * 2,
                metrics.height() + CODE_NAME_PAD_Y * 2,
            )
            painter.setPen(QColor("transparent"))
            painter.setBrush(QColor(theme.code_name_background))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QColor(theme.code_name_foreground))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), decoration.text)
        painter.restore()

    cells = [
        d
        for d in decorations
        if d.kind in (DecorationKind.TABLE_TEXT, DecorationKind.TABLE_TEXT_HEADER)
    ]
    if cells:
        painter.save()
        # **本文と同じフォントで描く**（ADR-0029）。ヘッダは太字・白抜き。
        # セルの中のインライン記法（2026-08-26）は断片ごとに描き分ける。
        # 置き場（寄せ込み）は `_wrapped_table` が決めてあるので、ここは
        # 左詰めで置くだけ。矩形は測った幅ぴったりなので clip しない
        # （合成斜体のはみ出しを削らない）
        mono = mono_family or font.family()
        flags = int(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextDontClip
        )
        for decoration in cells:
            header = decoration.kind is DecorationKind.TABLE_TEXT_HEADER
            body = cell_font(font, mono, header=header, kinds=decoration.kinds)
            band = _cell_band(decoration.kinds, theme)
            if band is not None:
                inset = max(
                    0.0, (decoration.rect.height() - QFontMetricsF(body).height()) / 2 - 1.0
                )
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QColor("transparent"))
                painter.setBrush(QColor(band))
                painter.drawRoundedRect(
                    decoration.rect.adjusted(0.0, inset, 0.0, -inset),
                    INLINE_BAND_RADIUS,
                    INLINE_BAND_RADIUS,
                )
                painter.restore()
            painter.setFont(body)
            painter.setPen(QColor(_cell_pen(decoration.kinds, theme, header=header)))
            painter.drawText(decoration.rect, flags, decoration.text)
        painter.restore()

    marks = [d for d in decorations if d.kind in (DecorationKind.CHECKBOX, DecorationKind.BULLET)]
    if not marks:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for decoration in marks:
        if decoration.kind is DecorationKind.BULLET:
            _paint_bullet(painter, decoration, theme)
        else:
            _paint_checkbox(painter, decoration, theme)
    painter.restore()


def _paint_bullet(painter: QPainter, decoration: Decoration, theme: ThemeColors) -> None:
    """箇条書きの点。**深さで形を替える**（● ○ ■）。"""
    box = decoration.rect
    color = QColor(theme.foreground)
    painter.setPen(QPen(color, BULLET_STROKE))
    if decoration.text == "circle":
        painter.setBrush(QColor("transparent"))
        painter.drawEllipse(box.adjusted(0.5, 0.5, -0.5, -0.5))
        return
    painter.setBrush(color)
    if decoration.text == "square":
        # 塗った四角は同じ大きさだと丸より重く見える。少し詰める
        inset = box.width() * BULLET_SQUARE_INSET
        painter.drawRect(box.adjusted(inset, inset, -inset, -inset))
        return
    painter.drawEllipse(box)


def _paint_checkbox(painter: QPainter, decoration: Decoration, theme: ThemeColors) -> None:
    """枠と、チェック済みならその中のレ点を描く。

    **状態で外形を変えない。** 変えると行ごとに箱の大きさが違って見える
    （フォントの記号で描いていたときの不具合そのもの）。
    """
    box = decoration.rect
    pen = QPen(QColor(theme.muted_foreground))
    pen.setWidthF(CHECKBOX_STROKE)
    painter.setPen(pen)
    painter.setBrush(QColor("transparent"))
    radius = box.width() * 0.2
    painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    if decoration.text != CHECKED:
        return
    mark = QPen(QColor(theme.accent))
    mark.setWidthF(CHECKBOX_STROKE + 0.4)
    mark.setCapStyle(Qt.PenCapStyle.RoundCap)
    mark.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(mark)
    painter.drawPolyline(
        [
            QPointF(box.left() + box.width() * 0.24, box.top() + box.height() * 0.52),
            QPointF(box.left() + box.width() * 0.43, box.top() + box.height() * 0.72),
            QPointF(box.left() + box.width() * 0.77, box.top() + box.height() * 0.28),
        ]
    )
