"""数式の描画（I-1 / ADR-0020）。

LaTeX → SVG は **ziamath**（純 Python・約 3MB）。検討時は matplotlib
（+60MB）が必須と見ていたが、TeX 品質のグリフがこの大きさで出る。
SVG → QPixmap は Qt 標準の QtSvg。1 式 6ms（初回）/ 1ms（フォントが
温まったあと）なので、変更ブロックだけの再ハイライト（R7）に収まる。

描き直さないよう、指定（式・大きさ・色・幅）ごとに絵を覚える。
"""

import logging
from collections import OrderedDict

import ziamath
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)

# QtSvg は SVG Tiny 相当で、SVG2 の <symbol>/<use> を描けない
# （枠線だけ出て文字が消える。実測）。パスを直接出させる
ziamath.config.svg2 = False

# 覚えておく絵の数。1 ノートに載る数式はせいぜい数十
_CACHE_SIZE = 64

# Retina。等倍で描くと文字の縁がにじむ
_RATIO = 2.0

# 本文の文字に対する式の大きさ。同じ大きさだと添字が潰れる
MATH_POINT_SCALE = 1.4


class MathCache:
    """式ごとの描画結果。壊れた式は None を覚える（毎回試さない）。"""

    def __init__(self) -> None:
        self._pixmaps: OrderedDict[tuple[str, float, str, int], QPixmap | None] = OrderedDict()

    def pixmap(
        self, latex: str, *, point_size: float, color: str, max_width: int
    ) -> QPixmap | None:
        """描いた絵。描けない式（空・壊れた LaTeX）は None。"""
        key = (latex, point_size, color, max_width)
        if key in self._pixmaps:
            self._pixmaps.move_to_end(key)
            return self._pixmaps[key]

        found = self._render(latex, point_size, color, max_width)
        self._pixmaps[key] = found
        while len(self._pixmaps) > _CACHE_SIZE:
            self._pixmaps.popitem(last=False)
        return found

    def size(self, latex: str, *, point_size: float, color: str, max_width: int) -> QSize | None:
        """絵の論理サイズ（px）。高さの予約（highlighter）が見る。"""
        found = self.pixmap(latex, point_size=point_size, color=color, max_width=max_width)
        if found is None:
            return None
        return QSize(
            round(found.width() / found.devicePixelRatio()),
            round(found.height() / found.devicePixelRatio()),
        )

    def _render(self, latex: str, point_size: float, color: str, max_width: int) -> QPixmap | None:
        if not latex.strip():
            return None
        try:
            svg = ziamath.Latex(latex, size=point_size * MATH_POINT_SCALE, color=color).svg()
        except Exception as error:
            logger.debug("数式を描けない: %s (%s)", latex[:40], error)
            return None

        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        base = renderer.defaultSize()
        if not renderer.isValid() or base.isEmpty():
            return None

        # 幅に収める（画像と同じ）。式は横に長くなりがち
        scale = min(1.0, max_width / base.width()) if max_width > 0 else 1.0
        width = max(1, round(base.width() * scale * _RATIO))
        height = max(1, round(base.height() * scale * _RATIO))

        target = QPixmap(width, height)
        target.fill(Qt.GlobalColor.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        target.setDevicePixelRatio(_RATIO)
        return target
