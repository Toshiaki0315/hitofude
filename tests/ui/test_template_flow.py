"""テンプレートと日次ノートの配線（E-4）。

作る・索引に入れる・開く・書き始める場所へキャレットを置く、までが
1 回の操作で終わること。**雛形を選んだのに一覧へ出ない**、**今日のノートが
2 つできる**、が起きやすいので、そこを固定する。
"""

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from hitofude.storage.vault import DAILY_TEMPLATE
from hitofude.ui.main_window import MainWindow
from hitofude.ui.quick_open import Palette

pytestmark = pytest.mark.gui

NOW = datetime(2026, 8, 14, 9, 5)


def put_template(window: MainWindow, name: str, text: str) -> Path:
    path = window.vault.templates_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def titles(window: MainWindow) -> list[str]:
    model = window.note_list.model()
    return [model.index(row).data() for row in range(model.rowCount())]


class TestSeeding:
    def test_起動時に既定の雛形が置かれる(self, window) -> None:
        assert (window.vault.templates_dir / DAILY_TEMPLATE).is_file()

    def test_雛形は一覧に出てこない(self, window) -> None:
        assert "議事録" not in titles(window)


class TestFromTemplate:
    def test_パレットが開く(self, window) -> None:
        assert window.new_from_template() is True
        assert window.findChild(Palette) is not None

    def test_雛形が候補に並ぶ(self, window) -> None:
        assert "議事録" in [item.title for item in window._notes._template_items("")]

    def test_あいまい検索で絞れる(self, window) -> None:
        assert [item.title for item in window._notes._template_items("議")] == ["議事録"]

    def test_雛形が無ければ開かない(self, window, monkeypatch) -> None:
        """置き場所を知らせて終わる。空のパレットを出しても何も選べない。"""
        # 出しっぱなしにするとテストが固まる（モーダル）
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        for path in window.vault.templates():
            path.unlink()

        assert window.new_from_template() is False
        assert window.findChild(Palette) is None

    def test_選ぶとノートができる(self, window) -> None:
        note = window.create_from_template(window.vault.templates_dir / "議事録.md")
        assert note is not None
        assert note.path.is_file()
        assert window.current_note.path == note.path

    def test_一覧に出る(self, window) -> None:
        """索引に入れて `refresh()` するまでが 1 つの操作。"""
        window.create_from_template(window.vault.templates_dir / "議事録.md")
        assert "議事録" in titles(window)

    def test_印が埋まっている(self, window) -> None:
        put_template(window, "日報.md", "# {{date}} の日報\n")
        window.create_from_template(window.vault.templates_dir / "日報.md")
        assert "の日報" in window.editor.toPlainText()
        assert "{{date}}" not in window.editor.toPlainText()

    def test_キャレットが書き始める場所に来る(self, window) -> None:
        put_template(window, "空欄.md", "# 空欄\n\n本文{{cursor}}\n")
        window.create_from_template(window.vault.templates_dir / "空欄.md")
        text = window.editor.toPlainText()
        assert text[window.editor.textCursor().position() :] == "\n"

    def test_印が無ければ本文の先頭(self, window) -> None:
        """ふつうにノートを開いたときと同じ。front matter の前には行かない。"""
        from hitofude.core import frontmatter

        put_template(window, "素.md", "# 素\n")
        window.create_from_template(window.vault.templates_dir / "素.md")
        text = window.editor.toPlainText()
        assert window.editor.textCursor().position() == frontmatter.body_offset(text)

    def test_外のファイルからは作らない(self, window, tmp_path: Path) -> None:
        outside = tmp_path / "秘密.md"
        outside.write_text("# 秘密\n", encoding="utf-8")
        assert window.create_from_template(outside) is None

    def test_選ぶと繋がっている(self, window) -> None:
        """パレットと作成が配線されていること。"""
        window.new_from_template()
        palette = window.findChild(Palette)
        item = next(found for found in window._notes._template_items("") if found.title == "議事録")
        palette.chosen.emit(item)
        assert window.current_note.path.name == "議事録.md"


class TestDailyNote:
    def test_今日のノートができて開く(self, window) -> None:
        note = window.open_daily_note(NOW)
        assert note.path.name == "2026-08-14.md"
        assert window.current_note.path == note.path

    def test_二度押しても増えない(self, window) -> None:
        first = window.open_daily_note(NOW)
        second = window.open_daily_note(NOW)
        assert first.path == second.path
        assert titles(window).count("2026-08-14") == 1

    def test_一覧に出る(self, window) -> None:
        window.open_daily_note(NOW)
        assert "2026-08-14" in titles(window)

    def test_書いた内容を消さない(self, window) -> None:
        window.open_daily_note(NOW)
        window.editor.textCursor().insertText("\n打った行\n")
        window.flush()

        window.open_daily_note(NOW)
        assert "打った行" in window.editor.toPlainText()

    def test_日付を省くと今日になる(self, window) -> None:
        note = window.open_daily_note()
        assert note.path.stem == datetime.now().strftime("%Y-%m-%d")


class TestMenu:
    @pytest.mark.parametrize(
        ("shortcut", "label"),
        [("Ctrl+Shift+N", "テンプレートから新規…"), ("Ctrl+T", "今日のノート")],
    )
    def test_ショートカットが登録されている(self, window, shortcut: str, label: str) -> None:
        found = {
            action.shortcut().toString(): action.text()
            for action in window.actions()
            if action.shortcut().toString()
        }
        assert found.get(shortcut) == label
