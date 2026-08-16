"""上部のバーの大きさ（ユーザー要望）。

一覧の上（並び順・新規）と本文の上（書式ツールバー）が小さく感じる、
という指摘。**倍率を 1 か所に持つ**ので、戻すときも試すときもここを
変えるだけで済む。
"""

import pytest

from hitofude.ui.icons import TOOLBAR_SCALE

pytestmark = pytest.mark.gui


class TestScale:
    def test_倍率は1か所(self) -> None:
        """**各ファイルに 1.5 を散らさない。** 直すときに片方だけ残る。"""
        assert pytest.approx(1.5) == TOOLBAR_SCALE

    def test_書式ツールバーの寸法が倍率どおり(self) -> None:
        from hitofude.ui import format_toolbar as module

        assert round(module.BASE_ICON_SIZE * TOOLBAR_SCALE) == module.ICON_SIZE
        assert round(module.BASE_BUTTON_SIZE * TOOLBAR_SCALE) == module.BUTTON_SIZE

    def test_ボタンは正方形のまま(self, qtbot) -> None:
        from hitofude.editor.editor_widget import MarkdownEditor
        from hitofude.ui.format_toolbar import BUTTON_SIZE, FormatToolbar

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        bar = FormatToolbar(editor)
        qtbot.addWidget(bar)
        for button in bar.buttons():
            assert button.size().width() == BUTTON_SIZE
            assert button.size().height() == BUTTON_SIZE

    def test_絵も一緒に大きくなる(self, qtbot) -> None:
        """**枠だけ広げない。** 記号が小さいまま余白だけ増えると、
        押せる場所は広がっても見やすくはならない。"""
        from hitofude.editor.editor_widget import MarkdownEditor
        from hitofude.ui.format_toolbar import ICON_SIZE, FormatToolbar

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        bar = FormatToolbar(editor)
        qtbot.addWidget(bar)
        assert bar.buttons()[0].iconSize().width() == ICON_SIZE

    def test_一覧の上の記号も大きくなる(self, qtbot) -> None:
        """`＋` と `⇅` は絵ではなく文字なので、字の大きさで効かせる。"""
        from hitofude.ui.note_list_pane import NoteListPane

        pane = NoteListPane()
        qtbot.addWidget(pane)
        base = pane.font().pointSizeF()
        for button in (pane.new_button, pane.sort_button):
            assert button.font().pointSizeF() == pytest.approx(base * TOOLBAR_SCALE)

    def test_並び順の三角が重ならない(self, qtbot) -> None:
        """字を大きくすると記号も広がる。三角の場所も一緒に広げる。"""
        import math

        from PySide6.QtGui import QFontMetricsF

        from hitofude.ui.note_list_pane import SORT_GLYPH, SORT_INDICATOR_ROOM, NoteListPane

        pane = NoteListPane()
        qtbot.addWidget(pane)
        glyph = QFontMetricsF(pane.sort_button.font()).horizontalAdvance(SORT_GLYPH)
        assert pane.sort_button.minimumWidth() >= math.ceil(glyph + SORT_INDICATOR_ROOM)
