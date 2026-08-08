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

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QTextBlock

from hitofude.core.models import BlockType
from hitofude.theme import ThemeColors

# spec §5.2
QUOTE_BAR_WIDTH = 3
QUOTE_BAR_STEP = 10
CODE_ACCENT_WIDTH = 4
RULE_HEIGHT = 1
LEFT_INSET = 2

UNCHECKED_GLYPH = "☐"
CHECKED_GLYPH = "☑"

_CODE_TYPES = frozenset(
    {BlockType.CODE_FENCE_OPEN, BlockType.CODE_FENCE_BODY, BlockType.CODE_FENCE_CLOSE}
)


# spec §5.4 のフォーカスモード。現在段落以外をこの不透明度で覆う
FOCUS_DIM_ALPHA = 150


class DecorationKind(Enum):
    FOCUS_DIM = auto()
    CODE_BACKGROUND = auto()
    CODE_ACCENT = auto()
    QUOTE_BAR = auto()
    RULE = auto()
    CHECKBOX = auto()


@dataclass(frozen=True, slots=True)
class Decoration:
    kind: DecorationKind
    rect: QRectF
    text: str = ""


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
    decorations: list[Decoration] = []
    block = editor.firstVisibleBlock()
    offset = editor.contentOffset()
    viewport_height = editor.viewport().height()

    while block.isValid():
        geometry = editor.blockBoundingGeometry(block).translated(offset)
        if geometry.top() > viewport_height:
            break
        data = block.userData()
        if data is not None:
            decorations.extend(_for_block(editor, block, data.info, geometry))
        block = block.next()

    return decorations


def _for_block(editor, block: QTextBlock, info, geometry: QRectF) -> list[Decoration]:
    result: list[Decoration] = []

    if info.type in _CODE_TYPES:
        result.append(Decoration(DecorationKind.CODE_BACKGROUND, QRectF(geometry)))
        result.append(
            Decoration(
                DecorationKind.CODE_ACCENT,
                QRectF(geometry.left(), geometry.top(), CODE_ACCENT_WIDTH, geometry.height()),
            )
        )

    for depth in range(info.quote_depth):
        left = geometry.left() + LEFT_INSET + depth * QUOTE_BAR_STEP
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

    return result


def _checkbox(editor, block: QTextBlock, info, geometry: QRectF) -> Decoration:
    """潰した `[ ]` の位置に記号を重ねる（§6.4）。"""
    column = block.text().find("[", 0, info.marker_len)
    x = geometry.left() + _column_x(block, max(column, 0))
    glyph = CHECKED_GLYPH if info.checked else UNCHECKED_GLYPH
    return Decoration(
        DecorationKind.CHECKBOX,
        QRectF(x, geometry.top(), geometry.height(), geometry.height()),
        glyph,
    )


def _column_x(block: QTextBlock, column: int) -> float:
    """ブロック内の文字位置の x 座標。レイアウトが無ければ 0。"""
    layout = block.layout()
    if layout is None or layout.lineCount() == 0:
        return 0.0
    line = layout.lineForTextPosition(column)
    if not line.isValid():
        return 0.0
    x = line.cursorToX(column)
    # PySide6 は (x, cursorPos) のタプルを返すことがある
    return float(x[0]) if isinstance(x, tuple) else float(x)


def paint(painter: QPainter, decorations: list[Decoration], theme: ThemeColors) -> None:
    """組み立てた装飾を描く。背景に属するものだけを扱う。"""
    painter.save()
    painter.setPen(QColor("transparent"))
    for decoration in decorations:
        match decoration.kind:
            case DecorationKind.CODE_BACKGROUND:
                painter.fillRect(decoration.rect, QColor(theme.code_background))
            case DecorationKind.CODE_ACCENT:
                painter.fillRect(decoration.rect, QColor(theme.accent))
            case DecorationKind.QUOTE_BAR:
                painter.fillRect(decoration.rect, QColor(theme.quote_bar))
            case DecorationKind.RULE:
                painter.fillRect(decoration.rect, QColor(theme.rule))
            case DecorationKind.CHECKBOX:
                pass  # 文字なので前景で描く
            case DecorationKind.FOCUS_DIM:
                pass  # 本文の上に重ねるので前景で描く
    painter.restore()


def paint_foreground(
    painter: QPainter, decorations: list[Decoration], theme: ThemeColors, font: QFont
) -> None:
    """本文の上に重ねる要素（チェックボックス記号）を描く。"""
    dim = QColor(theme.background)
    dim.setAlpha(FOCUS_DIM_ALPHA)
    for decoration in decorations:
        if decoration.kind is DecorationKind.FOCUS_DIM:
            painter.fillRect(decoration.rect, dim)

    boxes = [d for d in decorations if d.kind is DecorationKind.CHECKBOX]
    if not boxes:
        return
    painter.save()
    painter.setFont(font)
    painter.setPen(QColor(theme.foreground))
    for decoration in boxes:
        painter.drawText(decoration.rect, 0, decoration.text)
    painter.restore()
