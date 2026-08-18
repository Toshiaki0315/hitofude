"""一覧の仕切り線と、ツールバーのボタンの枠（ユーザー要望）。

どちらも `theme.rule`（表の罫線などで既に使っている薄い色）で引く。
**色を増やさない。** 同じ役目の線が別の色だと、画面が散らかって見える。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from hitofude.theme import DARK, LIGHT
from hitofude.ui.note_list import NoteListView, NoteRow

pytestmark = pytest.mark.gui


def rows(count: int) -> list[NoteRow]:
    return [
        NoteRow(
            id=str(i),
            path=Path(f"{i}.md"),
            title=f"ノート {i}",
            preview="本文の抜粋です。",
            modified_at="2026-08-17T10:00:00",
            mtime_ns=0,
            size_bytes=10,
            pinned=False,
        )
        for i in range(count)
    ]


@pytest.fixture
def view(qtbot) -> NoteListView:
    widget = NoteListView()
    qtbot.addWidget(widget)
    widget.resize(280, 400)
    widget.show()
    return widget


def shot(view: NoteListView) -> QImage:
    image = QImage(view.viewport().size(), QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    view.viewport().render(image, QPoint(0, 0))
    return image


def line_colors(image: QImage, y: int) -> set[str]:
    return {image.pixelColor(x, y).name() for x in range(20, image.width() - 20, 5)}


class TestSeparator:
    def test_行の下に線が引かれる(self, view) -> None:
        view.set_rows(rows(3))
        image = shot(view)
        height = view.visualRect(view.model().index(0)).height()

        assert LIGHT.rule.lower() in line_colors(image, height - 1)

    def test_線は1pxで薄い(self, view) -> None:
        """**太い線は仕切りではなく飾りに見える。** 1px に留める。"""
        view.set_rows(rows(3))
        image = shot(view)
        height = view.visualRect(view.model().index(0)).height()

        assert LIGHT.rule.lower() not in line_colors(image, height - 3)

    def test_最後の行の下にも引く(self, view) -> None:
        """**最後にも引く**（ユーザー要望 2026-08-18）。

        以前は「宙に浮いて見える」として引いていなかったが、最後の
        ノートの領域がどこで終わるか分からない、という指摘で全行に揃えた。
        """
        view.set_rows(rows(2))
        image = shot(view)
        bottom = view.visualRect(view.model().index(1)).bottom()

        assert LIGHT.rule.lower() in line_colors(image, bottom)

    def test_テーマに追従する(self, view) -> None:
        view.set_theme(DARK)
        view.set_rows(rows(3))
        image = shot(view)
        height = view.visualRect(view.model().index(0)).height()

        assert DARK.rule.lower() in line_colors(image, height - 1)


class TestButtonFrame:
    def test_角丸の枠が付く(self, qtbot) -> None:
        from hitofude.editor.editor_widget import MarkdownEditor
        from hitofude.ui.format_toolbar import FormatToolbar

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        bar = FormatToolbar(editor)
        qtbot.addWidget(bar)

        style = bar.buttons()[0].styleSheet() or bar.styleSheet()
        assert LIGHT.rule.lower() in style.lower()
        assert "border-radius" in style

    def test_枠はテーマに追従する(self, qtbot) -> None:
        from hitofude.editor.editor_widget import MarkdownEditor
        from hitofude.ui.format_toolbar import FormatToolbar

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        bar = FormatToolbar(editor)
        qtbot.addWidget(bar)
        bar.set_theme(DARK)

        style = bar.buttons()[0].styleSheet() or bar.styleSheet()
        assert DARK.rule.lower() in style.lower()


class TestListPaneButtons:
    """一覧の上の `⇅` と `＋` にも同じ枠を付ける（ユーザー要望）。

    **同じバーに並ぶボタンは同じ見た目にする。** 本文側だけ枠が付いていると、
    こちらが押せるものだと分かりにくい。
    """

    def make(self, qtbot):
        from hitofude.ui.note_list_pane import NoteListPane

        pane = NoteListPane()
        qtbot.addWidget(pane)
        return pane

    def test_両方に枠が付く(self, qtbot) -> None:
        pane = self.make(qtbot)
        for button in (pane.sort_button, pane.new_button):
            style = button.styleSheet().lower()
            assert LIGHT.rule.lower() in style
            assert "border-radius" in style

    def test_本文側と同じ角丸(self, qtbot) -> None:
        """**丸みが違うと不揃いに見える。** 同じ値を使う。"""
        from hitofude.ui.format_toolbar import BUTTON_RADIUS

        pane = self.make(qtbot)
        assert f"border-radius: {BUTTON_RADIUS}px" in pane.sort_button.styleSheet()

    def test_テーマに追従する(self, qtbot) -> None:
        pane = self.make(qtbot)
        pane.set_theme(DARK)
        assert DARK.rule.lower() in pane.new_button.styleSheet().lower()

    def test_三角を出さない(self, qtbot) -> None:
        """文字＋三角をやめ、正方形のアイコンボタンにした（ユーザー指摘）。"""
        pane = self.make(qtbot)
        assert "menu-indicator" in pane.sort_button.styleSheet()
