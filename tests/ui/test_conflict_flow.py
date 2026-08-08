"""競合と外部削除のときの分岐（spec §7.5）。

**このアプリで最も避けたい事故に直結する経路**なのに、モーダルが挟まるため
テストが無かった（監査で判明）。ダイアログの応答を差し替えて、
どの選択でも書いたものが残ることを見る。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from hitofude.config import Config
from hitofude.ui.conflict_dialog import ConflictDialog, Resolution
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")

    widget = MainWindow(config)
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def opened_note(window: MainWindow, body: str = "もとの本文\n") -> Path:
    note = window.vault.create("競合するノート", f"# 競合するノート\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    window.open_note(note.path)
    return note.path


def answer_with(monkeypatch, resolution: Resolution) -> None:
    """競合ダイアログの応答を差し替える。"""
    monkeypatch.setattr(ConflictDialog, "exec", lambda self: 0)
    monkeypatch.setattr(ConflictDialog, "resolution", property(lambda self: resolution))


def make_conflict(window: MainWindow, path: Path) -> None:
    """外部で書き換えたうえで、こちらにも未保存の編集を作る。"""
    import time

    time.sleep(0.01)
    path.write_text("# 競合するノート\n\n外部で書いた内容\n", encoding="utf-8")
    # **末尾に足す。** 先頭に入れると見出しが変わり、保存時に改名されて
    # このテストが見たい競合とは別の話になる
    window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
    window.editor.textCursor().insertText("こちらで書いた内容")


class TestConflict:
    def test_自分の版を選ぶと自分の内容が残る(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.TAKE_MINE)

        window.flush()
        assert "こちらで書いた内容" in path.read_text(encoding="utf-8")

    def test_外部を選ぶと外部の内容になる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.TAKE_EXTERNAL)

        window.flush()
        assert "外部で書いた内容" in path.read_text(encoding="utf-8")

    def test_外部を選ぶと画面も外部の内容になる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.TAKE_EXTERNAL)

        window.flush()
        assert "外部で書いた内容" in window.editor.toPlainText()

    def test_両方残すと別ファイルができる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.KEEP_BOTH)

        window.flush()
        kept = [p for p in window.vault.root.glob("*.md") if "競合" in p.name and p != path]
        assert kept, "別名のファイルができていない"

    def test_両方残すとどちらの内容も消えない(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.KEEP_BOTH)

        window.flush()
        everything = "".join(p.read_text(encoding="utf-8") for p in window.vault.root.glob("*.md"))
        assert "外部で書いた内容" in everything
        assert "こちらで書いた内容" in everything

    def test_閉じるだけなら何も書かない(self, window, monkeypatch) -> None:
        """ダイアログを閉じただけで上書きしない。"""
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.CANCEL)

        window.flush()
        assert "外部で書いた内容" in path.read_text(encoding="utf-8")

    def test_聞けないときは両方残す(self, window) -> None:
        """終了処理からはモーダルを開けない。書いたものを失わない側に倒す。"""
        path = opened_note(window)
        make_conflict(window, path)

        window.flush(interactive=False)
        everything = "".join(p.read_text(encoding="utf-8") for p in window.vault.root.glob("*.md"))
        assert "こちらで書いた内容" in everything
        assert "外部で書いた内容" in everything


class TestExternalDelete:
    def test_作り直すと内容が戻る(self, window, monkeypatch) -> None:
        path = opened_note(window, "消される前の本文\n")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        path.unlink()
        window._on_note_deleted(path)
        assert path.is_file()
        assert "消される前の本文" in path.read_text(encoding="utf-8")

    def test_作り直さないなら閉じる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_note_deleted(path)
        assert window.current_note is None
        assert window.editor.toPlainText() == ""

    def test_索引からも消える(self, window, monkeypatch) -> None:
        path = opened_note(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_external_change(_deleted_kind(), path)
        assert all(row.title != "競合するノート" for row in window.vault_index.notes())


def _deleted_kind():
    from hitofude.storage.watcher import ChangeKind

    return ChangeKind.DELETED
