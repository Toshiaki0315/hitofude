"""一覧の右クリックに操作を足す（ユーザー要望）。

今まではピン留め / 名前を変更 / ゴミ箱へ移動だけだった。よく要る 3 つを
足す。**どれも一覧から手が届かないと、Finder を開くか手作業になる。**
"""

import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def revealed(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append(list(args)))
    return calls


def make_note(window: MainWindow, title: str, body: str = "本文\n") -> Path:
    note = window.vault.create(title, f"# {title}\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return note.path


def labels(window: MainWindow, path: Path) -> list[str]:
    menu = window.context_menu_for(path.relative_to(window.vault.root))
    try:
        return [action.text() for action in menu.actions() if action.text()]
    finally:
        menu.deleteLater()


class TestMenu:
    def test_3つとも出る(self, window) -> None:
        found = labels(window, make_note(window, "メモ"))
        for label in ("Finder で表示", "複製", "リンクをコピー"):
            assert label in found

    def test_ゴミ箱では出さない(self, window) -> None:
        """ゴミ箱の中身は「戻す」か「完全に削除」だけ（G-3 の作法）。"""
        from hitofude.ui.sidebar import TRASH

        trashed = window.vault.trash(make_note(window, "捨てた"))
        window.set_filter(TRASH)
        found = labels(window, trashed)
        assert "複製" not in found
        assert "リンクをコピー" not in found


class TestReveal:
    def test_ノートを選んだ状態で開く(self, window, revealed) -> None:
        path = make_note(window, "メモ")
        window.reveal_note(path)
        assert revealed == [["open", "-R", str(path)]]


class TestDuplicate:
    def test_複製ができる(self, window) -> None:
        path = make_note(window, "議事録のひな形", "参加者:\n決めたこと:\n")
        copy = window.duplicate_note(path)

        assert copy is not None
        assert copy != path
        assert copy.is_file()
        assert path.is_file()  # 元は残る

    def test_中身をそのまま写す(self, window) -> None:
        path = make_note(window, "ひな形", "参加者:\n決めたこと:\n")
        copy = window.duplicate_note(path)
        assert "決めたこと:" in copy.read_text(encoding="utf-8")

    def test_名前が衝突しない(self, window) -> None:
        path = make_note(window, "ひな形")
        first = window.duplicate_note(path)
        second = window.duplicate_note(path)
        assert first != second

    def test_見出しも新しい名前に揃える(self, window) -> None:
        """**題名は本文の見出し**（`with_title`）。写しただけだと、一覧に
        同じ名前が 2 つ並んで見分けが付かない。"""
        from hitofude.core.document import title_of

        path = make_note(window, "ひな形")
        copy = window.duplicate_note(path)
        assert title_of(copy.read_text(encoding="utf-8"), "無題") == copy.stem

    def test_一覧に出る(self, window) -> None:
        path = make_note(window, "ひな形")
        before = window.note_list.model().rowCount()
        window.duplicate_note(path)
        assert window.note_list.model().rowCount() == before + 1

    def test_複製を開く(self, window) -> None:
        """作ったら開く（新規ノートと同じ）。すぐ書き始められる。"""
        path = make_note(window, "ひな形")
        copy = window.duplicate_note(path)
        assert window.current_note is not None
        assert window.current_note.path == copy


class TestCopyLink:
    def test_二重括弧の形でコピーする(self, window) -> None:
        path = make_note(window, "会議メモ")
        window.copy_note_link(path)
        assert QApplication.clipboard().text() == "[[会議メモ]]"

    def test_知らせを出す(self, window) -> None:
        """クリップボードは目に見えない。入ったことを伝える。"""
        window.copy_note_link(make_note(window, "会議メモ"))
        assert window.notice()


class TestRegisterTemplate:
    """一覧の右クリック → テンプレートに登録（ユーザー要望）。"""

    def make_note(self, window, title="打合せ", body="# 打合せ\n\n- 日時: {{date}}\n"):
        note = window.vault.create(title, body)
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        return note

    def test_メニューに項目がある(self, window) -> None:
        note = self.make_note(window)
        relative = note.path.relative_to(window.vault.root)
        labels = [a.text() for a in window.context_menu_for(relative).actions()]
        assert "テンプレートに登録…" in labels

    def test_ゴミ箱では出さない(self, window) -> None:
        from hitofude.ui.sidebar import TRASH

        note = self.make_note(window)
        trashed = window.vault.trash(note.path)
        window.set_filter(TRASH)
        relative = trashed.relative_to(window.vault.root)
        labels = [a.text() for a in window.context_menu_for(relative).actions()]
        assert "テンプレートに登録…" not in labels

    def test_名前を付けて登録できる(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        note = self.make_note(window)
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("会議の雛形", True))
        )
        target = window.register_template(note.path)
        assert target is not None
        assert target in window.vault.templates()
        assert "登録しました" in window.notice() or "会議の雛形" in window.notice()

    def test_やめれば何もしない(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        note = self.make_note(window)
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
        )
        before = window.vault.templates()  # 同梱の雛形が最初から入っている
        assert window.register_template(note.path) is None
        assert window.vault.templates() == before  # 増えていない

    def test_同名は確認してから上書き(self, window, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        from hitofude.ui import note_actions as module

        note = self.make_note(window)
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("雛形", True))
        )
        window.register_template(note.path)

        asked = []
        monkeypatch.setattr(
            module.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.No),
        )
        first = (window.vault.templates_dir / "雛形.md").read_text(encoding="utf-8")
        window.register_template(note.path)
        assert asked, "上書きの確認が出ていない"
        assert (window.vault.templates_dir / "雛形.md").read_text(encoding="utf-8") == first
