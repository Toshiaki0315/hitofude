"""本文の左右（書けない場所）を薄く塗る（ユーザー要望 2026-08-26）。

Qiita のように、**書ける幅の外側**が地の色になっていると「ここが紙」だと
分かる。今はどちらも同じ白で、幅を絞っていることが見た目から伝わらない。

**塗り分け方**（実測で選んだ）。`setViewportMargins` で作った余白は
ウィジェット側の領域で、本文（viewport）とは別に塗れる。

| 試した形 | 外側 | 本文側 |
| --- | --- | --- |
| `Window` ロール + `autoFillBackground` | **薄い色** | **地の色** |
| QSS で `background` を指定 | 薄い色 | 薄い色（**本文まで塗る**） |

QSS は viewport まで塗ってしまうので使えない。
"""

import pytest
from PySide6.QtGui import QColor, QPalette

from hitofude.config import CONTENT_WIDTH_PIXELS, ContentWidth
from hitofude.theme import DARK, LIGHT

pytestmark = pytest.mark.gui


class TestThemeHasIt:
    """**地の色をテーマに持つ。** 明暗どちらでも「紙より少し沈む」。"""

    @pytest.mark.parametrize("theme", [LIGHT, DARK])
    def test_本文の色とは違う(self, theme) -> None:
        assert theme.page_background != theme.background

    def test_明るいテーマでは本文より暗い(self) -> None:
        assert QColor(LIGHT.page_background).lightness() < QColor(LIGHT.background).lightness()

    def test_暗いテーマでは本文より暗い(self) -> None:
        """**暗いほうへ沈める。** 明るくすると光って見え、目が疲れる。"""
        assert QColor(DARK.page_background).lightness() < QColor(DARK.background).lightness()

    @pytest.mark.parametrize("theme", [LIGHT, DARK])
    def test_差は控えめ(self, theme) -> None:
        """**主張させない。** 本文を読む邪魔になる。"""
        gap = abs(QColor(theme.page_background).lightness() - QColor(theme.background).lightness())
        assert 0 < gap <= 40, gap


class TestPalette:
    def test_外側の色を持っている(self, window) -> None:
        editor = window.editor
        found = editor.palette().color(QPalette.ColorRole.Window)
        assert found == QColor(LIGHT.page_background)

    def test_自分で背景を塗る(self, window) -> None:
        """**`autoFillBackground` が無いと塗られない**（実測）。"""
        assert window.editor.autoFillBackground()

    def test_本文の色は変えない(self, window) -> None:
        found = window.editor.palette().color(QPalette.ColorRole.Base)
        assert found == QColor(LIGHT.background)

    def test_テーマを変えれば追う(self, window) -> None:
        window.editor.set_theme(DARK)
        found = window.editor.palette().color(QPalette.ColorRole.Window)
        assert found == QColor(DARK.page_background)


class TestPixels:
    """**実際に塗れているかは画素で見る。**"""

    def wide(self, window, qtbot):
        """本文だけにして広げる（余白が出る幅にする）。"""
        window.resize(2000, 700)
        window.toggle_sidebar()
        window.toggle_note_list()
        window.show()
        qtbot.waitExposed(window)
        window.editor.setPlainText("# 会議メモ\n\n本文です。\n")
        qtbot.wait(50)
        return window.editor

    def color_at(self, window, x: int) -> QColor:
        """**窓ごと描いて見る。** エディタ単体を `grab()` すると、
        `autoFillBackground` を外しても色が出てしまい、**変異が素通りした**
        （実測）。人が見るのは窓なので、窓で見る。
        """
        editor = window.editor
        origin = editor.mapTo(window, editor.rect().topLeft())
        image = window.grab().toImage()
        return QColor(image.pixel(origin.x() + x, origin.y() + editor.height() // 2))

    def test_外側が薄く塗られる(self, window, qtbot) -> None:
        editor = self.wide(window, qtbot)
        assert editor.viewportMargins().left() > 50, "余白が出ていない"
        assert self.color_at(window, 10) == QColor(LIGHT.page_background)

    def test_本文側は地の色のまま(self, window, qtbot) -> None:
        editor = self.wide(window, qtbot)
        inside = editor.viewportMargins().left() + 40
        assert self.color_at(window, inside) == QColor(LIGHT.background)

    def test_暗いテーマでも外側が沈む(self, window, qtbot) -> None:
        """**暗いほうへ沈む**（明るくすると外側が光って本文より目立つ）。

        色の決め方は `TestThemeHasIt` が見ている。ここは**実際に塗れて
        いるか**を画素で見る。
        """
        window.editor.set_theme(DARK)
        editor = self.wide(window, qtbot)
        assert editor.viewportMargins().left() > 50
        outer = self.color_at(window, 10)
        assert outer == QColor(DARK.page_background)
        assert outer.lightness() < QColor(DARK.background).lightness()

    def test_幅いっぱいなら塗る場所が無い(self, window, qtbot) -> None:
        """`ContentWidth.FULL` は余白 0。**外側が無いので何も変わらない。**"""
        window._config.content_width = ContentWidth.FULL
        window.editor.set_content_width(CONTENT_WIDTH_PIXELS[ContentWidth.FULL])
        editor = self.wide(window, qtbot)
        assert editor.viewportMargins().left() == 0
        assert self.color_at(window, 10) == QColor(LIGHT.background)
