"""`[[` の候補に何を渡すか（ユーザー要望）。

判定は `core/notelink.py`、出す仕組みは `editor/editor_widget.py`。
ここは**何を候補にするか**（既存ノートの題名）だけを見る。
"""

import pytest

pytestmark = pytest.mark.gui


class TestInWindow:
    """`MainWindow` から索引を渡す（`[[` の候補は既存ノートの題名）。"""

    def test_既存ノートの題名が出る(self, window) -> None:
        for title in ("会議メモ", "買い物リスト"):
            note = window.vault.create(title, f"# {title}\n")
            window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.new_note()

        window.editor.textCursor().insertText("[[会")
        window.editor.update_tag_completion()
        assert "会議メモ" in window.editor.tag_candidates()

    def test_今開いているノートは出さない(self, window) -> None:
        """**自分へのリンクは意味が無い。** 候補に混ざると選び間違える。"""
        note = window.vault.create("いま開いているノート", "# いま開いているノート\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)

        window.editor.textCursor().insertText("[[いま")
        window.editor.update_tag_completion()
        assert window.editor.tag_candidates() == []

    def test_ゴミ箱のノートは出さない(self, window) -> None:
        note = window.vault.create("捨てたノート", "# 捨てたノート\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.trash_note(note.path)
        window.new_note()

        window.editor.textCursor().insertText("[[捨て")
        window.editor.update_tag_completion()
        assert window.editor.tag_candidates() == []
