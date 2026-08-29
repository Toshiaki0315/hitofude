"""Word 書き出しの入口（U-5）。"""

import pytest

pytestmark = pytest.mark.gui


class TestEntry:
    def test_書き出しメニューにある(self, window) -> None:
        from hitofude.ui.commands import commands

        labels = [c.label for c in commands(window.menuBar())]
        assert "Word…" in labels

    def test_書き出せる(self, window, tmp_path, monkeypatch) -> None:
        from docx import Document

        note = window._vault.create("会議メモ", "# 会議メモ\n\n決めたこと\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_and_select(note.path)

        target = tmp_path / "会議メモ.docx"
        monkeypatch.setattr(
            "hitofude.ui.export_actions.QFileDialog.getSaveFileName",
            lambda *a, **k: (str(target), ""),
        )
        assert window.export_docx() == target
        assert any("決めたこと" in p.text for p in Document(str(target)).paragraphs)
