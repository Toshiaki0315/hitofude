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

    def test_最後の行の下には引かない(self, view) -> None:
        """下に何も無いところへ線を引くと、宙に浮いて見える。"""
        view.set_rows(rows(2))
        image = shot(view)
        bottom = view.visualRect(view.model().index(1)).bottom()

        assert LIGHT.rule.lower() not in line_colors(image, bottom)

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
