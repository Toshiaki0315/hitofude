"""印刷（C-9）。

`Cmd+P` は macOS では**印刷ダイアログ**が慣習で、そこから「PDF として保存」も
選べる。ここは PDF 書き出しに割り当てていたので、慣習のほうへ戻した。

**ダイアログは出さずに試す。** `QPrintDialog.exec()` はモーダルで、
出したらテストが止まる。押した / やめた の分岐だけ差し替えて、その先を見る。
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from hitofude.ui import export_actions as export_actions_module
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


class FakeDialog:
    """`QPrintDialog` の代わり。開いた回数と答えだけを持つ。"""

    opened = 0
    answer = QDialog.DialogCode.Accepted

    def __init__(self, printer, parent=None) -> None:
        self.printer = printer
        type(self).opened += 1

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def exec(self) -> int:
        return type(self).answer

    def deleteLater(self) -> None:
        pass  # 本物と同じ口だけ持つ


@pytest.fixture
def dialog(monkeypatch) -> type[FakeDialog]:
    class Spy(FakeDialog):
        opened = 0
        answer = QDialog.DialogCode.Accepted

    monkeypatch.setattr(export_actions_module, "QPrintDialog", Spy)
    return Spy


@pytest.fixture
def printed(monkeypatch) -> list[tuple]:
    """`exporter.print_document` に渡ったものを記録する。"""
    calls: list[tuple] = []
    monkeypatch.setattr(
        export_actions_module.exporter,
        "print_document",
        lambda printer, text, **kwargs: calls.append((printer, text, kwargs)),
    )
    return calls


def open_note(window: MainWindow, body: str = "# 刷るノート\n\n本文\n") -> Path:
    note = window.vault.create("刷るノート", body)
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    window.open_note(note.path)
    return note.path


class TestPrintFlow:
    def test_ノートが無ければダイアログを出さない(self, window, dialog, printed) -> None:
        window._note = None
        assert window.print_note() is False
        assert dialog.opened == 0

    def test_やめれば刷らない(self, window, dialog, printed) -> None:
        open_note(window)
        dialog.answer = QDialog.DialogCode.Rejected

        assert window.print_note() is False
        assert dialog.opened == 1
        assert printed == []

    def test_押せば今の本文が流れる(self, window, dialog, printed) -> None:
        open_note(window)

        assert window.print_note() is True
        assert len(printed) == 1
        assert "刷るノート" in printed[0][1]

    def test_打った直後の内容が出る(self, window, dialog, printed) -> None:
        """デバウンス待ちの文字が抜け落ちない。書き出しと同じく先に保存する。"""
        open_note(window)
        window.editor.textCursor().insertText("\nまだ保存していない行\n")

        window.print_note()
        assert "まだ保存していない行" in printed[0][1]
        assert "まだ保存していない行" in window.current_note.path.read_text(encoding="utf-8")

    def test_保管フォルダを渡す(self, window, dialog, printed) -> None:
        """画像は相対パス。基準を渡さないと絵が出ない。"""
        open_note(window)
        window.print_note()
        assert printed[0][2]["base_path"] == window.vault.root

    def test_本文は変わらない(self, window, dialog, printed) -> None:
        """R1: 印刷は一方通行。"""
        path = open_note(window)
        before = path.read_text(encoding="utf-8")
        window.print_note()
        assert path.read_text(encoding="utf-8") == before


class TestMenu:
    def test_CmdPは印刷になる(self, window) -> None:
        """macOS の慣習。PDF はそのダイアログから出せる。"""
        assert self._shortcut(window, "Ctrl+P") == "印刷…"

    def test_PDF書き出しは残っている(self, window) -> None:
        """入口を消すわけではない。キーを譲っただけ。"""
        labels = [action.text() for action in window.actions()]
        assert "PDF で書き出す…" in labels

    def test_PDF書き出しはCmdPを取らない(self, window) -> None:
        for action in window.actions():
            if action.text() == "PDF で書き出す…":
                assert action.shortcut().toString() != "Ctrl+P"

    def _shortcut(self, window, keys: str) -> str:
        for action in window.actions():
            if action.shortcut().toString() == keys:
                return action.text()
        return ""
