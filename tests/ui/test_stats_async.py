"""文字数の集計を背景で回す（ユーザー要望）。

長い本文では集計に時間がかかる（実測: 5 万文字で 70ms、忙しいときは
285ms）。**打つのをやめて 0.4 秒後**に走るので入力の邪魔にはならないが、
その一瞬だけ画面が止まる。数えるのは表示のためだけなので、待たせる理由がない。

**短い本文はその場で数える。** 1,000 文字なら 1.5ms で、投げて返す
ほうが遅い。1 フレーム（16ms）に収まる長さを境にする。
"""

import time

import pytest

from hitofude.ui.main_window import ASYNC_STATS_CHARS

pytestmark = pytest.mark.gui

LINE = "これは日本語の文章です。**強調** も入ります。\n"


@pytest.fixture
def window(window):
    """数える対象が要る。"""
    window.new_note()
    return window


def long_text() -> str:
    """境を確実に超える長さ。"""
    return LINE * (ASYNC_STATS_CHARS // len(LINE) + 200)


class TestThreshold:
    def test_境は1フレームに収まる長さ(self) -> None:
        """**16ms を超えるものだけ投げる。** 実測 1,000 文字 1.5ms /
        1 万文字 13.7ms / 1.3 万文字 17.0ms。"""
        assert 5_000 <= ASYNC_STATS_CHARS <= 13_000

    def test_短い本文はその場で数える(self, window) -> None:
        window.editor.setPlainText("短いメモ\n")
        window._update_stats()
        assert "文字" in window.status_text()


class TestBackground:
    def test_長い本文でも待たされない(self, window) -> None:
        """**その場で数えると 70ms 止まる。** 投げるだけなら一瞬で戻る。"""
        window.editor.setPlainText(long_text())

        started = time.perf_counter()
        window._update_stats()
        elapsed = (time.perf_counter() - started) * 1000

        assert elapsed < 16.0, f"{elapsed:.0f}ms 待たされた"

    def test_数え終わると表示が変わる(self, window, qtbot) -> None:
        text = long_text()
        window.editor.setPlainText(text)
        window._update_stats()

        from hitofude.core.stats import count

        # 記号は数に入らない（`**強調**` は 2 文字ぶん増えない）ので、
        # 期待値も同じ関数から作る
        expected = f"{count(text).characters:,} 文字"
        qtbot.waitUntil(lambda: expected in window.status_text(), timeout=5000)

    def test_古い結果は捨てる(self, window, qtbot) -> None:
        """**数え終わる前に別のノートへ移れる。** 遅れて届いた前の
        ノートの数字を出すと、今見ているものと食い違う。"""
        from hitofude.core.stats import TextStats

        window.editor.setPlainText(long_text())
        window._update_stats()
        qtbot.waitUntil(lambda: "文字" in window.status_text(), timeout=5000)
        shown = window.status_text()

        window._on_stats_counted(-1, TextStats(characters=999_999, lines=999_999))
        assert window.status_text() == shown

    def test_閉じたあとに届いても落ちない(self, window) -> None:
        """`closeEvent` はワーカーを待つが、**そこから飛んだシグナルは
        待ち行列に残る**（索引の走査で実際に踏んでいる）。"""
        from hitofude.core.stats import TextStats

        window.editor.setPlainText(long_text())
        window._update_stats()
        window.close()

        window._on_stats_counted(window._stats_token, TextStats(characters=1, lines=1))
