"""`Cmd+クリック` の結線（D-1 / D-2）。

判定は `core/activation.py`。ここは**押した場所から判定へ繋がるか**と、
**素のクリックを邪魔しないか**を見る。
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui

CMD = Qt.KeyboardModifier.ControlModifier  # macOS では Cmd


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(600, 300)
    widget.show()
    return widget


def click_at(editor: MarkdownEditor, column: int, *, modifiers=CMD) -> None:
    """その桁を押す。

    **場面（`QPointF`）と画面位置の 2 つを渡す形で作る。** 引数の少ない
    `QMouseEvent` は非推奨で、警告がエラー扱いになって落ちる。
    """
    cursor = editor.textCursor()
    cursor.setPosition(column)
    rect = editor.cursorRect(cursor)
    point = QPointF(rect.left() + 2, rect.center().y())
    editor.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point,
            editor.viewport().mapToGlobal(point),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
    )


class TestLink:
    def test_リンクを押すと知らせる(self, editor, qtbot) -> None:
        editor.setPlainText("[Qt](https://qt.io) を見る")
        with qtbot.waitSignal(editor.link_activated, timeout=1000) as blocker:
            click_at(editor, 2)
        assert blocker.args[0] == "https://qt.io"

    def test_危ないスキームでは知らせない(self, editor, qtbot) -> None:
        editor.setPlainText("[危険](javascript:alert(1))")
        with qtbot.assertNotEmitted(editor.link_activated):
            click_at(editor, 2)

    def test_Cmdなしでは知らせない(self, editor, qtbot) -> None:
        """素のクリックはキャレット移動。編集の邪魔をしない。"""
        editor.setPlainText("[Qt](https://qt.io)")
        with qtbot.assertNotEmitted(editor.link_activated):
            click_at(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)

    def test_リンクでない場所では知らせない(self, editor, qtbot) -> None:
        editor.setPlainText("ただの文章")
        with qtbot.assertNotEmitted(editor.link_activated):
            click_at(editor, 2)


class TestTag:
    def test_タグを押すと知らせる(self, editor, qtbot) -> None:
        editor.setPlainText("メモ #日報 です")
        with qtbot.waitSignal(editor.tag_activated, timeout=1000) as blocker:
            click_at(editor, 5)
        assert blocker.args[0] == "日報"

    def test_Cmdなしでは知らせない(self, editor, qtbot) -> None:
        editor.setPlainText("メモ #日報")
        with qtbot.assertNotEmitted(editor.tag_activated):
            click_at(editor, 5, modifiers=Qt.KeyboardModifier.NoModifier)


class TestCaret:
    def test_Cmdクリックでもキャレットは動く(self, editor) -> None:
        """押した場所を見失わない。開いたあと本文を直せる。"""
        editor.setPlainText("[Qt](https://qt.io) を見る")
        click_at(editor, 2)
        assert editor.textCursor().position() > 0


class TestCheckboxClick:
    """チェックボックスをクリックで切り替える（E-1）。

    他のエディタでは当たり前の操作。今までは `Cmd+Shift+T` しか無かった。
    **`Cmd` は要らない。** 押す場所が印の上に限られているので誤爆しにくく、
    毎回修飾キーを押させるほうが煩わしい。
    """

    def test_印を押すと切り替わる(self, editor) -> None:
        editor.setPlainText("- [ ] やること\n\n末尾")
        click_at(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        assert editor.toPlainText().startswith("- [x] やること")

    def test_もう一度押すと戻る(self, editor) -> None:
        editor.setPlainText("- [x] 済み\n\n末尾")
        click_at(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        assert editor.toPlainText().startswith("- [ ] 済み")

    def test_文字の上では切り替わらない(self, editor) -> None:
        """本文を押しただけで状態が変わると、読んでいるだけで壊れる。"""
        editor.setPlainText("- [ ] やること\n\n末尾")
        click_at(editor, 10, modifiers=Qt.KeyboardModifier.NoModifier)
        assert editor.toPlainText().startswith("- [ ] やること")

    def test_チェックボックスでない行では何も起きない(self, editor) -> None:
        editor.setPlainText("- ただの項目\n\n末尾")
        click_at(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        assert editor.toPlainText().startswith("- ただの項目")

    def test_Undoは1手で戻る(self, editor) -> None:
        editor.setPlainText("- [ ] やること\n\n末尾")
        click_at(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        editor.undo()
        assert editor.toPlainText().startswith("- [ ] やること")

    def test_Rawでは切り替えない(self, editor) -> None:
        """記号を直に触るモードなので、クリックは素の意味（キャレット移動）。"""
        editor.setPlainText("- [ ] やること\n\n末尾")
        editor.set_source_mode(True)
        click_at(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        assert editor.toPlainText().startswith("- [ ] やること")
