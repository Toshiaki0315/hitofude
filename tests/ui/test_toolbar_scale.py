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
        """**各ファイルに数字を散らさない。** 直すときに片方だけ残る。"""
        assert pytest.approx(1.3) == TOOLBAR_SCALE

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

    def test_一覧の上のボタンも同じ大きさ(self, qtbot) -> None:
        """`⇅` と `＋` は**絵で描く**ようにしたので、本文側と同じ寸法に
        なる（文字だったころは字の大きさで効かせていた）。"""
        from hitofude.ui.format_toolbar import BUTTON_SIZE, ICON_SIZE
        from hitofude.ui.note_list_pane import NoteListPane

        pane = NoteListPane()
        qtbot.addWidget(pane)
        for button in (pane.new_button, pane.sort_button):
            assert button.size().width() == BUTTON_SIZE
            assert button.iconSize().width() == ICON_SIZE


class TestSameHeight:
    """**一覧側と本文側の上のバーは同じ高さ**（ユーザー要望）。

    左右に並んで見えるので、高さが違うと段差になって目に付く。実測で
    本文側 42px に対して一覧側は 34px だった。
    """

    def test_高さが揃っている(self, qtbot) -> None:
        from hitofude.editor.editor_widget import MarkdownEditor
        from hitofude.ui.format_toolbar import FormatToolbar
        from hitofude.ui.note_list_pane import NoteListPane

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        bar = FormatToolbar(editor)
        qtbot.addWidget(bar)
        bar.resize(600, bar.sizeHint().height())
        bar.show()

        pane = NoteListPane()
        qtbot.addWidget(pane)
        pane.resize(300, 400)
        pane.show()

        assert pane.header_height() == bar.height()

    def test_一覧はその下から始まる(self, qtbot) -> None:
        """バーの高さを決めても、一覧が食い込んでは意味がない。"""
        from hitofude.ui.note_list_pane import NoteListPane

        pane = NoteListPane()
        qtbot.addWidget(pane)
        pane.resize(300, 400)
        pane.show()

        assert pane.note_list.geometry().top() == pane.header_height()

    def test_記号は上下の真ん中(self, qtbot) -> None:
        """高さだけ増やして記号が上に張り付くと、ただ余白が空いて見える。"""
        from hitofude.ui.note_list_pane import NoteListPane

        pane = NoteListPane()
        qtbot.addWidget(pane)
        pane.resize(300, 400)
        pane.show()

        for button in (pane.sort_button, pane.new_button):
            box = button.geometry()
            above = box.top()
            below = pane.header_height() - box.bottom() - 1
            assert abs(above - below) <= 1, (above, below)
