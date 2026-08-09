"""サイドバーのアイコン（ユーザー要望）。

**絵文字も画像ファイルも使わない。** 絵文字は色を指定できずテーマから浮き、
画像ファイルは 2 テーマ × 解像度ぶん用意することになる。線で描けば
色を渡すだけで済み、`resources/Hitofude.icns` と同じやり方に揃う。
"""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from hitofude.ui.icons import Glyph, glyph_icon

pytestmark = pytest.mark.gui


def rendered(icon, size: int = 32) -> QImage:
    return icon.pixmap(QSize(size, size)).toImage()


def drawn_colors(image: QImage) -> set[str]:
    """透明でない画素の色。"""
    found = set()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = QColor(image.pixelColor(x, y))
            if pixel.alpha() > 128:
                found.add(pixel.name())
    return found


class TestDrawing:
    @pytest.mark.parametrize("glyph", list(Glyph))
    def test_描ける(self, qapp, glyph: Glyph) -> None:
        assert not glyph_icon(glyph, "#1d1d1f").isNull()

    @pytest.mark.parametrize("glyph", list(Glyph))
    def test_中身がある(self, qapp, glyph: Glyph) -> None:
        """空の四角を返していないこと。"""
        assert drawn_colors(rendered(glyph_icon(glyph, "#1d1d1f")))

    def test_渡した色で描く(self, qapp) -> None:
        colors = drawn_colors(rendered(glyph_icon(Glyph.ALL, "#ff0000")))
        assert all(c == "#ff0000" for c in colors), colors

    def test_色を変えれば変わる(self, qapp) -> None:
        light = drawn_colors(rendered(glyph_icon(Glyph.ALL, "#1d1d1f")))
        dark = drawn_colors(rendered(glyph_icon(Glyph.ALL, "#e8e8ea")))
        assert light != dark

    def test_種類ごとに違う絵になる(self, qapp) -> None:
        """全部同じ絵だと見分けが付かない。"""
        seen = {}
        for glyph in Glyph:
            image = rendered(glyph_icon(glyph, "#1d1d1f"))
            key = bytes(image.constBits())
            assert key not in seen, f"{glyph} と {seen[key]} が同じ絵"
            seen[key] = glyph

    def test_大きさを指定できる(self, qapp) -> None:
        icon = glyph_icon(Glyph.TRASH, "#1d1d1f")
        assert icon.pixmap(QSize(64, 64)).width() == 64

    def test_同じ指定なら作り直さない(self, qapp) -> None:
        """一覧の再構築のたびに描き直すと無駄。"""
        assert glyph_icon(Glyph.TAG, "#1d1d1f") is glyph_icon(Glyph.TAG, "#1d1d1f")

    def test_色が違えば別のものを返す(self, qapp) -> None:
        assert glyph_icon(Glyph.TAG, "#1d1d1f") is not glyph_icon(Glyph.TAG, "#e8e8ea")


class TestFilled:
    """塗り潰しの星（一覧のピン留めの印に使う）。

    小さく出すので、輪郭だけだと何の形か分からない。
    """

    def test_塗り潰せる(self, qapp) -> None:
        assert not glyph_icon(Glyph.PINNED, "#e0a100", filled=True).isNull()

    def test_輪郭だけのものとは違う(self, qapp) -> None:
        outline = rendered(glyph_icon(Glyph.PINNED, "#e0a100"))
        solid = rendered(glyph_icon(Glyph.PINNED, "#e0a100", filled=True))
        assert bytes(outline.constBits()) != bytes(solid.constBits())

    def test_中まで色が乗る(self, qapp) -> None:
        image = rendered(glyph_icon(Glyph.PINNED, "#e0a100", filled=True), 32)
        center = image.pixelColor(16, 18)
        assert center.alpha() > 128
        assert center.name() == "#e0a100"

    def test_塗り潰しも別に覚える(self, qapp) -> None:
        assert glyph_icon(Glyph.PINNED, "#e0a100") is not glyph_icon(
            Glyph.PINNED, "#e0a100", filled=True
        )
