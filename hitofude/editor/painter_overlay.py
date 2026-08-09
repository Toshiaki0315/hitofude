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
from hitofude.core.models import BlockType
from hitofude.theme import ThemeColors

# spec §5.2
QUOTE_BAR_WIDTH = 3
QUOTE_BAR_STEP = 10
# `:::note` の縦線（B-3）。引用より太くして、引用と区別が付くようにする
NOTE_BAR_WIDTH = 4
# ファイル名を書き出す位置（`paintEvent` で描く）。左端に寄せすぎると
# 背景の角に食い込む
CODE_NAME_INSET = 8.0
# ファイル名の大きさ（本文に対する比）。見出しとして読めて、かつ主張しない
CODE_NAME_SCALE = 0.85
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
    TABLE_BACKGROUND = auto()
    TABLE_HEADER = auto()
    TABLE_RULE = auto()
    CODE_BACKGROUND = auto()
    CODE_NAME = auto()
    """` ```python:aaa.py ` のファイル名（B-3）。"""

    QUOTE_BAR = auto()
    NOTE_BAR = auto()
    """`:::note` の囲み（B-3）。種類は `Decoration.text` に入れる。"""

    RULE = auto()
    CHECKBOX = auto()
    IMAGE = auto()


@dataclass(frozen=True, slots=True)
class Decoration:
    kind: DecorationKind
    rect: QRectF
    text: str = ""
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

    entries: list[tuple[QTextBlock, object, QRectF]] = []
    while block.isValid():
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
    return decorations


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


def table_decorations(editor, entries) -> list[Decoration]:
    """表の罫線とヘッダ背景（spec §5.2 の描画フック）。

    **キャレットが表の中にある間は線を引かない。** 編集中はソースがまだ
    揃っておらず、揃った前提で引いた線が本文とずれるため。行を離れると
    自動整形が走り、そこで線が現れる（マーカーのリビールと同じ考え方）。
    """
    caret = editor.textCursor().blockNumber()
    result: list[Decoration] = []

    for run in _table_runs(entries):
        numbers = [block.blockNumber() for block, _info, _rect in run]
        if caret in numbers:
            continue

        columns = _pipe_positions(run[0][0], run[0][2])
        if len(columns) < 2:
            continue  # 縦線が引けない＝表として描けない

        top = run[0][2].top()
        bottom = run[-1][2].bottom()
        # **ブロックの矩形は表示領域の全幅**なので、そのまま使うと罫線が
        # 画面の端まで伸びる。表の実際の幅（左端と右端の縦線）に収める
        left = columns[0]
        right = columns[-1] + RULE_HEIGHT

        delimiter = next(
            (i for i, (_b, info, _r) in enumerate(run) if info.type is BlockType.TABLE_DELIMITER),
            None,
        )
        if delimiter is not None:
            header = QRectF(left, top, right - left, run[delimiter][2].top() - top)
            result.append(Decoration(DecorationKind.TABLE_HEADER, header))

        for x in columns:
            result.append(
                Decoration(DecorationKind.TABLE_RULE, QRectF(x, top, RULE_HEIGHT, bottom - top))
            )

        for _block, _info, rect in run:
            result.append(
                Decoration(
                    DecorationKind.TABLE_RULE, QRectF(left, rect.top(), right - left, RULE_HEIGHT)
                )
            )
        result.append(
            Decoration(DecorationKind.TABLE_RULE, QRectF(left, bottom, right - left, RULE_HEIGHT))
        )

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


def _pipe_positions(block: QTextBlock, geometry: QRectF) -> list[float]:
    """行の中の `|` の x 座標。縦線を引く位置になる。"""
    return [
        geometry.left() + _column_x(block, index)
        for index, character in enumerate(block.text())
        if character == "|"
    ]


def _for_block(editor, block: QTextBlock, info, geometry: QRectF) -> list[Decoration]:
    result: list[Decoration] = []

    if info.type in _CODE_TYPES:
        result.append(Decoration(DecorationKind.CODE_BACKGROUND, QRectF(geometry)))

    if info.type is BlockType.CODE_FENCE_OPEN and info.code_name:
        result.append(
            Decoration(
                DecorationKind.CODE_NAME,
                QRectF(geometry).adjusted(CODE_NAME_INSET, 0, 0, 0),
                info.code_name,
            )
        )

    if info.note_kind:
        # 種類は `text` に載せる。色を決めるのは描く側（`paint`）で、
        # ここはテーマを知らないままでいられる
        result.append(
            Decoration(
                DecorationKind.NOTE_BAR,
                QRectF(
                    geometry.left() + LEFT_INSET, geometry.top(), NOTE_BAR_WIDTH, geometry.height()
                ),
                info.note_kind,
            )
        )

    # 囲みの中では引用の縦線を右へ逃がす。同じ位置だと 2 本が重なって
    # どちらも読めなくなる
    quote_inset = LEFT_INSET + (NOTE_BAR_WIDTH + LEFT_INSET if info.note_kind else 0)
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

    return result


def checkbox_size(font: QFont) -> float:
    """箱の一辺。

    **行の高さではなく文字の高さから決める。** ハイライタは幅を確保する時点で
    行の高さを知らない（まだ組まれていない）。両方が同じ font metrics を見れば、
    確保した幅と描く箱が必ず揃う。
    """
    return QFontMetricsF(font).height() * CHECKBOX_SIZE_RATIO


def _checkbox(editor, block: QTextBlock, info, geometry: QRectF) -> Decoration:
    """潰した `[ ]` の位置に箱を描く（§6.4）。"""
    column = block.text().find("[", 0, info.marker_len)
    x = geometry.left() + _column_x(block, max(column, 0))
    size = min(checkbox_size(editor.font()), geometry.height())
    top = geometry.top() + (geometry.height() - size) / 2
    return Decoration(
        DecorationKind.CHECKBOX,
        QRectF(x, top, size, size),
        CHECKED if info.checked else UNCHECKED,
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


def _note_color(kind: str, theme: ThemeColors) -> str:
    """`:::note` の種類から色を引く（B-3）。"""
    # 知らない綴りは**灰色**。`info` の青にすると、間違えたことに
    # 気づく手掛かりが無くなる（ユーザー報告）
    return {
        "info": theme.note_info,
        "warn": theme.note_warn,
        "alert": theme.note_alert,
    }.get(kind, theme.muted_foreground)


def paint(painter: QPainter, decorations: list[Decoration], theme: ThemeColors) -> None:
    """組み立てた装飾を描く。背景に属するものだけを扱う。"""
    painter.save()
    painter.setPen(QColor("transparent"))
    for decoration in decorations:
        match decoration.kind:
            case DecorationKind.CODE_BACKGROUND:
                painter.fillRect(decoration.rect, QColor(theme.code_background))
            case DecorationKind.TABLE_HEADER:
                painter.fillRect(decoration.rect, QColor(theme.code_background))
            case DecorationKind.TABLE_RULE:
                painter.fillRect(decoration.rect, QColor(theme.rule))
            case DecorationKind.TABLE_BACKGROUND:
                painter.fillRect(decoration.rect, QColor(theme.code_background))
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
    painter.restore()


def paint_foreground(
    painter: QPainter, decorations: list[Decoration], theme: ThemeColors, font: QFont
) -> None:
    """本文の上に重ねる要素（チェックボックス記号・画像）を描く。"""
    for decoration in decorations:
        if decoration.kind is DecorationKind.IMAGE and decoration.pixmap is not None:
            painter.drawPixmap(decoration.rect.topLeft(), decoration.pixmap)

    dim = QColor(theme.background)
    dim.setAlpha(FOCUS_DIM_ALPHA)
    for decoration in decorations:
        if decoration.kind is DecorationKind.FOCUS_DIM:
            painter.fillRect(decoration.rect, dim)

    names = [d for d in decorations if d.kind is DecorationKind.CODE_NAME]
    if names:
        painter.save()
        label = QFont(font)
        label.setPointSizeF(max(font.pointSizeF() * CODE_NAME_SCALE, 1.0))
        painter.setFont(label)
        painter.setPen(QColor(theme.muted_foreground))
        for decoration in names:
            painter.drawText(
                decoration.rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                decoration.text,
            )
        painter.restore()

    boxes = [d for d in decorations if d.kind is DecorationKind.CHECKBOX]
    if not boxes:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for decoration in boxes:
        _paint_checkbox(painter, decoration, theme)
    painter.restore()


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
