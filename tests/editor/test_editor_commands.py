"""ショートカットと入力補助の結線のテスト（タスク 3-3, 3-5, 3-6 / spec §5.4, §5.5）。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui

CMD = Qt.KeyboardModifier.ControlModifier  # macOS では Cmd に対応する
CMD_SHIFT = CMD | Qt.KeyboardModifier.ShiftModifier


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def select(editor: MarkdownEditor, start: int, end: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)


def press(editor: MarkdownEditor, key, text: str = "") -> None:
    """文字つきのキー押下を送る。

    `QTest.keyClick` は PySide6 では `text=` を受け付けないので、
    QKeyEvent を直接組み立てる。オートペアは押された文字そのものを見るため、
    キーコードだけでは判定できない。
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
    QApplication.sendEvent(editor, event)


def put_caret(editor: MarkdownEditor, position: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(position)
    editor.setTextCursor(cursor)


class TestToggleShortcuts:
    @pytest.mark.parametrize(
        ("key", "modifier", "expected"),
        [
            (Qt.Key.Key_B, CMD, "これは**強調**です"),
            (Qt.Key.Key_I, CMD, "これは*強調*です"),
            (Qt.Key.Key_E, CMD, "これは`強調`です"),
            (Qt.Key.Key_X, CMD_SHIFT, "これは~~強調~~です"),
            (Qt.Key.Key_H, CMD_SHIFT, "これは::強調::です"),
        ],
    )
    def test_選択範囲を囲む(self, editor, qtbot, key, modifier, expected) -> None:
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        qtbot.keyClick(editor, key, modifier)
        assert editor.toPlainText() == expected

    def test_もう一度押すと外れる(self, editor, qtbot) -> None:
        """spec §5.4「既に囲まれていれば外す、を必ず実装」。"""
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        qtbot.keyClick(editor, Qt.Key.Key_B, CMD)
        assert editor.toPlainText() == "これは**強調**です"
        qtbot.keyClick(editor, Qt.Key.Key_B, CMD)
        assert editor.toPlainText() == "これは強調です"

    def test_囲んだあとも同じ文字が選ばれている(self, editor, qtbot) -> None:
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        qtbot.keyClick(editor, Qt.Key.Key_B, CMD)
        assert editor.textCursor().selectedText() == "強調"

    def test_Undoは1手で戻る(self, editor, qtbot) -> None:
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        qtbot.keyClick(editor, Qt.Key.Key_B, CMD)
        editor.undo()
        assert editor.toPlainText() == "これは強調です"


class TestLink:
    def test_CmdKで選択をリンクにする(self, editor, qtbot) -> None:
        editor.setPlainText("Qt のドキュメント")
        select(editor, 0, 2)
        qtbot.keyClick(editor, Qt.Key.Key_K, CMD)
        assert editor.toPlainText() == "[Qt]() のドキュメント"

    def test_キャレットが丸括弧の中にある(self, editor, qtbot) -> None:
        editor.setPlainText("Qt")
        select(editor, 0, 2)
        qtbot.keyClick(editor, Qt.Key.Key_K, CMD)
        assert editor.textCursor().position() == 5


class TestPasteAsLink:
    """spec §5.5-5: 選択があってクリップボードが URL ならリンクにする。"""

    def test_URLを貼るとリンクになる(self, editor) -> None:
        from PySide6.QtCore import QMimeData

        editor.setPlainText("Qt のドキュメント")
        select(editor, 0, 2)
        data = QMimeData()
        data.setText("https://doc.qt.io/")
        editor.insertFromMimeData(data)
        assert editor.toPlainText() == "[Qt](https://doc.qt.io/) のドキュメント"

    def test_URLでなければ普通に貼る(self, editor) -> None:
        from PySide6.QtCore import QMimeData

        editor.setPlainText("Qt のドキュメント")
        select(editor, 0, 2)
        data = QMimeData()
        data.setText("Framework")
        editor.insertFromMimeData(data)
        assert editor.toPlainText() == "Framework のドキュメント"

    def test_選択が無ければ普通に貼る(self, editor) -> None:
        from PySide6.QtCore import QMimeData

        editor.setPlainText("")
        data = QMimeData()
        data.setText("https://doc.qt.io/")
        editor.insertFromMimeData(data)
        assert editor.toPlainText() == "https://doc.qt.io/"


class TestAutoPair:
    """spec §5.5-4: 選択状態で囲み記号を押すと選択範囲を囲む。"""

    @pytest.mark.parametrize(
        ("key", "text", "expected"),
        [
            (Qt.Key.Key_Asterisk, "*", "これは*強調*です"),
            (Qt.Key.Key_BracketLeft, "[", "これは[強調]です"),
            (Qt.Key.Key_ParenLeft, "(", "これは(強調)です"),
            (Qt.Key.Key_QuoteDbl, '"', 'これは"強調"です'),
        ],
    )
    def test_選択範囲を囲む(self, editor, qtbot, key, text, expected) -> None:
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        press(editor, key, text)
        assert editor.toPlainText() == expected

    def test_選択が無ければそのまま入力される(self, editor, qtbot) -> None:
        editor.setPlainText("")
        press(editor, Qt.Key.Key_BracketLeft, "[")
        assert editor.toPlainText() == "["

    def test_囲んだあとも選択が残る(self, editor, qtbot) -> None:
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        press(editor, Qt.Key.Key_Asterisk, "*")
        assert editor.textCursor().selectedText() == "強調"


class TestHeadingLevel:
    def test_下げると見出しになる(self, editor, qtbot) -> None:
        editor.setPlainText("段落")
        put_caret(editor, 1)
        qtbot.keyClick(editor, Qt.Key.Key_Down, CMD_SHIFT)
        assert editor.toPlainText() == "# 段落"

    def test_上げると大きくなる(self, editor, qtbot) -> None:
        editor.setPlainText("## 見出し")
        put_caret(editor, 4)
        qtbot.keyClick(editor, Qt.Key.Key_Up, CMD_SHIFT)
        assert editor.toPlainText() == "# 見出し"

    def test_H1から上げると段落に戻る(self, editor, qtbot) -> None:
        editor.setPlainText("# 見出し")
        put_caret(editor, 3)
        qtbot.keyClick(editor, Qt.Key.Key_Up, CMD_SHIFT)
        assert editor.toPlainText() == "見出し"

    def test_H6より下げられない(self, editor, qtbot) -> None:
        editor.setPlainText("###### 見出し")
        put_caret(editor, 8)
        qtbot.keyClick(editor, Qt.Key.Key_Down, CMD_SHIFT)
        assert editor.toPlainText() == "###### 見出し"


class TestCheckbox:
    def test_CmdShiftTで付ける(self, editor, qtbot) -> None:
        editor.setPlainText("- 項目")
        put_caret(editor, 4)
        qtbot.keyClick(editor, Qt.Key.Key_T, CMD_SHIFT)
        assert editor.toPlainText() == "- [ ] 項目"

    def test_もう一度押すとチェックが付く(self, editor, qtbot) -> None:
        editor.setPlainText("- [ ] 項目")
        put_caret(editor, 8)
        qtbot.keyClick(editor, Qt.Key.Key_T, CMD_SHIFT)
        assert editor.toPlainText() == "- [x] 項目"

    def test_さらに押すと外れる(self, editor, qtbot) -> None:
        editor.setPlainText("- [x] 項目")
        put_caret(editor, 8)
        qtbot.keyClick(editor, Qt.Key.Key_T, CMD_SHIFT)
        assert editor.toPlainText() == "- [ ] 項目"


class TestImeGuardStillApplies:
    def test_変換中はショートカットも効かない(self, editor, qtbot) -> None:
        """R6: 変換中は特殊処理を全て無効化する。"""
        from PySide6.QtGui import QInputMethodEvent
        from PySide6.QtWidgets import QApplication

        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        QApplication.sendEvent(editor, QInputMethodEvent("にほんご", []))
        qtbot.keyClick(editor, Qt.Key.Key_B, CMD)
        assert "**" not in editor.toPlainText()


class TestUnknownCommandKeys:
    """未処理の Cmd 組み合わせで文字を入れない（回帰テスト）。

    macOS では Option が文字合成に使われる。`Cmd+Option+T` は `†` を生み、
    選択中に押すと**選択範囲がその 1 文字に置き換わって消える**。
    実際に表 4 行を失った。
    """

    def _send(self, editor, key, text: str, modifiers) -> None:
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text))

    def test_CmdOptionTで文字が入らない(self, editor) -> None:
        editor.setPlainText("消えては困る内容")
        select(editor, 0, 8)
        self._send(
            editor,
            Qt.Key.Key_T,
            "†",
            CMD | Qt.KeyboardModifier.AltModifier,
        )
        assert editor.toPlainText() == "消えては困る内容"

    def test_知らないCmdの組み合わせでも消えない(self, editor) -> None:
        editor.setPlainText("表の中身")
        select(editor, 0, 4)
        for key, text in ((Qt.Key.Key_J, "∆"), (Qt.Key.Key_G, "©"), (Qt.Key.Key_5, "%")):
            self._send(editor, key, text, CMD | Qt.KeyboardModifier.AltModifier)
        assert editor.toPlainText() == "表の中身"

    def test_修飾なしの文字は普通に入る(self, editor) -> None:
        editor.setPlainText("")
        self._send(editor, Qt.Key.Key_A, "a", Qt.KeyboardModifier.NoModifier)
        assert editor.toPlainText() == "a"

    def test_割り当て済みのCmdは効く(self, editor, qtbot) -> None:
        editor.setPlainText("これは強調です")
        select(editor, 3, 5)
        qtbot.keyClick(editor, Qt.Key.Key_B, CMD)
        assert editor.toPlainText() == "これは**強調**です"
