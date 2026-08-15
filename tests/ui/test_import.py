"""資料の取り込み（F-2）。

「ファイル」→「読み込む…」で PDF を選ぶと、**新しいノートになって開く**。
もらった資料を Markdown にして書き足す、という使い方（TASKS.md の F 群）。

**元のファイルは触らない。** 読むだけで、移動も複製もしない。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hitofude.config import Config
from hitofude.editor.exporter import write_pdf
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui

NOTE = "# 四半期の振り返り\n\n本日の議題は **予算** です。\n"


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


@pytest.fixture(autouse=True)
def notice(monkeypatch) -> list[str]:
    """読めなかったときの知らせ。**出しっぱなしにするとテストが固まる。**"""
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a, **k: shown.append(text))
    return shown


@pytest.fixture
def sample(qapp, tmp_path: Path) -> Path:
    return write_pdf(tmp_path / "四半期資料.pdf", NOTE)


def choose(monkeypatch, path: Path | None) -> None:
    """ファイル選択の結果を差し替える（開くとモーダルで止まる）。"""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(path) if path else "", "")
    )


def titles(window: MainWindow) -> list[str]:
    model = window.note_list.model()
    return [model.index(row).data() for row in range(model.rowCount())]


class TestImport:
    def test_ノートができて開く(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        path = window.import_document()
        assert path is not None
        assert window.current_note.path == path

    def test_題名はファイル名(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        assert window.import_document().name == "四半期資料.md"

    def test_一覧に出る(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        window.import_document()
        assert "四半期資料" in titles(window)

    def test_本文が入っている(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        window.import_document()
        assert "本日の議題" in window.editor.toPlainText()

    def test_元のファイルを触らない(self, window, sample, monkeypatch) -> None:
        before = sample.read_bytes()
        choose(monkeypatch, sample)
        window.import_document()
        assert sample.read_bytes() == before

    def test_やめれば何も起きない(self, window, monkeypatch) -> None:
        choose(monkeypatch, None)
        before = len(titles(window))
        assert window.import_document() is None
        assert len(titles(window)) == before

    def test_読めないファイルは知らせる(self, window, notice, monkeypatch, tmp_path) -> None:
        """**ノートは作らない。** 空のノートが増えるほうが困る。"""
        broken = tmp_path / "壊れた.pdf"
        broken.write_text("これは PDF ではありません", encoding="utf-8")
        choose(monkeypatch, broken)

        before = len(titles(window))
        assert window.import_document() is None
        assert notice
        assert len(titles(window)) == before

    def test_書きかけの内容を保存してから移る(self, window, sample, monkeypatch) -> None:
        note = window.vault.create("元のノート", "# 元のノート\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)
        window.editor.textCursor().insertText("\n打った行\n")

        choose(monkeypatch, sample)
        window.import_document()
        assert "打った行" in note.path.read_text(encoding="utf-8")


class TestMenu:
    def test_メニューにある(self, window) -> None:
        assert "読み込む…" in [action.text() for action in window.actions()]

    def test_ショートカットは付けない(self, window) -> None:
        """ファイルを選ぶ操作で、急いで押すものではない。"""
        for action in window.actions():
            if action.text() == "読み込む…":
                assert action.shortcut().toString() == ""
