"""コードフェンスの言語補完（ユーザー要望）。

```py まで打ったところで Pygments の言語名を出す。判定と絞り込みは
`core/code_langs.py`（純関数）。ここは**ポップアップの出し入れと確定**、
そして発火してはいけない場面を見る。タグ補完（C-4 / H-3）と同じ部品を使う。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def type_fence(editor: MarkdownEditor, text: str) -> None:
    editor.setPlainText("")
    editor.textCursor().insertText(text)
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.update_tag_completion()


class TestPopup:
    def test_言語を打ちかけると候補が出る(self, editor) -> None:
        type_fence(editor, "```pyth")
        assert "python" in editor.tag_candidates()

    def test_タグの口が無くても出る(self, editor) -> None:
        """タグ補完と違い、索引（tag_source）に依存しない。"""
        editor.set_tag_source(None)
        type_fence(editor, "```pyth")
        assert "python" in editor.tag_candidates()

    def test_フェンスだけでは出ない(self, editor) -> None:
        """Enter を奪うと素のコードブロックが作れない。"""
        type_fence(editor, "```")
        assert editor.tag_candidates() == []

    def test_本文では出ない(self, editor) -> None:
        type_fence(editor, "pyth")
        assert editor.tag_candidates() == []

    def test_フェンスの中では出ない(self, editor) -> None:
        """開いたフェンスの中の ```py は閉じ損ないのコード。補完しない。"""
        type_fence(editor, "```\n```py")
        assert editor.tag_candidates() == []

    def test_変換中は出ない(self, editor) -> None:
        """R6: IME の変換候補と重なる。"""
        from PySide6.QtGui import QInputMethodEvent
        from PySide6.QtWidgets import QApplication

        type_fence(editor, "```py")
        QApplication.sendEvent(editor, QInputMethodEvent("に", []))
        editor.update_tag_completion()
        assert editor.tag_candidates() == []


class TestComplete:
    def test_Enterで確定する(self, editor, qtbot) -> None:
        type_fence(editor, "```pyth")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "```python"

    def test_ファイル名の前でも確定できる(self, editor) -> None:
        editor.setPlainText("```py:aaa.py")
        cursor = editor.textCursor()
        cursor.setPosition(5)
        editor.setTextCursor(cursor)
        editor.update_tag_completion()
        assert "python" in editor.tag_candidates()

        editor.complete_tag("python")
        assert editor.toPlainText() == "```python:aaa.py"

    def test_Escで閉じて改行は素通り(self, editor, qtbot) -> None:
        type_fence(editor, "```pyth")
        qtbot.keyClick(editor, Qt.Key.Key_Escape)
        assert editor.tag_candidates() == []
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert "\n" in editor.toPlainText()
