"""リンク先をその場で覗く（U-2。ユーザー要望 2026-08-29）。

`[[ノート]]` に `Cmd` を押しながら触れると、**開かずに**冒頭が浮いて出る。
確かめるために開いて戻る往復が要らなくなる。

**`Cmd` を要る条件にする**（カーソルの形と同じ理由）。素の移動で泡が
出ると、文字を選ぼうとしただけで邪魔になる。開く操作自体が
`Cmd+クリック` なので、条件も揃う。

ここは vault を知らない。**中身は呼び出し側が渡す**（`set_note_source`
と同じ作法）。
"""

import pytest
from PySide6.QtCore import QPoint

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.link_preview import EXCERPT_LINES, LinkPreview

pytestmark = pytest.mark.gui

NOTE = "前の本文\n\n[[会議メモ]] を見る\n\n末尾\n"
TARGET = "# 会議メモ\n\n決めたこと\n次にやること\n"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setPlainText(NOTE)
    return widget


def link_point(editor: MarkdownEditor) -> QPoint:
    """`[[会議メモ]]` の真ん中あたり。"""
    block = editor.document().findBlockByNumber(2)
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + 4)
    return editor.cursorRect(cursor).center()


class TestExcerpt:
    """出す中身（純粋な組み立て）。"""

    def test_冒頭を出す(self) -> None:
        from hitofude.editor.link_preview import excerpt

        assert "決めたこと" in excerpt(TARGET)

    def test_見出しの記号は出さない(self) -> None:
        """**読むためのもの。** `#` が並ぶと読みにくい。"""
        from hitofude.editor.link_preview import excerpt

        assert not excerpt(TARGET).startswith("#")

    def test_長い本文は切る(self) -> None:
        from hitofude.editor.link_preview import excerpt

        long_text = "\n".join(f"{i} 行目" for i in range(50))
        assert excerpt(long_text).count("\n") < EXCERPT_LINES + 2

    def test_front_matterは出さない(self) -> None:
        """**実物のノートには front matter が付く**（作成日時と id）。
        そのまま出すと泡が YAML で埋まる（実機で確認）。
        """
        from hitofude.editor.link_preview import excerpt

        raw = "---\ncreated: 2026-08-29\nid: 01J\n---\n\n# 会議メモ\n\n決めたこと\n"
        found = excerpt(raw)
        assert "created" not in found
        assert "決めたこと" in found

    def test_空なら何も返さない(self) -> None:
        from hitofude.editor.link_preview import excerpt

        assert excerpt("# 題だけ\n") == ""


class TestHover:
    @pytest.fixture
    def preview(self, editor) -> LinkPreview:
        found = LinkPreview(editor)
        found.set_source(lambda title: TARGET if title == "会議メモ" else None)
        return found

    def test_Cmdを押していれば出る(self, preview, editor, qtbot) -> None:
        preview.update(link_point(editor), held=True)
        preview.show_now()  # 待ちを飛ばす
        from hitofude.ui import tooltip

        assert tooltip.is_showing()
        assert "決めたこと" in tooltip.shown_text()
        tooltip.hide()

    def test_Cmdを押していなければ出ない(self, preview, editor) -> None:
        """**素の移動では邪魔しない**（カーソルの形と同じ約束）。"""
        from hitofude.ui import tooltip

        tooltip.hide()
        preview.update(link_point(editor), held=False)
        preview.show_now()
        assert not tooltip.is_showing()

    def test_リンクの外では出ない(self, preview, editor) -> None:
        from hitofude.ui import tooltip

        tooltip.hide()
        block = editor.document().findBlockByNumber(0)
        cursor = editor.textCursor()
        cursor.setPosition(block.position() + 1)
        preview.update(editor.cursorRect(cursor).center(), held=True)
        preview.show_now()
        assert not tooltip.is_showing()

    def test_まだ無いノートでは出ない(self, editor) -> None:
        """**空の泡を出さない。** 無いノートは `Cmd+クリック` で作る道がある。"""
        from hitofude.ui import tooltip

        tooltip.hide()
        found = LinkPreview(editor)
        found.set_source(lambda title: None)
        found.update(link_point(editor), held=True)
        found.show_now()
        assert not tooltip.is_showing()

    def test_離れたら消える(self, preview, editor) -> None:
        from hitofude.ui import tooltip

        preview.update(link_point(editor), held=True)
        preview.show_now()
        preview.hide()
        assert not tooltip.is_showing()


class TestWiredToEditor:
    """エディタのマウス移動から呼ばれること。**繋がっていなければ出ない。**"""

    def move(self, editor, point, *, held: bool) -> None:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        modifier = Qt.KeyboardModifier.ControlModifier if held else Qt.KeyboardModifier.NoModifier
        QApplication.sendEvent(
            editor.viewport(),
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(point),
                QPointF(point),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                modifier,
            ),
        )

    def test_マウス移動で用意される(self, editor) -> None:
        from hitofude.ui import tooltip

        tooltip.hide()
        editor.set_note_preview(lambda title: TARGET if title == "会議メモ" else None)
        self.move(editor, link_point(editor), held=True)
        editor._link_preview.show_now()
        assert "決めたこと" in tooltip.shown_text()
        tooltip.hide()

    def test_Cmdなしでは用意されない(self, editor) -> None:
        from hitofude.ui import tooltip

        tooltip.hide()
        editor.set_note_preview(lambda title: TARGET)
        self.move(editor, link_point(editor), held=False)
        editor._link_preview.show_now()
        assert not tooltip.is_showing()


class TestModifierAfterHover:
    """**リンクに触れてから `Cmd` を押す**（ユーザー報告 2026-08-30）。

    形（指差し）は変わるのに泡が出なかった。キーの押下は
    `_update_hover`（カーソルの形）だけを呼んでいて、覗き見の用意は
    マウスの移動からしか呼ばれていなかった。

    **押せると見せたなら、見せられるべき。** 形と泡は同じ合図から動かす。
    """

    def press(self, editor, *, held: bool) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication

        kind = QKeyEvent.Type.KeyPress if held else QKeyEvent.Type.KeyRelease
        QApplication.sendEvent(
            editor,
            QKeyEvent(kind, Qt.Key.Key_Control, Qt.KeyboardModifier.NoModifier),
        )

    def move(self, editor, point) -> None:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendEvent(
            editor.viewport(),
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(point),
                QPointF(point),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    def test_触れてからCmdで出る(self, editor) -> None:
        """**これが本題。** 先に触れて、あとから押す順。"""
        from hitofude.ui import tooltip

        tooltip.hide()
        editor.set_note_preview(lambda title: TARGET if title == "会議メモ" else None)
        self.move(editor, link_point(editor))  # Cmd なしで触れる
        self.press(editor, held=True)
        editor._link_preview.show_now()
        assert "決めたこと" in tooltip.shown_text()
        tooltip.hide()

    def test_離したら消える(self, editor) -> None:
        from hitofude.ui import tooltip

        editor.set_note_preview(lambda title: TARGET)
        self.move(editor, link_point(editor))
        self.press(editor, held=True)
        editor._link_preview.show_now()
        self.press(editor, held=False)
        assert not tooltip.is_showing()

    def test_リンクの外で押しても出ない(self, editor) -> None:
        from hitofude.ui import tooltip

        tooltip.hide()
        editor.set_note_preview(lambda title: TARGET)
        block = editor.document().findBlockByNumber(0)
        cursor = editor.textCursor()
        cursor.setPosition(block.position() + 1)
        self.move(editor, editor.cursorRect(cursor).center())
        self.press(editor, held=True)
        editor._link_preview.show_now()
        assert not tooltip.is_showing()
