"""設定を閉じたあとも一覧の選択が残る（ユーザー報告 2026-08-28）。

**開いているノートと一覧の選択は一致しているべき。** ノートを開いたまま
設定を開いて OK を押すと、一覧の選択だけが消えていた——本文は出ている
のに、どれを見ているのか一覧から分からない。

原因は `note_list.set_line_spacing()` の `reset()`。行の高さを測り直させる
ために要るが、`QAbstractItemView.reset()` は**選択も落とす**。すぐ下の
`set_rows()` は「覚えて戻す」作法を既に持っていた。
"""

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def opened(window):
    for name in ("一枚目", "二枚目", "三枚目"):
        note = window._vault.create(name, f"# {name}\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(window._vault.root / "二枚目.md")
    return window


class TestAfterPreferences:
    def test_選択が残る(self, opened) -> None:
        """**これが本題。** 設定を閉じても選択は消えない。"""
        before = opened.note_list.currentIndex().row()
        assert before >= 0
        opened._apply_preferences()
        assert opened.note_list.currentIndex().row() == before

    def test_開いているノートと一致する(self, opened) -> None:
        """行番号が同じでも、**指しているノートが違えば意味が無い。**

        一覧が持つのは保管フォルダからの相対パス（絶対パスではない）。
        """
        opened._apply_preferences()
        shown = opened.current_note.path.relative_to(opened._vault.root)
        assert opened.note_list.current_path() == shown


class TestLineSpacing:
    """原因そのもの（行間の変更）。"""

    def test_選択を落とさない(self, opened) -> None:
        from hitofude.config import LineSpacing

        path = opened.note_list.current_path()
        opened.note_list.set_line_spacing(LineSpacing.RELAXED)
        assert opened.note_list.current_path() == path

    def test_高さは測り直される(self, opened) -> None:
        """**直しすぎない。** 選択を守るために `reset()` をやめない
        （やめると古い高さのまま残る。この関数がある理由そのもの）。
        """
        from hitofude.config import LineSpacing

        first = opened.note_list.sizeHintForRow(0)
        opened.note_list.set_line_spacing(LineSpacing.RELAXED)
        assert opened.note_list.sizeHintForRow(0) != first
