"""サイドバーのアイコンを線で描く。あわせて、上部のバーの倍率を置く。

**絵文字も画像ファイルも使わない。** 絵文字は色を指定できずテーマから浮き、
画像ファイルはライト / ダーク × 解像度のぶんだけ用意することになる。
線で描けば色を渡すだけで済み、`scripts/make_icon.py`（アプリアイコン）と
同じやり方に揃う。

既定は輪郭だけで塗り潰さない。文字と同じ太さに見えるほうが、一覧として
落ち着く。小さく出す印（一覧のピン留め）だけ `filled=True` で中まで塗る。
輪郭だけでは形が読めないため。
"""

from enum import Enum, auto
from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

# 描画は倍率をかけた大きさで行い、表示側で縮小する。線が滑らかになる
# 上部のバー（一覧の並び順・新規、本文の書式ツールバー）の倍率。
# **1 か所に持つ。** 各ファイルに数字を散らすと、直すときに片方だけ残る。
# 1.0 が元の大きさ（ユーザー要望で 1.5 倍を試し、1.3 に落ち着いた）
TOOLBAR_SCALE = 1.3

CANVAS = 64
STROKE = 5.0
_CACHE: dict[tuple["Glyph", str, bool], QIcon] = {}


class Glyph(Enum):
    ALL = auto()
    """すべて。重なった紙。"""

    PINNED = auto()
    """お気に入り。星。"""

    TRASH = auto()
    """ゴミ箱。"""

    TAG = auto()
    """タグ。"""

    # ------------------------------------------------- 一覧の上のボタン

    SORT = auto()
    """並び順。上下の矢印。"""

    NEW_NOTE = auto()
    """新規ノート。＋。"""

    GEAR = auto()
    """メニュー。歯車。"""

    # ------------------------------------------- 書式ツールバー（B-1）

    BOLD = auto()
    """太字。"""

    ITALIC = auto()
    """斜体。"""

    STRIKE = auto()
    """打ち消し。"""

    CODE = auto()
    """コード。山括弧。"""

    MARKER = auto()
    """マーカー。引いた線。"""

    LINK = auto()
    """リンク。鎖の輪。"""

    HEADING = auto()
    """見出し。"""

    BULLET = auto()
    """箇条書き。点と行。"""

    ORDERED = auto()
    """番号付き。数字と行。"""

    CHECKBOX = auto()
    """チェックボックス。"""

    QUOTE = auto()
    """引用。縦線と行。本文での見え方（`painter_overlay`）に合わせる。"""


def glyph_icon(glyph: Glyph, color: str, *, filled: bool = False) -> QIcon:
    """線で描いたアイコン。同じ指定なら描き直さない。

    `filled` は中まで塗る。小さく出すときは輪郭だけだと形が読めない
    （一覧のピン留めの印がそれ）。
    """
    key = (glyph, color, filled)
    found = _CACHE.get(key)
    if found is not None:
        return found

    pixmap = QPixmap(CANVAS, CANVAS)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(STROKE)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(color)) if filled else Qt.BrushStyle.NoBrush)

    _DRAW[glyph](painter)
    painter.end()

    icon = QIcon(pixmap)
    _CACHE[key] = icon
    return icon


def _draw_all(painter: QPainter) -> None:
    """重なった紙。"""
    painter.drawRect(QRectF(10, 18, 32, 38))
    painter.drawPolyline(
        [QPointF(22, 10), QPointF(54, 10), QPointF(54, 46)]  # 後ろの 1 枚
    )


def _draw_pinned(painter: QPainter) -> None:
    """星。5 つの頂点を外周と内周で交互に結ぶ。"""
    import math

    center = QPointF(32, 33)
    outer, inner = 22.0, 9.0
    path = QPainterPath()
    for step in range(10):
        radius = outer if step % 2 == 0 else inner
        angle = math.radians(-90 + step * 36)
        point = QPointF(
            center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle)
        )
        if step == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_trash(painter: QPainter) -> None:
    """ゴミ箱。ふたと本体と縦線 2 本。"""
    painter.drawLine(QPointF(11, 18), QPointF(53, 18))
    painter.drawPolyline([QPointF(26, 18), QPointF(26, 11), QPointF(38, 11), QPointF(38, 18)])
    painter.drawPolyline([QPointF(16, 18), QPointF(19, 55), QPointF(45, 55), QPointF(48, 18)])
    painter.drawLine(QPointF(27, 27), QPointF(28, 46))
    painter.drawLine(QPointF(37, 27), QPointF(36, 46))


def _draw_tag(painter: QPainter) -> None:
    """タグ。角を落とした札と穴。"""
    path = QPainterPath()
    path.moveTo(QPointF(33, 10))
    path.lineTo(QPointF(54, 31))
    path.lineTo(QPointF(31, 54))
    path.lineTo(QPointF(10, 33))
    path.lineTo(QPointF(10, 10))
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawEllipse(QPointF(21, 21), 4.5, 4.5)


# ------------------------------------------------- 書式ツールバー（B-1）
#
# 太字・斜体・打ち消し・見出しは**字そのもの**を描く。B / I / S / H は
# どの編集ソフトでも同じ絵で、線で描いた抽象記号より早く読める。
# 残りは線で描く。引用は本文での見え方（`painter_overlay` の縦線）に揃える。

_LETTER_SIZE = 44
_LINE_LEFT, _LINE_RIGHT = 24.0, 54.0
_LINE_ROWS = (17.0, 32.0, 47.0)


def _letter(painter: QPainter, char: str, *, bold: bool = False, italic: bool = False) -> None:
    font = painter.font()
    font.setPixelSize(_LETTER_SIZE)
    font.setBold(bold)
    font.setItalic(italic)
    painter.setFont(font)
    # 字は塗りではなくペンの色で出る。輪郭用の太いペンは字には効かない
    painter.drawText(QRectF(0, 0, CANVAS, CANVAS), Qt.AlignmentFlag.AlignCenter, char)


def _rows(painter: QPainter, rows=_LINE_ROWS) -> None:
    """本文を表す横線。リスト系のアイコンで共通に使う。"""
    for y in rows:
        painter.drawLine(QPointF(_LINE_LEFT, y), QPointF(_LINE_RIGHT, y))


def _draw_bold(painter: QPainter) -> None:
    _letter(painter, "B", bold=True)


def _draw_italic(painter: QPainter) -> None:
    """傾いた I。**字を斜体にしただけでは斜線にしか見えない**（実際に描いて確認）。
    上下の横棒を足すと I だと読める。"""
    painter.drawLine(QPointF(26, 14), QPointF(48, 14))
    painter.drawLine(QPointF(16, 50), QPointF(38, 50))
    painter.drawLine(QPointF(38, 14), QPointF(26, 50))


def _draw_strike(painter: QPainter) -> None:
    _letter(painter, "S")
    painter.drawLine(QPointF(12, 32), QPointF(52, 32))


def _draw_code(painter: QPainter) -> None:
    """山括弧。"""
    painter.drawPolyline([QPointF(24, 18), QPointF(10, 32), QPointF(24, 46)])
    painter.drawPolyline([QPointF(40, 18), QPointF(54, 32), QPointF(40, 46)])


def _draw_marker(painter: QPainter) -> None:
    """マーカーペンと引いた線。

    **横線だけで表すと箇条書き・引用と見分けが付かない**（実際に並べて確認）。
    ペンの形を足して区別する。
    """
    pen = painter.pen()
    painter.setBrush(Qt.BrushStyle.NoBrush)

    body = QPainterPath()  # 傾けたペン先
    body.moveTo(QPointF(40, 8))
    body.lineTo(QPointF(56, 24))
    body.lineTo(QPointF(28, 44))
    body.lineTo(QPointF(16, 44))
    body.lineTo(QPointF(16, 32))
    body.closeSubpath()
    painter.drawPath(body)

    stroke = QPen(pen)  # 引いた跡
    stroke.setWidthF(9.0)
    painter.setPen(stroke)
    painter.drawLine(QPointF(14, 55), QPointF(50, 55))
    painter.setPen(pen)


def _draw_link(painter: QPainter) -> None:
    """鎖の輪 2 つ。傾けた角丸で表す。"""
    painter.save()
    painter.translate(32, 32)
    painter.rotate(-40)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(-26, -11, 30, 22), 11, 11)
    painter.drawRoundedRect(QRectF(-4, -11, 30, 22), 11, 11)
    painter.restore()


def _draw_heading(painter: QPainter) -> None:
    _letter(painter, "H", bold=True)


def _draw_bullet(painter: QPainter) -> None:
    """点と行。"""
    _rows(painter)
    painter.setBrush(QBrush(painter.pen().color()))
    for y in _LINE_ROWS:
        painter.drawEllipse(QPointF(12, y), 3.5, 3.5)


def _draw_ordered(painter: QPainter) -> None:
    """数字と行。"""
    _rows(painter)
    font = painter.font()
    font.setPixelSize(17)
    painter.setFont(font)
    for index, y in enumerate(_LINE_ROWS, start=1):
        painter.drawText(
            QRectF(0, y - 11, 20, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            str(index),
        )


def _draw_checkbox(painter: QPainter) -> None:
    """四角とチェック。"""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(11, 11, 42, 42), 8, 8)
    painter.drawPolyline([QPointF(20, 33), QPointF(29, 42), QPointF(45, 22)])


def _draw_quote(painter: QPainter) -> None:
    """縦線と行。本文での引用の見え方に合わせる。"""
    pen = painter.pen()
    bar = QPen(pen)
    bar.setWidthF(7.0)
    painter.setPen(bar)
    painter.drawLine(QPointF(13, 15), QPointF(13, 49))
    painter.setPen(pen)
    _rows(painter, rows=(20.0, 32.0, 44.0))


def _draw_sort(painter: QPainter) -> None:
    """並び順。**上向きと下向きの矢印を並べる。**

    文字の `⇅` は書体で形が変わるうえ、ポップアップ用の三角と近づくと
    重なった（ユーザー報告）。線で描けば大きさも間隔もこちらで決まる。
    """
    for x, tip, tail in ((24.0, 14.0, 50.0), (40.0, 50.0, 14.0)):
        painter.drawLine(QPointF(x, tail), QPointF(x, tip))
        head = 9.0 if tip < tail else -9.0
        painter.drawPolyline(
            [QPointF(x - 7, tip + head), QPointF(x, tip), QPointF(x + 7, tip + head)]
        )


def _draw_new_note(painter: QPainter) -> None:
    """新規。十字。"""
    painter.drawLine(QPointF(32, 14), QPointF(32, 50))
    painter.drawLine(QPointF(14, 32), QPointF(50, 32))


def _draw_gear(painter: QPainter) -> None:
    """メニュー。歯車。輪 + 8 枚の歯 + 軸穴。

    歯は線 1 本ではなく**太いペンの短い線**で描く（ユーザー要望）。
    細い線だとトゲに見えて歯車に読めない。丸キャップなので先が丸い
    歯になり、輪の線とのつながりも滑らか。
    """
    tooth = QPen(painter.pen())
    tooth.setWidthF(STROKE * 1.6)
    rim = painter.pen()
    painter.setPen(tooth)
    for step in range(8):
        angle = radians(step * 45)
        x, y = cos(angle), sin(angle)
        painter.drawLine(QPointF(32 + 13 * x, 32 + 13 * y), QPointF(32 + 18 * x, 32 + 18 * y))
    painter.setPen(rim)
    painter.drawEllipse(QRectF(21, 21, 22, 22))
    painter.drawEllipse(QRectF(28, 28, 8, 8))


_DRAW = {
    Glyph.SORT: _draw_sort,
    Glyph.NEW_NOTE: _draw_new_note,
    Glyph.GEAR: _draw_gear,
    Glyph.ALL: _draw_all,
    Glyph.PINNED: _draw_pinned,
    Glyph.TRASH: _draw_trash,
    Glyph.TAG: _draw_tag,
    Glyph.BOLD: _draw_bold,
    Glyph.ITALIC: _draw_italic,
    Glyph.STRIKE: _draw_strike,
    Glyph.CODE: _draw_code,
    Glyph.MARKER: _draw_marker,
    Glyph.LINK: _draw_link,
    Glyph.HEADING: _draw_heading,
    Glyph.BULLET: _draw_bullet,
    Glyph.ORDERED: _draw_ordered,
    Glyph.CHECKBOX: _draw_checkbox,
    Glyph.QUOTE: _draw_quote,
}
