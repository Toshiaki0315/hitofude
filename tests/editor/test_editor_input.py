"""キー入力と入力補助の結線のテスト（タスク 3-1, 3-2, 3-4 / spec §5.5）。

**IME ガード（R6）が本命。** ここが壊れると日本語入力が使い物にならなくなる。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtWidgets import QApplication

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def put(editor: MarkdownEditor, text: str) -> None:
    """本文を入れ、キャレットを末尾に置く（IME 確定と同じ経路）。"""
    editor.setPlainText(text)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)


def start_composition(editor: MarkdownEditor, preedit: str) -> None:
    QApplication.sendEvent(editor, QInputMethodEvent(preedit, []))


def commit_composition(editor: MarkdownEditor, text: str) -> None:
    event = QInputMethodEvent("", [])
    event.setCommitString(text)
    QApplication.sendEvent(editor, event)


class TestListContinuation:
    def test_Enterで箇条書きが続く(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "- 項目\n- "

    def test_インデントも継承する(self, editor, qtbot) -> None:
        put(editor, "  - 項目")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "  - 項目\n  - "

    def test_番号が進む(self, editor, qtbot) -> None:
        put(editor, "1. 項目")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "1. 項目\n2. "

    def test_引用が続く(self, editor, qtbot) -> None:
        put(editor, "> 引用")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "> 引用\n> "

    def test_段落では普通に改行する(self, editor, qtbot) -> None:
        put(editor, "ただの段落")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "ただの段落\n"

    def test_コードフェンスの中では継承しない(self, editor, qtbot) -> None:
        put(editor, "```\n- コードの中")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "```\n- コードの中\n"


class TestEmptyItemReset:
    def test_2回のEnterで段落に戻る(self, editor, qtbot) -> None:
        """spec §5.5-2: `  - ` → `- ` → ``"""
        put(editor, "  - ")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "- "
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == ""

    def test_空の引用は解除される(self, editor, qtbot) -> None:
        put(editor, "> ")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == ""

    def test_解除してもUndoは1手(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "- 項目\n"
        editor.undo()
        assert editor.toPlainText() == "- 項目\n- "


class TestIndent:
    def test_Tabでリストを字下げする(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        qtbot.keyClick(editor, Qt.Key.Key_Tab)
        assert editor.toPlainText() == "  - 項目"

    def test_ShiftTabで字上げする(self, editor, qtbot) -> None:
        put(editor, "    - 項目")
        qtbot.keyClick(editor, Qt.Key.Key_Backtab)
        assert editor.toPlainText() == "  - 項目"

    def test_字下げしてもキャレットは同じ文字の位置に残る(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        before = editor.textCursor().positionInBlock()
        qtbot.keyClick(editor, Qt.Key.Key_Tab)
        assert editor.textCursor().positionInBlock() == before + 2

    def test_段落ではタブが入る(self, editor, qtbot) -> None:
        """spec §5.4: リスト行以外は通常のタブ挿入。"""
        put(editor, "段落")
        qtbot.keyClick(editor, Qt.Key.Key_Tab)
        assert editor.toPlainText() == "段落\t"


class TestImeGuard:
    """R6 / spec §5.5: 変換中は Enter/Tab の特殊処理を**すべて**無効化する。

    ここを怠ると日本語入力が壊滅的に使えなくなる、と仕様書が名指ししている箇所。
    """

    def test_変換中はEnterでリストが増えない(self, editor, qtbot) -> None:
        """止めるのは**特殊処理だけ**。キーそのものは Qt に渡す。

        実機では変換中の Enter は IME が食べてここまで来ないが、
        来てしまった場合でもリストを増やさないことを保証する。
        """
        put(editor, "- 項目")
        start_composition(editor, "にほんご")
        assert editor.is_composing() is True
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "- 項目\n", "変換確定の Enter でリストが増えた"

    def test_変換中はTabで字下げしない(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        start_composition(editor, "にほんご")
        qtbot.keyClick(editor, Qt.Key.Key_Tab)
        assert editor.toPlainText() == "- 項目\t", "変換中に字下げが発火した"

    def test_確定後は補助が戻る(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        start_composition(editor, "にほんご")
        commit_composition(editor, "日本語")
        assert editor.is_composing() is False
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "- 項目日本語\n- "

    def test_変換を取り消しても状態が残らない(self, editor, qtbot) -> None:
        put(editor, "- 項目")
        start_composition(editor, "にほんご")
        start_composition(editor, "")  # 変換キャンセル
        assert editor.is_composing() is False


class TestSelection:
    def test_選択があるときは補助しない(self, editor, qtbot) -> None:
        """選択を置き換える普通の挙動を邪魔しない。"""
        put(editor, "- 項目")
        cursor = editor.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "- \n"
