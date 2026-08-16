"""`Cmd+クリック` の結線（D-1 / D-2）。

判定は `core/activation.py`。ここは**押した場所から判定へ繋がるか**と、
**素のクリックを邪魔しないか**を見る。
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

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


def move_to(editor: MarkdownEditor, column: int, *, modifiers=CMD) -> None:
    """その桁へマウスを動かす（押さない）。

    **`mouseMoveEvent()` を直に呼ばない。** 実際の移動は viewport 宛てに
    届くので、そこへ送る。直に呼ぶと「イベントがそもそも来ていない」
    （マウス追跡が切れている）状態を見逃す。
    """
    cursor = editor.textCursor()
    cursor.setPosition(column)
    rect = editor.cursorRect(cursor)
    point = QPointF(rect.left() + 2, rect.center().y())
    QApplication.sendEvent(
        editor.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            editor.viewport().mapToGlobal(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            modifiers,
        ),
    )


def hold_cmd(editor: MarkdownEditor, *, held: bool = True) -> None:
    """マウスを動かさずに `Cmd` を押す／離す。"""
    kind = QEvent.Type.KeyPress if held else QEvent.Type.KeyRelease
    modifiers = CMD if held else Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(editor, QKeyEvent(kind, Qt.Key.Key_Control, modifiers))


def shape(editor: MarkdownEditor):
    return editor.viewport().cursor().shape()


class TestHoverCursor:
    """押せるものの上でカーソルの形を変える（G-2）。

    **今までは手掛かりがゼロだった。** リンクもタグも `[[ノート]]` も、
    見た目は本文と同じ色付きの文字で、`Cmd+クリック` できること自体に
    気づけない。判定は `activation_at()` が既に持っているので、
    ここは形を変えるだけ。

    **`Cmd` を押している間だけ。** 素のマウス移動で形が変わると、
    文字を選ぼうとしただけで手の形になって落ち着かない。
    """

    def test_リンクの上で手の形になる(self, editor) -> None:
        editor.setPlainText("[Qt](https://qt.io) を見る")
        move_to(editor, 2)
        assert shape(editor) is Qt.CursorShape.PointingHandCursor

    def test_タグの上でも手の形(self, editor) -> None:
        editor.setPlainText("#仕事 の話")
        move_to(editor, 1)
        assert shape(editor) is Qt.CursorShape.PointingHandCursor

    def test_ノートのリンクでも手の形(self, editor) -> None:
        editor.setPlainText("[[会議メモ]] を見る")
        move_to(editor, 4)
        assert shape(editor) is Qt.CursorShape.PointingHandCursor

    def test_本文の上では文字のまま(self, editor) -> None:
        editor.setPlainText("ただの本文です")
        move_to(editor, 3)
        assert shape(editor) is Qt.CursorShape.IBeamCursor

    def test_Cmdを押していなければ変わらない(self, editor) -> None:
        """素の移動で形が変わると、選ぼうとしただけで落ち着かない。"""
        editor.setPlainText("[Qt](https://qt.io) を見る")
        move_to(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        assert shape(editor) is Qt.CursorShape.IBeamCursor

    def test_離れると戻る(self, editor) -> None:
        editor.setPlainText("[Qt](https://qt.io) と本文")
        move_to(editor, 2)
        move_to(editor, 22)
        assert shape(editor) is Qt.CursorShape.IBeamCursor

    def test_開けないリンクは変わらない(self, editor) -> None:
        """`javascript:` は開かない（D-1）。押せないものを押せそうに見せない。"""
        editor.setPlainText("[危険](javascript:alert(1)) を見る")
        move_to(editor, 2)
        assert shape(editor) is Qt.CursorShape.IBeamCursor

    def test_Rawでも効く(self, editor) -> None:
        """記号が見えていても押せることに変わりはない。"""
        editor.setPlainText("[Qt](https://qt.io)")
        editor.set_source_mode(True)
        move_to(editor, 2)
        assert shape(editor) is Qt.CursorShape.PointingHandCursor

    def test_マウスを動かさずCmdを押しても手になる(self, editor) -> None:
        """**押す前に手が出ないと気づけない。** リンクの上にマウスを置いた
        まま `Cmd` を押すのが自然な順で、そこで形が変わらなければ
        「押せる」ことは伝わらない。"""
        editor.setPlainText("[Qt](https://qt.io) を見る")
        move_to(editor, 2, modifiers=Qt.KeyboardModifier.NoModifier)
        hold_cmd(editor)
        assert shape(editor) is Qt.CursorShape.PointingHandCursor

    def test_Cmdを離すと文字に戻る(self, editor) -> None:
        editor.setPlainText("[Qt](https://qt.io) を見る")
        move_to(editor, 2)
        hold_cmd(editor, held=False)
        assert shape(editor) is Qt.CursorShape.IBeamCursor

    def test_本文の上でCmdを押しても変わらない(self, editor) -> None:
        editor.setPlainText("ただの本文です")
        move_to(editor, 3, modifiers=Qt.KeyboardModifier.NoModifier)
        hold_cmd(editor)
        assert shape(editor) is Qt.CursorShape.IBeamCursor

    def test_マウスが来ていなければCmdだけでは変わらない(self, editor) -> None:
        """どこを指しているか分からないうちに形を変えない。"""
        editor.setPlainText("[Qt](https://qt.io) を見る")
        hold_cmd(editor)
        assert shape(editor) is Qt.CursorShape.IBeamCursor
