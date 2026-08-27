"""コードブロックのコピーボタン（ユーザー要望 2026-08-27 / Qiita 風）。

コードの上にマウスを載せると右上に写しの印が出て、押すと**フェンスを
除いた中身**がクリップボードへ入る。
"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTextCursor
from PySide6.QtWidgets import QApplication

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import BAND_MARGIN

pytestmark = pytest.mark.gui

NOTE = "前の本文\n\n```python\nprint(1)\nprint(2)\n```\n\n後の本文\n"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.show()
    widget.setPlainText(NOTE)
    widget.moveCursor(QTextCursor.MoveOperation.End)
    return widget


def hover(editor: MarkdownEditor, line: int) -> None:
    """その行の真ん中へマウスを動かす。"""
    block = editor.document().findBlockByNumber(line)
    geometry = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
    point = QPoint(int(editor.viewport().width() / 2), int(geometry.center().y()))
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(point),
        QPointF(point),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(editor.viewport(), event)


class TestShowHide:
    def test_コードの上で出る(self, editor) -> None:
        hover(editor, 3)
        assert editor.code_copy.button.isVisible()

    def test_フェンスの行でも出る(self, editor) -> None:
        hover(editor, 2)
        assert editor.code_copy.button.isVisible()

    def test_本文の上では出ない(self, editor) -> None:
        hover(editor, 3)
        hover(editor, 0)
        assert not editor.code_copy.button.isVisible()

    def test_編集すると隠れる(self, editor) -> None:
        """行番号が動くと控えた範囲が古くなる。次の hover で出直す。"""
        hover(editor, 3)
        cursor = editor.textCursor()
        cursor.insertText("x")
        assert not editor.code_copy.button.isVisible()

    def test_帯の右上に付く(self, editor) -> None:
        hover(editor, 3)
        button = editor.code_copy.button
        band_right = editor.viewport().width() - BAND_MARGIN
        assert button.geometry().right() <= band_right
        assert button.geometry().right() >= band_right - 60
        block = editor.document().findBlockByNumber(2)  # 開きフェンス = 帯の上端
        top = editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top()
        assert abs(button.y() - top) < 30


class TestCopy:
    def test_押すと中身だけコピーされる(self, editor) -> None:
        """フェンス（```python）は含まない。"""
        hover(editor, 3)
        editor.code_copy.button.click()
        assert QApplication.clipboard().text() == "print(1)\nprint(2)\n"

    def test_閉じフェンスから押しても同じ(self, editor) -> None:
        hover(editor, 5)
        editor.code_copy.button.click()
        assert QApplication.clipboard().text() == "print(1)\nprint(2)\n"

    def test_ソースは変わらない(self, editor) -> None:
        hover(editor, 3)
        editor.code_copy.button.click()
        assert editor.toPlainText() == NOTE
