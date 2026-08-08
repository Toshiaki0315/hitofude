"""アプリアイコン `.icns` を生成する（spec §9 Phase 6, §8.1）。

    uv run python scripts/make_icon.py

外部の画像編集ソフトを要らなくするため、Qt で描いて `iconutil` に渡す。
デザインは「一筆」— 一本の筆致を表す弧を、紙色の角丸の上に置いただけのもの。
差し替えたくなったら `resources/Hitofude.icns` を上書きすればよい。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUTPUT = ROOT / "resources" / "Hitofude.icns"
# .icns に必要な解像度（Retina 用の @2x を含む）
SIZES = [16, 32, 64, 128, 256, 512, 1024]

PAPER = "#FCFBF7"
INK = "#1D1D1F"
ACCENT = "#D2553C"


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    inset = size * 0.06
    body = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(PAPER))
    painter.drawRoundedRect(body, size * 0.22, size * 0.22)

    # 一本の筆致。始点を太く、終点を細くして払いを表す
    stroke = QPainterPath()
    stroke.moveTo(QPointF(size * 0.28, size * 0.66))
    stroke.cubicTo(
        QPointF(size * 0.42, size * 0.26),
        QPointF(size * 0.62, size * 0.74),
        QPointF(size * 0.76, size * 0.36),
    )
    pen = QPen(QColor(INK))
    pen.setWidthF(size * 0.085)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(stroke)

    # 筆を置いた点。アクセント色で「書き始め」を示す
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawEllipse(QPointF(size * 0.28, size * 0.66), size * 0.055, size * 0.055)

    painter.end()
    return image


def main() -> None:
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutil が見つからない（macOS でのみ生成できる）")

    QApplication.instance() or QApplication([])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    iconset = OUTPUT.with_suffix(".iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()

    for size in SIZES:
        render(size).save(str(iconset / f"icon_{size}x{size}.png"))
        if size <= 512:
            render(size * 2).save(str(iconset / f"icon_{size}x{size}@2x.png"))

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(OUTPUT)],
        check=True,
    )
    shutil.rmtree(iconset, ignore_errors=True)
    print(f"{OUTPUT.relative_to(ROOT)}: {OUTPUT.stat().st_size:,} バイト")


if __name__ == "__main__":
    main()
