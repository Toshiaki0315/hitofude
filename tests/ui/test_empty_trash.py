"""ゴミ箱を今すぐ空にする / 1 件を完全に削除する（G-3）。

今までは**捨ててから 30 日待つしかなかった**。見られたくないノートを
捨てたとき、それは捨てたことにならない。

**消す前に必ず数を見せる**（E-5 の片づけと同じ作法）。取り消せない操作を
黙って走らせない。
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


@pytest.fixture
def answer_no(monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)


@pytest.fixture(autouse=True)
def notice(monkeypatch) -> list[str]:
    """知らせのダイアログを受け取る。出しっぱなしだとテストが固まる。"""
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, _t, text, *a, **k: shown.append(text)
    )
    return shown


def trashed(window: MainWindow, title: str) -> Path:
    note = window.vault.create(title, f"# {title}\n\n本文\n")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return window.vault.trash(note.path)


class TestEmptyTrash:
    def test_中身が消える(self, window, answer_yes) -> None:
        paths = [trashed(window, "あ"), trashed(window, "い")]
        assert window.empty_trash() == 2
        assert not any(path.exists() for path in paths)

    def test_消す前に数を見せる(self, window, answer_yes) -> None:
        trashed(window, "あ")
        trashed(window, "い")
        window.empty_trash()
        assert "2" in answer_yes[0]

    def test_取り消せないと伝える(self, window, answer_yes) -> None:
        """**戻せない操作**。ゴミ箱へ移すときとは書き方を変える。"""
        trashed(window, "あ")
        window.empty_trash()
        assert "戻せません" in answer_yes[0]

    def test_いいえなら消さない(self, window, answer_no) -> None:
        path = trashed(window, "あ")
        assert window.empty_trash() == 0
        assert path.exists()

    def test_空なら聞かずに知らせる(self, window, notice, answer_yes) -> None:
        assert window.empty_trash() == 0
        assert answer_yes == []
        assert notice

    def test_一覧から消える(self, window, answer_yes) -> None:
        trashed(window, "あ")
        window.set_filter(TRASH)
        window.empty_trash()
        model = window.note_list.model()
        assert model.rowCount() == 0


class TestDeleteOne:
    def test_1件だけ消せる(self, window, answer_yes) -> None:
        keep = trashed(window, "残す")
        target = trashed(window, "消す")
        assert window.delete_permanently(target) is True
        assert not target.exists()
        assert keep.exists()

    def test_名前を見せてから消す(self, window, answer_yes) -> None:
        target = trashed(window, "秘密のメモ")
        window.delete_permanently(target)
        assert "秘密のメモ" in answer_yes[0]

    def test_いいえなら消さない(self, window, answer_no) -> None:
        target = trashed(window, "消す")
        assert window.delete_permanently(target) is False
        assert target.exists()

    def test_開いていたら閉じる(self, window, answer_yes) -> None:
        """消したノートを開いたままにすると、次の保存で書き戻ってしまう。"""
        target = trashed(window, "開いているメモ")
        window.set_filter(TRASH)
        window.open_note(target)
        window.delete_permanently(target)
        assert window.current_note is None


class TestMenus:
    def labels(self, window: MainWindow, path: Path) -> list[str]:
        menu = window.context_menu_for(path.relative_to(window.vault.root))
        try:
            return [action.text() for action in menu.actions() if action.text()]
        finally:
            menu.deleteLater()

    def test_ゴミ箱の右クリックに完全に削除が出る(self, window) -> None:
        target = trashed(window, "あ")
        window.set_filter(TRASH)
        assert "完全に削除…" in self.labels(window, target)

    def test_ふつうのノートには出さない(self, window) -> None:
        note = window.vault.create("ふつう", "# ふつう\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        assert "完全に削除…" not in self.labels(window, note.path)

    def test_サイドバーのゴミ箱にメニューが出る(self, window) -> None:
        menu = window.sidebar_menu_for(TRASH)
        assert menu is not None
        try:
            assert "ゴミ箱を空にする…" in [action.text() for action in menu.actions()]
        finally:
            menu.deleteLater()

    def action(self, window: MainWindow):
        menu = window.sidebar_menu_for(TRASH)
        return next(a for a in menu.actions() if a.text() == "ゴミ箱を空にする…")

    def test_空のときは押せない(self, window) -> None:
        """**押してから断らない。** 件数は開く前に分かるので、
        押せない状態で見せる（一覧の「ゴミ箱へ移動」と同じ作法）。"""
        assert self.action(window).isEnabled() is False

    def test_中身があれば押せる(self, window) -> None:
        trashed(window, "あ")
        assert self.action(window).isEnabled() is True

    def test_ゴミ箱以外にはメニューを出さない(self, window) -> None:
        from hitofude.ui.sidebar import ALL

        assert window.sidebar_menu_for(ALL) is None


class TestEmptyNotice:
    """空の一覧に出す案内は、**何を見ているか**で変える（ユーザー指摘）。

    ゴミ箱を見ているのに「右上の ＋ で作れます」と言われても、作った
    ノートはゴミ箱に入らない。お気に入りとタグでも同じことが起きていた。
    """

    def test_ゴミ箱では作り方を案内しない(self, window) -> None:
        window.set_filter(TRASH)
        text = window.note_list_pane.empty_notice_text()
        assert "ゴミ箱" in text
        assert "＋" not in text

    def test_すべてでは作り方を案内する(self, window) -> None:
        from hitofude.ui.sidebar import ALL

        window.set_filter(ALL)
        assert "＋" in window.note_list_pane.empty_notice_text()

    def test_お気に入りでは入れ方を案内する(self, window) -> None:
        from hitofude.ui.sidebar import PINNED

        window.set_filter(PINNED)
        assert "右クリック" in window.note_list_pane.empty_notice_text()

    def test_タグではそのタグの話をする(self, window) -> None:
        from hitofude.ui.sidebar import Filter, FilterKind

        window.set_filter(Filter(FilterKind.TAG, "仕事"))
        # どのタグを見ているのかが分かる（「ノートがありません」だけでは
        # 絞り込みのせいなのか本当に無いのかが読めない）
        assert "仕事" in window.note_list_pane.empty_notice_text()
