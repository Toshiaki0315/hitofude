"""一覧の上のボタン（`⇅` と `＋`）の作り（ユーザー指摘）。

**文字ではなく絵で描く。** 文字の `⇅` にポップアップ用の三角が付く形は、
横に広がって間延びし、三角と記号が近づくと重なった（過去のユーザー報告）。
本文側の書式ツールバーと同じ、**正方形のアイコンボタン**に揃える。

**フォーカスは受け取らない。** 書式ツールバーと同じ扱い（押しても本文の
キャレットを手放さない）。
"""

import pytest
from PySide6.QtCore import Qt

from hitofude.theme import DARK, LIGHT
from hitofude.ui.format_toolbar import BUTTON_SIZE, ICON_SIZE
from hitofude.ui.note_list_pane import NoteListPane

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> NoteListPane:
    widget = NoteListPane(theme=LIGHT)
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestFocus:
    def test_フォーカスを受け取らない(self, pane) -> None:
        for button in (pane.sort_button, pane.new_button):
            assert button.focusPolicy() is Qt.FocusPolicy.NoFocus


class TestShape:
    def test_本文側と同じ正方形(self, pane) -> None:
        for button in (pane.sort_button, pane.new_button):
            assert button.size().width() == BUTTON_SIZE
            assert button.size().height() == BUTTON_SIZE

    def test_絵で描く(self, pane) -> None:
        """文字だと書体で形が変わる。線で描けば色も大きさもこちらで決まる。"""
        for button in (pane.sort_button, pane.new_button):
            assert not button.text()
            assert not button.icon().isNull()
            assert button.iconSize().width() == ICON_SIZE

    def test_三角を出さない(self, pane) -> None:
        """**Qt の三角を消す。** 正方形に収めた絵の横に出ると、はみ出すか
        記号と重なる（過去のユーザー報告）。"""
        assert "menu-indicator" in pane.sort_button.styleSheet()

    def test_メニューは今まで通り出る(self, pane) -> None:
        assert pane.sort_button.menu() is not None
        assert len(pane.sort_button.menu().actions()) == 3

    def test_何のボタンか分かる(self, pane) -> None:
        assert "並び順" in pane.sort_button.toolTip()
        assert "新規" in pane.new_button.toolTip()


class TestTheme:
    def test_テーマで絵を描き直す(self, pane) -> None:
        """色を渡して描くので、暗い側では明るい線になる。"""
        before = pane.sort_button.icon().cacheKey()
        pane.set_theme(DARK)
        assert pane.sort_button.icon().cacheKey() != before
