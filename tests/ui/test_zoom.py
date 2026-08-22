"""`Cmd +` / `Cmd -` で本文の文字サイズを変える（G-5）。

今までは設定を開くしかなかった。**読み返すとき・人に画面を見せるとき**は
「今そうしたい」操作で、ダイアログを開いて数字を入れて閉じる、では重い。

変えた大きさは**設定に残す**（次に開いたときも同じ）。設定の
「文字サイズ」と同じ値を触るので、両方から見て食い違わない。
"""

import pytest
from PySide6.QtGui import QKeySequence

from hitofude.config import DEFAULT_POINT_SIZE, MAX_POINT_SIZE, MIN_POINT_SIZE
from hitofude.ui.main_window import ZOOM_STEP, MainWindow

pytestmark = pytest.mark.gui


def size(window: MainWindow) -> float:
    return window.editor.font().pointSizeF()


class TestZoom:
    def test_大きくなる(self, window) -> None:
        before = size(window)
        assert window.zoom_in() is True
        assert size(window) == pytest.approx(before + ZOOM_STEP)

    def test_小さくなる(self, window) -> None:
        before = size(window)
        assert window.zoom_out() is True
        assert size(window) == pytest.approx(before - ZOOM_STEP)

    def test_設定に残る(self, window) -> None:
        """次に開いたときも同じ大きさで出る。"""
        window.zoom_in()
        assert window.config.font_point_size == pytest.approx(size(window))

    def test_設定と同じ値を触る(self, window) -> None:
        """**2 つの数字を持たない。** 別々に持つと、片方で変えたときに
        もう片方が古い値を書き戻す。"""
        window.config.font_point_size = 20.0
        window._apply_preferences()
        window.zoom_in()
        assert window.config.font_point_size == pytest.approx(20.0 + ZOOM_STEP)

    def test_標準に戻せる(self, window) -> None:
        window.zoom_in()
        window.zoom_in()
        window.reset_zoom()
        assert size(window) == pytest.approx(DEFAULT_POINT_SIZE)

    def test_ハイライタにも伝わる(self, window) -> None:
        """見出しやコードは本文の大きさから決まる。ここが伝わらないと、
        本文だけ大きくなって見出しが取り残される。"""
        window.zoom_in()
        assert window.editor.highlighter.base_point_size == pytest.approx(size(window))


class TestLimits:
    def test_大きくしすぎない(self, window) -> None:
        window.config.font_point_size = MAX_POINT_SIZE
        window._apply_preferences()
        assert window.zoom_in() is False
        assert size(window) == pytest.approx(MAX_POINT_SIZE)

    def test_小さくしすぎない(self, window) -> None:
        window.config.font_point_size = MIN_POINT_SIZE
        window._apply_preferences()
        assert window.zoom_out() is False
        assert size(window) == pytest.approx(MIN_POINT_SIZE)

    def test_端でも設定を壊さない(self, window) -> None:
        window.config.font_point_size = MIN_POINT_SIZE
        window._apply_preferences()
        window.zoom_out()
        assert window.config.font_point_size == pytest.approx(MIN_POINT_SIZE)

    def test_端に丸める(self, window) -> None:
        """あと 0.5pt しか余裕が無くても、そこまでは動く。"""
        window.config.font_point_size = MAX_POINT_SIZE - 0.5
        window._apply_preferences()
        assert window.zoom_in() is True
        assert size(window) == pytest.approx(MAX_POINT_SIZE)


class TestMenu:
    def labels(self, window: MainWindow) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for action in window.actions():
            found[action.text()] = [key.toString() for key in action.shortcuts()]
        return found

    def test_表示メニューに入っている(self, window) -> None:
        labels = self.labels(window)
        assert "文字を大きく" in labels
        assert "文字を小さく" in labels
        assert "標準の大きさ" in labels

    def test_Cmdプラスで効く(self, window) -> None:
        keys = self.labels(window)["文字を大きく"]
        assert QKeySequence("Ctrl++").toString() in keys

    def test_Cmdイコールでも効く(self, window) -> None:
        """**`+` は Shift を押さないと打てない。** 実際に押されるのは
        `Cmd+=` のほうが多いので、両方受ける（他のアプリもそうしている）。"""
        keys = self.labels(window)["文字を大きく"]
        assert QKeySequence("Ctrl+=").toString() in keys

    def test_Cmdマイナスで効く(self, window) -> None:
        keys = self.labels(window)["文字を小さく"]
        assert QKeySequence("Ctrl+-").toString() in keys

    def test_Cmdゼロで標準に戻る(self, window) -> None:
        keys = self.labels(window)["標準の大きさ"]
        assert QKeySequence("Ctrl+0").toString() in keys


class TestNotice:
    def test_今の大きさを知らせる(self, window) -> None:
        """**変えたことが分かるように。** 1pt の差は見て取りにくい。"""
        window.zoom_in()
        assert "pt" in window.notice()
