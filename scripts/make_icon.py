"""アプリアイコン `.icns` を生成する（spec §9 Phase 6, §8.1）。

    uv run python scripts/make_icon.py

外部の画像編集ソフトを要らなくするため、Qt で描いて `iconutil` に渡す。
デザインは「覚書」（改名 2026-08-27 / ADR-0032）— 角を折ったメモ用紙に、
墨の題と本文の線、書き始めの朱点。筆致の弧だった旧デザインから、
墨と朱のアクセントだけを引き継いだ。
差し替えたくなったら `resources/OboeGaki.icns` を上書きすればよい。
軽量版（`resources/OboeGakiLite.icns`）は右下に小さく `Lite` が入る。
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
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

OUTPUT = ROOT / "resources" / "OboeGaki.icns"
LITE_OUTPUT = ROOT / "resources" / "OboeGakiLite.icns"
LITE_MARK = "Lite"
"""軽量版の目印（ユーザー要望 2026-08-28）。**小さく**入れる——
絵の主役は覚書のままで、見分けが付けばよい。"""

LITE_MARK_MIN_SIZE = 64
"""この大きさ未満には入れない。

**読めない字は汚れに見える。** 32px だと字の高さが 4px しか取れず、
実際に描いて見ると「Lite」ではなく右下の赤い滲みになる（実測）。
見分けが付かないうえに、絵が壊れているように見えるほうが損。

Retina では 32pt の枠に 64px の絵が入るので、**いま出回っている Mac では
32pt から字が出る**。名前（OboeGakiLite / 覚書Lite）でも区別は付く。"""
# .icns に必要な解像度（Retina 用の @2x を含む）
SIZES = [16, 32, 64, 128, 256, 512, 1024]

PAPER = "#FCFBF7"
FOLD = "#E7E3D8"
INK = "#1D1D1F"
FAINT = "#9A9AA0"
ACCENT = "#D2553C"


def render(size: int, *, lite: bool = False) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    inset = size * 0.06
    radius = size * 0.22
    left, top = inset, inset
    right, bottom = size - inset, size - inset
    fold = size * 0.24  # 折り返しの一辺

    # 紙。右上の角だけ折り返しぶんを切り欠く
    body = QPainterPath()
    body.moveTo(QPointF(right - fold, top))
    body.lineTo(QPointF(left + radius, top))
    body.quadTo(QPointF(left, top), QPointF(left, top + radius))
    body.lineTo(QPointF(left, bottom - radius))
    body.quadTo(QPointF(left, bottom), QPointF(left + radius, bottom))
    body.lineTo(QPointF(right - radius, bottom))
    body.quadTo(QPointF(right, bottom), QPointF(right, bottom - radius))
    body.lineTo(QPointF(right, top + fold))
    body.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(PAPER))
    painter.drawPath(body)

    # 折り返した角（覚書らしさの要）。紙より一段沈んだ色の三角
    ear = QPainterPath()
    ear.moveTo(QPointF(right - fold, top))
    ear.lineTo(QPointF(right - fold, top + fold * 0.18))
    ear.quadTo(
        QPointF(right - fold, top + fold),
        QPointF(right - fold * 0.18, top + fold),
    )
    ear.lineTo(QPointF(right, top + fold))
    ear.closeSubpath()
    painter.setBrush(QColor(FOLD))
    painter.drawPath(ear)

    # 題の墨線。始点を丸く置いて筆の含みを残す
    pen = QPen(QColor(INK))
    pen.setWidthF(size * 0.075)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(size * 0.40, size * 0.36), QPointF(size * 0.62, size * 0.36))

    # 本文の線。薄くして題と読み分ける
    pen = QPen(QColor(FAINT))
    pen.setWidthF(size * 0.055)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(size * 0.26, size * 0.54), QPointF(size * 0.74, size * 0.54))
    painter.drawLine(QPointF(size * 0.26, size * 0.70), QPointF(size * 0.60, size * 0.70))

    # 書き始めの朱点（旧デザインから引き継ぎ）。題の頭に置く
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawEllipse(QPointF(size * 0.28, size * 0.36), size * 0.055, size * 0.055)

    if lite and size >= LITE_MARK_MIN_SIZE:
        _draw_lite_mark(painter, size)

    painter.end()
    return image


def _draw_lite_mark(painter: QPainter, size: int) -> None:
    """右下に小さく `Lite`。"""
    font = QFont()
    font.setPixelSize(max(1, round(size * 0.13)))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(ACCENT))
    box = QRectF(size * 0.58, size * 0.74, size * 0.28, size * 0.13)
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, LITE_MARK)


def build(output: Path, *, lite: bool) -> None:
    """`.icns` を 1 つ作る。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    iconset = output.with_suffix(".iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()

    for size in SIZES:
        render(size, lite=lite).save(str(iconset / f"icon_{size}x{size}.png"))
        if size <= 512:
            # **@2x は倍の実寸で描き直す**（拡大しない）。目印の字も
            # そのぶん大きく描かれるので、Retina では 32pt から読める
            render(size * 2, lite=lite).save(str(iconset / f"icon_{size}x{size}@2x.png"))

    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    print(f"{output.relative_to(ROOT)}: {output.stat().st_size:,} バイト")


def main() -> None:
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutil が見つからない（macOS でのみ生成できる）")

    QApplication.instance() or QApplication([])
    # **両方まとめて作る。** どちらかだけ古いまま配ることがないように
    build(OUTPUT, lite=False)
    build(LITE_OUTPUT, lite=True)


if __name__ == "__main__":
    main()
