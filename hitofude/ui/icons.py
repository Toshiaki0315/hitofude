"""サイドバーのアイコンを線で描く。

**絵文字も画像ファイルも使わない。** 絵文字は色を指定できずテーマから浮き、
画像ファイルはライト / ダーク × 解像度のぶんだけ用意することになる。
線で描けば色を渡すだけで済み、`scripts/make_icon.py`（アプリアイコン）と
同じやり方に揃う。

描くのは輪郭だけで塗り潰さない。文字と同じ太さに見えるほうが、
一覧として落ち着く。
"""

from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap

# 描画は倍率をかけた大きさで行い、表示側で縮小する。線が滑らかになる
CANVAS = 64
STROKE = 5.0
_CACHE: dict[tuple["Glyph", str], QIcon] = {}


class Glyph(Enum):
    ALL = auto()
    """すべて。重なった紙。"""

    PINNED = auto()
    """お気に入り。星。"""

    TRASH = auto()
    """ゴミ箱。"""

    TAG = auto()
    """タグ。"""


def glyph_icon(glyph: Glyph, color: str) -> QIcon:
    """線で描いたアイコン。同じ指定なら描き直さない。"""
    key = (glyph, color)
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
    painter.setBrush(Qt.BrushStyle.NoBrush)

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


_DRAW = {
    Glyph.ALL: _draw_all,
    Glyph.PINNED: _draw_pinned,
    Glyph.TRASH: _draw_trash,
    Glyph.TAG: _draw_tag,
}
