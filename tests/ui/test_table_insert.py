"""表を作るボタンとダイアログ（ユーザー要望 2026-08-26）。

**入口は 2 つ、中身は 1 つ。** ツールバーのボタンと「編集」メニューの
どちらから押しても `MainWindow.insert_table` を通る。行と列を聞く窓が
UI 側にあるのが、他の書式ボタンと違うところ（`editor/` は窓を開かない）。
"""

import pytest

from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.table_dialog import TableSizeDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> EditorPane:
    widget = EditorPane()
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestButton:
    def test_ツールバーにボタンがある(self, pane) -> None:
        assert pane.toolbar.table_button.accessibleName() == "表"

    def test_押すと知らせる(self, pane, qtbot) -> None:
        """**開くのはツールバーではない**（窓を知らない。アウトラインと同じ形）。"""
        with qtbot.waitSignal(pane.toolbar.table_requested, timeout=500):
            pane.toolbar.table_button.click()

    def test_フォーカスは奪わない(self, pane) -> None:
        """他のボタンと同じ約束（奪うと本文の選択が外れる）。"""
        from PySide6.QtCore import Qt

        assert pane.toolbar.table_button.focusPolicy() is Qt.FocusPolicy.NoFocus

    def test_絵が付いている(self, pane) -> None:
        assert not pane.toolbar.table_button.icon().isNull()


class TestDialog:
    def test_既定は3行3列(self, qtbot) -> None:
        dialog = TableSizeDialog()
        qtbot.addWidget(dialog)
        assert dialog.values() == (3, 3)

    def test_行と列を返す(self, qtbot) -> None:
        dialog = TableSizeDialog()
        qtbot.addWidget(dialog)
        dialog.set_values(rows=2, columns=5)
        assert dialog.values() == (2, 5)

    def test_1より小さくはできない(self, qtbot) -> None:
        dialog = TableSizeDialog()
        qtbot.addWidget(dialog)
        dialog.set_values(rows=0, columns=0)
        assert dialog.values() == (1, 1)

    def test_見出しは行数に数えない(self, qtbot) -> None:
        """数え方が食い違うと 1 行ずれた表ができる。窓の文言で示す。"""
        dialog = TableSizeDialog()
        qtbot.addWidget(dialog)
        assert "見出し" in dialog.hint()


class TestWiring:
    def test_メニューからも作れる(self, window) -> None:
        assert "表を作る…" in window.menu_actions

    def test_聞いた大きさで作る(self, window, monkeypatch) -> None:
        window.new_note()
        monkeypatch.setattr(window, "_ask_table_size", lambda: (2, 4))
        window.insert_table()
        lines = [line for line in window.editor.toPlainText().splitlines() if line.startswith("|")]
        assert len(lines) == 4  # 見出し + 区切り + 本体 2
        assert lines[0].count("|") == 5  # 4 列

    def test_取り消したら何もしない(self, window, monkeypatch) -> None:
        window.new_note()
        before = window.editor.toPlainText()
        monkeypatch.setattr(window, "_ask_table_size", lambda: None)
        window.insert_table()
        assert window.editor.toPlainText() == before

    def test_ツールバーのボタンが繋がっている(self, window, monkeypatch) -> None:
        window.new_note()
        monkeypatch.setattr(window, "_ask_table_size", lambda: (1, 2))
        window._pane.toolbar.table_button.click()
        assert "見出し1" in window.editor.toPlainText()
