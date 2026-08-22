"""ゴミ箱 × サブフォルダの穴（コードレビュー指摘 3 件）。

K-5 でゴミ箱は階層を保つようになった（`仕事/会議.md` は
`.trash/仕事/会議.md` へ入る）が、**ゴミ箱を平らだと思っている場所が
残っていた**。3 件とも「直下しか見ない」ことが原因。

1. 編集中のノートを捨てると、打ちかけの内容が保存されずに消える
2. サブフォルダから捨てたノートを 1 件だけ完全削除できない
3. サブフォルダから捨てたノートしか無いと「ゴミ箱を空にする」が押せない
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import TRASH

pytestmark = pytest.mark.gui


@pytest.fixture
def answer_yes(monkeypatch) -> list[str]:
    asked: list[str] = []

    def question(_parent, _title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    return asked


@pytest.fixture(autouse=True)
def notice(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, _t, text, *a, **k: shown.append(text)
    )
    return shown


def note_in(window: MainWindow, folder: str, title: str) -> Path:
    """`folder/` の中にノートを作って索引に入れる。"""
    if not (window.vault.root / folder).is_dir():
        window.vault.create_folder(folder)
    note = window.vault.create(title, f"# {title}\n\n本文\n", folder=window.vault.root / folder)
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return note.path


class TestPendingEdit:
    """**打ちかけを捨てない。**

    自動保存は打ち終わって 0.8 秒で走る。打った直後に `Cmd+Delete` を
    押すと、まだ書かれていない内容ごとゴミ箱へ行き、戻しても消えている。
    """

    def open_and_type(self, window: MainWindow, path: Path, text: str) -> None:
        window.open_note(path)
        cursor = window.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)  # 日本語は keyClicks を通さない（CLAUDE.md）

    def test_打ちかけの内容がゴミ箱に入る(self, window) -> None:
        path = note_in(window, "仕事", "会議")
        self.open_and_type(window, path, "\n打ちかけの一行\n")
        assert window.trash_current() is True

        moved = window.vault.trash_dir / "仕事" / path.name
        assert "打ちかけの一行" in moved.read_text(encoding="utf-8")

    def test_保存で改名されても取り残さない(self, window) -> None:
        """保存は見出しに合わせてファイル名を変える（K-1）。捨てる前に
        保存する以上、**捨てる相手は保存後のパス**でなければならない。"""
        path = note_in(window, "仕事", "会議")
        window.open_note(path)
        cursor = window.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText("# 打ち直した題名\n\n本文\n")
        window.trash_current()

        assert list((window.vault.root / "仕事").glob("*.md")) == []
        moved = list((window.vault.trash_dir / "仕事").glob("*.md"))
        assert len(moved) == 1
        assert "打ち直した題名" in moved[0].read_text(encoding="utf-8")


class TestDeleteOneInFolder:
    def test_フォルダの中の1件を完全に削除できる(self, window, answer_yes) -> None:
        path = note_in(window, "仕事", "会議")
        moved = window.vault.trash(path)
        assert window.delete_permanently(moved) is True
        assert not moved.exists()

    def test_空になったフォルダは残さない(self, window, answer_yes) -> None:
        """ゴミ箱の中の空フォルダは戻す先も無く、ただの残骸
        （`restore` / `purge_trash` と同じ後始末をする）。"""
        path = note_in(window, "仕事", "会議")
        window.delete_permanently(window.vault.trash(path))
        assert not (window.vault.trash_dir / "仕事").exists()

    def test_ゴミ箱の外は消せないまま(self, window, answer_yes) -> None:
        path = note_in(window, "仕事", "会議")
        assert window.delete_permanently(path) is False
        assert path.exists()


class TestEmptyTrashWithFolders:
    def test_フォルダの中だけでも押せる(self, window) -> None:
        """空のときは押せない（G-3）。**押せない理由が中身の場所であっては
        いけない。** サブフォルダから捨てたノートも「中身」である。"""
        window.vault.trash(note_in(window, "仕事", "会議"))
        menu = window.sidebar_menu_for(TRASH)
        try:
            empty = [action for action in menu.actions() if "空にする" in action.text()]
            assert [action.isEnabled() for action in empty] == [True]
        finally:
            menu.deleteLater()

    def test_フォルダの中だけでも空にできる(self, window, answer_yes) -> None:
        path = note_in(window, "仕事", "会議")
        moved = window.vault.trash(path)
        assert window.empty_trash() == 1
        assert not moved.exists()

    def test_数は中身で数える(self, window, answer_yes) -> None:
        """フォルダを 1 件と数えると、見せた数と消える数が食い違う。"""
        for title in ("会議", "予算"):
            window.vault.trash(note_in(window, "仕事", title))
        window.empty_trash()
        assert "2" in answer_yes[0]


class TestOutsideVault:
    """境界の外を渡されても落ちない（コードレビュー指摘の後始末）。

    `Vault` が `ValueError` で止めるようになったので、**受け手も知らせて
    終わる**必要がある。素通しにすると画面が落ちる。
    """

    def test_外のファイルは捨てない(self, window, tmp_path) -> None:
        outside = tmp_path / "外のファイル.md"
        outside.write_text("# 外\n", encoding="utf-8")
        assert window.trash_note(outside) is False
        assert outside.exists()

    def test_捨てられなければ知らせる(self, window, tmp_path) -> None:
        outside = tmp_path / "外のファイル.md"
        outside.write_text("# 外\n", encoding="utf-8")
        window.trash_note(outside)
        assert window.notice() == "保管フォルダの中のノートだけ移せます"

    def test_ゴミ箱の外は戻さない(self, window) -> None:
        path = note_in(window, "仕事", "普通のノート")
        assert window.restore_note(path) is None
        assert path.exists()
