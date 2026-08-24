"""使っていない添付の片づけ（E-5）。

**手で走らせる。** 起動のたびに自動で動かすと、参照の取りこぼしが
「気づかないうちにファイルが動く」に直結する。件数を見せて、押した
ときだけ動かす。

**消さずにゴミ箱へ移す**ので、間違えても 30 日は戻せる。
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from hitofude.ui import main_window as main_window_module
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def answer_yes(monkeypatch):
    """確認ダイアログで「移す」を押した状態にする。"""
    asked: list[str] = []

    def question(_parent, _title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    return asked


@pytest.fixture
def answer_no(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)


@pytest.fixture(autouse=True)
def notice(monkeypatch) -> list[str]:
    """「片づけるものはありません」の知らせを受け取る。

    **全てのテストに掛ける。** 出しっぱなしにするとモーダルで固まる。
    """
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, _t, text, *a, **k: shown.append(text)
    )
    return shown


def put_attachment(window: MainWindow, name: str) -> Path:
    path = window.vault.attachments_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    return path


class TestCleanup:
    def test_使っていない添付をゴミ箱へ移す(self, window, answer_yes) -> None:
        orphan = put_attachment(window, "迷子.png")
        assert window.cleanup_attachments() == 1
        assert not orphan.exists()

    def test_件数を見せてから移す(self, window, answer_yes) -> None:
        """**押す前に数が分かること。** 黙って動かさない。"""
        put_attachment(window, "迷子1.png")
        put_attachment(window, "迷子2.png")
        window.cleanup_attachments()
        assert "2" in answer_yes[0]

    def test_やめれば動かさない(self, window, answer_no) -> None:
        orphan = put_attachment(window, "迷子.png")
        assert window.cleanup_attachments() == 0
        assert orphan.is_file()

    def test_使っている添付は残る(self, window, answer_yes) -> None:
        used = put_attachment(window, "使用中.png")
        note = window.vault.create("メモ", "# メモ\n\n![](attachments/使用中.png)\n")
        window.vault_index.upsert_note(note, window.vault.root)

        window.cleanup_attachments()
        assert used.is_file()

    def test_片づけるものが無ければ知らせる(self, window, notice) -> None:
        """ダイアログを出さずに終わると、押しても無反応に見える。"""
        assert window.cleanup_attachments() == 0
        assert notice

    def test_書きかけの本文も数える(self, window, answer_yes) -> None:
        """**保存前の参照を見落とすと、貼ったばかりの画像が消える。**"""
        used = put_attachment(window, "貼ったばかり.png")
        note = window.vault.create("メモ", "# メモ\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)
        window.editor.textCursor().insertText("\n![](attachments/貼ったばかり.png)\n")

        window.cleanup_attachments()
        assert used.is_file()

    def test_移した数を返す(self, window, answer_yes) -> None:
        put_attachment(window, "a.png")
        put_attachment(window, "b.png")
        assert window.cleanup_attachments() == 2


class TestMenu:
    def test_メニューにある(self, window) -> None:
        labels = [action.text() for action in window.actions()]
        assert "使っていない添付を片づける…" in labels

    def test_ショートカットは付けない(self, window) -> None:
        """**押し間違いでファイルが動く操作**にキーは割り当てない。"""
        for action in window.actions():
            if action.text() == "使っていない添付を片づける…":
                assert action.shortcut().toString() == ""


class TestWiring:
    def test_呼び出し口が繋がっている(self, window) -> None:
        assert hasattr(main_window_module.MainWindow, "cleanup_attachments")


class TestClosingTwice:
    """`close()` は 2 回来ることがある（明示 + Qt の後片付け）。

    1 度目で索引を閉じているので、2 度目に保存へ入ると閉じた DB を触る。
    **2 度目は何もしない。**
    """

    def test_二度閉じても落ちない(self, window: MainWindow) -> None:
        note = window.vault.create("二度閉じ", "# 二度閉じ\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.open_note(note.path)
        window.editor.insertPlainText("追記\n")
        window.close()
        window.close()

    def test_終了時に索引を待ちすぎない(self, window: MainWindow, monkeypatch) -> None:
        """大きな vault の走査中に閉じても、窓が固まったままにならない。"""
        seen: list[int] = []
        monkeypatch.setattr(
            MainWindow, "wait_for_index_sync", lambda self, ms=30000: (seen.append(ms), True)[1]
        )
        window.close()
        assert seen and seen[0] <= 5000
