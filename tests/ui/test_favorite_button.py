"""お気に入りの大きなボタン（ユーザー要望 2026-08-27 / Qiita 風）。

本文の左——幅を絞ったときに生まれる沈んだ領域——に星を浮かせ、
押すとお気に入りの入り切りになる。状態は星の塗りで見える。
"""

import pytest
from PySide6.QtCore import Qt

from hitofude.ui.editor_pane import EditorPane

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> EditorPane:
    widget = EditorPane()
    qtbot.addWidget(widget)
    widget.resize(1000, 500)
    widget.show()
    return widget


class TestButton:
    def test_ボタンがある(self, pane) -> None:
        assert pane.favorite_button.accessibleName() == "お気に入り"

    def test_押すと知らせる(self, pane, qtbot) -> None:
        """**切り替えるのは呼び出し側**（ここはノートを知らない）。"""
        with qtbot.waitSignal(pane.favorite_toggled, timeout=500):
            pane.favorite_button.click()

    def test_状態を映す(self, pane) -> None:
        pane.set_favorite(True)
        assert pane.favorite_button.isChecked()
        pane.set_favorite(False)
        assert not pane.favorite_button.isChecked()

    def test_フォーカスは奪わない(self, pane) -> None:
        assert pane.favorite_button.focusPolicy() is Qt.FocusPolicy.NoFocus

    def test_左の沈んだ領域に浮く(self, pane, qtbot) -> None:
        pane.editor.set_content_width(720)
        pane.set_favorite_visible(True)
        qtbot.wait(80)  # 置き直しはイベントループ経由
        margin = pane.editor.viewportMargins().left()
        assert margin > 60, "前提: 左に沈んだ領域がある"
        assert pane.favorite_button.isVisible()
        assert pane.favorite_button.geometry().right() <= margin

    def test_領域が無ければ隠れる(self, pane, qtbot) -> None:
        """全幅では置き場が無い。本文に重ねると開閉三角と取り合いになる。"""
        pane.editor.set_content_width(0)
        pane.set_favorite_visible(True)
        qtbot.wait(80)
        assert not pane.favorite_button.isVisible()


class TestWiring:
    def test_ノートを開くと出る(self, window) -> None:
        """出す**意思**を見る。窓を出す前は余白が 0 で、実際の表示は
        場所が決まってから（`toolbar_visible` と同じ理由）。"""
        assert not window._pane.favorite_visible()
        window.new_note()
        assert window._pane.favorite_visible()

    def test_押すとお気に入りが切り替わる(self, window) -> None:
        window.new_note()
        path = window._note.path
        window._pane.favorite_button.click()
        assert window._notes.is_pinned(path)
        assert window._pane.favorite_button.isChecked()
        window._pane.favorite_button.click()
        assert not window._notes.is_pinned(path)
        assert not window._pane.favorite_button.isChecked()

    def test_メニューから切り替えても星に映る(self, window) -> None:
        """入口が違っても状態は 1 つ。"""
        window.new_note()
        window.toggle_pin_current()
        assert window._pane.favorite_button.isChecked()
