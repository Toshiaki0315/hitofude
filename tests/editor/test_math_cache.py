"""数式の描画キャッシュ（I-1 / ADR-0020）。

LaTeX → SVG は ziamath（純 Python）。matplotlib も QtWebEngine も使わない。
"""

import pytest

from hitofude.editor.math_cache import MathCache

pytestmark = pytest.mark.gui  # QPixmap を作るので QApplication が要る


@pytest.fixture
def cache(qapp) -> MathCache:
    return MathCache()


class TestRender:
    def test_式が絵になる(self, cache) -> None:
        pixmap = cache.pixmap("E = mc^2", point_size=15.0, color="#1c1c1e", max_width=600)
        assert pixmap is not None
        assert pixmap.width() > 0 and pixmap.height() > 0

    def test_壊れた式はNone(self, cache) -> None:
        assert cache.pixmap(r"\frac{1}{", point_size=15.0, color="#000", max_width=600) is None

    def test_空の式はNone(self, cache) -> None:
        assert cache.pixmap("  ", point_size=15.0, color="#000", max_width=600) is None

    def test_同じ指定なら描き直さない(self, cache) -> None:
        first = cache.pixmap("x^2", point_size=15.0, color="#000", max_width=600)
        second = cache.pixmap("x^2", point_size=15.0, color="#000", max_width=600)
        assert first is second

    def test_色が変われば別の絵(self, cache) -> None:
        light = cache.pixmap("x^2", point_size=15.0, color="#000000", max_width=600)
        dark = cache.pixmap("x^2", point_size=15.0, color="#ffffff", max_width=600)
        assert light is not dark

    def test_幅に収める(self, cache) -> None:
        latex = "+".join(["x_{100}^{200}"] * 40)  # とても長い式
        pixmap = cache.pixmap(latex, point_size=15.0, color="#000", max_width=300)
        assert pixmap is not None
        assert pixmap.width() / pixmap.devicePixelRatio() <= 300

    def test_Retinaの倍率が付く(self, cache) -> None:
        pixmap = cache.pixmap("x", point_size=15.0, color="#000", max_width=600)
        assert pixmap.devicePixelRatio() == 2.0

    def test_sizeはpixmapと一致する(self, cache) -> None:
        size = cache.size("y = ax + b", point_size=15.0, color="#000", max_width=600)
        pixmap = cache.pixmap("y = ax + b", point_size=15.0, color="#000", max_width=600)
        assert size is not None
        assert size.width() == pixmap.width() / 2 and size.height() == pixmap.height() / 2

    def test_壊れた式のsizeもNone(self, cache) -> None:
        assert cache.size(r"\frac{1}{", point_size=15.0, color="#000", max_width=600) is None
