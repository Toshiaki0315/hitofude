"""ノート内検索バーのテスト（`Cmd+F`）。

位置の計算は `tests/core/test_search.py`、カーソルの動きは
`tests/editor/test_editor_search.py` が見る。ここは**バーとエディタの
繋がり**だけを検査する。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.find_bar import NO_MATCH

pytestmark = pytest.mark.gui

TEXT = "りんご みかん りんご\nぶどう りんご"


@pytest.fixture
def pane(qtbot) -> EditorPane:
    widget = EditorPane()
    qtbot.addWidget(widget)
    widget.editor.setPlainText(TEXT)
    widget.show()
    return widget


class TestOpenClose:
    def test_最初は隠れている(self, pane) -> None:
        assert pane.find_bar.isVisible() is False

    def test_開くと出る(self, pane) -> None:
        pane.open_find()
        assert pane.find_bar.isVisible() is True

    def test_開くと入力欄にフォーカスが移る(self, pane) -> None:
        pane.open_find()
        assert pane.find_bar.focusWidget() is not None

    def test_選択していた語が初期値になる(self, pane) -> None:
        pane.editor.find_text("みかん")
        pane.open_find()
        assert pane.find_bar.query == "みかん"

    def test_改行を含む選択は初期値にしない(self, pane) -> None:
        """行をまたいで選んで Cmd+F を押すのは、たいてい検索の意図ではない。"""
        pane.editor.selectAll()
        pane.open_find()
        assert "\n" not in pane.find_bar.query

    def test_閉じると隠れる(self, pane) -> None:
        pane.open_find()
        pane.close_find()
        assert pane.find_bar.isVisible() is False

    def test_閉じると強調が消える(self, pane) -> None:
        """下敷きが残ると、本文の一部が装飾されているように見える。"""
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.close_find()
        assert pane.editor.extraSelections() == []

    def test_閉じるとエディタへ戻る(self, pane) -> None:
        pane.open_find()
        pane.close_find()
        assert pane.editor.hasFocus()

    def test_Escで閉じる(self, pane, qtbot) -> None:
        pane.open_find()
        qtbot.keyClick(pane.find_bar._query, Qt.Key.Key_Escape)
        assert pane.find_bar.isVisible() is False


class TestSearching:
    def test_打つと一致が光る(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        assert len(pane.editor.extraSelections()) == 3

    def test_件数が出る(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        assert "3" in pane.find_bar._status.text()

    def test_無ければそう出る(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("バナナ")
        assert pane.find_bar._status.text() == NO_MATCH

    def test_消すと件数表示も消える(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.find_bar._query.setText("")
        assert pane.find_bar._status.text() == ""

    def test_Enterで次へ進む(self, pane, qtbot) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        qtbot.keyClick(pane.find_bar._query, Qt.Key.Key_Return)
        assert pane.editor.textCursor().selectedText() == "りんご"

    def test_Shift_Enterで前へ戻る(self, pane, qtbot) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        qtbot.keyClick(pane.find_bar._query, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert pane.editor.textCursor().selectionStart() == 16

    def test_バーを開かずに次を探せる(self, pane) -> None:
        """`Cmd+G`。一度検索した語を覚えている。"""
        pane.open_find()
        pane.find_bar._query.setText("みかん")
        pane.close_find()
        pane.find_again()
        assert pane.editor.textCursor().selectedText() == "みかん"

    def test_大文字小文字の区別を切り替えると数え直す(self, pane) -> None:
        pane.editor.setPlainText("Apple apple")
        pane.open_find()
        pane.find_bar._query.setText("apple")
        assert len(pane.editor.extraSelections()) == 2

        pane.find_bar._case.setChecked(True)
        assert len(pane.editor.extraSelections()) == 1


class TestReplacing:
    def test_置換できる(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("みかん")
        pane.find_bar._replacement.setText("なし")
        pane.find_bar.replace_requested.emit("みかん", "なし")  # 選択のため 1 回目
        pane.find_bar.replace_requested.emit("みかん", "なし")
        assert "みかん" not in pane.editor.toPlainText()

    def test_すべて置換できる(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.find_bar._replacement.setText("なし")
        pane.find_bar.replace_all_requested.emit("りんご", "なし")
        assert pane.editor.toPlainText() == "なし みかん なし\nぶどう なし"

    def test_すべて置換すると件数が0になる(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.find_bar.replace_all_requested.emit("りんご", "なし")
        assert pane.find_bar._status.text() == NO_MATCH

    def test_空のクエリでは何も起きない(self, pane) -> None:
        """置換欄だけ埋めて押しても本文を壊さない。"""
        pane.open_find()
        pane.find_bar._replacement.setText("なし")
        pane.find_bar._emit_replace()
        assert pane.editor.toPlainText() == TEXT


class TestImeGuard:
    """R6: 変換中の Enter は確定であって検索ではない。"""

    def test_変換中のEnterで検索しない(self, pane, qtbot) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        before = pane.editor.textCursor().position()

        QApplication.sendEvent(pane.find_bar._query, QInputMethodEvent("りんご", []))
        qtbot.keyClick(pane.find_bar._query, Qt.Key.Key_Return)

        assert pane.editor.textCursor().position() == before

    def test_確定後のEnterでは検索する(self, pane, qtbot) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")

        QApplication.sendEvent(pane.find_bar._query, QInputMethodEvent("りんご", []))
        QApplication.sendEvent(pane.find_bar._query, QInputMethodEvent("", []))
        qtbot.keyClick(pane.find_bar._query, Qt.Key.Key_Return)

        assert pane.editor.textCursor().selectedText() == "りんご"


class TestNoteSwitch:
    """本文が入れ替わったときの強調。"""

    def test_本文が変わると引き直す(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.editor.setPlainText("まったく別の本文\n")
        pane.refresh_highlights()
        assert pane.editor.extraSelections() == []

    def test_同じ語があれば光り直す(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.editor.setPlainText("りんごが 1 つ\n")
        pane.refresh_highlights()
        assert len(pane.editor.extraSelections()) == 1

    def test_バーが閉じていれば光らせない(self, pane) -> None:
        pane.open_find()
        pane.find_bar._query.setText("りんご")
        pane.close_find()
        pane.refresh_highlights()
        assert pane.editor.extraSelections() == []
