"""書き出したあとの導線（G-4）。

**書き出しても何も起きなかった。** ダイアログで保存先を選んだ直後、
画面は元のままで、どこへ何を書いたのか確かめる手がかりが無い。HTML には
「ブラウザで確認」があるが、PDF と PowerPoint は押しても無反応に見える。

保存先をステータスバーに出し、**「Finder で表示」を添える**。
"""

import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

from hitofude.ui.main_window import NOTICE_MS

pytestmark = pytest.mark.gui


@pytest.fixture
def window(window):
    """書き出す中身が要る。"""
    window.show()
    window.new_note()
    window.editor.setPlainText("# 見出し\n\n本文\n")
    window.flush()
    return window


@pytest.fixture
def revealed(monkeypatch) -> list[list[str]]:
    """Finder を実際に開かずに、渡した引数だけ受け取る。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append(list(args)))
    return calls


def save_to(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )


def cancel_save(monkeypatch) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))


class TestNotice:
    def test_保存先を出す(self, window, monkeypatch, tmp_path: Path) -> None:
        target = tmp_path / "書き出し.md"
        save_to(monkeypatch, target)
        window.export_markdown()
        assert "書き出し.md" in window.statusBar().currentMessage()

    def test_ホームは波線で短くする(self, window, monkeypatch) -> None:
        """**長い絶対パスはステータスバーに収まらない。** 見えないと
        意味がないので、よくある `/Users/名前/` は `~` にする。"""
        target = Path.home() / "hitofude-test-書き出し.md"
        save_to(monkeypatch, target)
        try:
            window.export_markdown()
            assert str(Path.home()) not in window.statusBar().currentMessage()
            assert "~/" in window.statusBar().currentMessage()
        finally:
            target.unlink(missing_ok=True)

    def test_Finderで表示が出る(self, window, monkeypatch, tmp_path: Path) -> None:
        save_to(monkeypatch, tmp_path / "out.md")
        window.export_markdown()
        assert window.reveal_button.isVisible() is True

    def test_書き出す前は出ていない(self, window) -> None:
        assert window.reveal_button.isVisible() is False

    def test_取り消したら出さない(self, window, monkeypatch) -> None:
        cancel_save(monkeypatch)
        window.export_markdown()
        assert window.reveal_button.isVisible() is False

    def test_しばらくすると消える(self, window, monkeypatch, tmp_path: Path) -> None:
        """**知らせは残さない。** 前に書き出したファイルのボタンが
        居座ると、今のノートと関係のないものを指すようになる。"""
        save_to(monkeypatch, tmp_path / "out.md")
        window.export_markdown()
        window.hide_export_notice()
        assert window.reveal_button.isVisible() is False

    def test_消えるまでは知らせと同じ長さ(self, window, monkeypatch, tmp_path: Path) -> None:
        save_to(monkeypatch, tmp_path / "out.md")
        window.export_markdown()
        assert window.export_timer.isSingleShot() is True
        assert window.export_timer.interval() == NOTICE_MS


class TestReveal:
    def test_Finderで開く(self, window, monkeypatch, revealed, tmp_path: Path) -> None:
        target = tmp_path / "out.md"
        save_to(monkeypatch, target)
        window.export_markdown()
        window.reveal_button.click()
        assert revealed == [["open", "-R", str(target)]]

    def test_無いファイルは開かない(self, window, revealed, tmp_path: Path) -> None:
        """書き出したあとに消された場合。Finder に空振りさせない。"""
        window.reveal_in_finder(tmp_path / "無い.md")
        assert revealed == []


class TestFailure:
    """**失敗したら黙らない。** 成功時の導線（G-4）を作った経緯と同じで、
    ディスクフルや権限で書けなかったときに無反応では、書けたのかどうかが
    画面から分からない。"""

    def test_書けない場所なら警告を出す(self, window, monkeypatch, tmp_path: Path) -> None:
        from PySide6.QtWidgets import QMessageBox

        warnings: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a))
        )
        save_to(monkeypatch, tmp_path / "存在しない階層" / "out.md")

        window.export_markdown()

        assert warnings, "警告が出ていない"
        assert window.reveal_button.isVisible() is False  # 成功の導線は出さない

    def test_失敗後も編集を続けられる(self, window, monkeypatch, tmp_path: Path) -> None:
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
        save_to(monkeypatch, tmp_path / "存在しない階層" / "out.md")
        window.export_markdown()

        # 例外で処理が途切れていないこと（後続の書き出しが成功する）
        save_to(monkeypatch, tmp_path / "out.md")
        window.export_markdown()
        assert (tmp_path / "out.md").is_file()


class TestEveryFormat:
    """**4 つとも同じ扱い。** 形式によって導線が有る無いになると、
    「押しても何も起きない」に見えるものが残る。"""

    @pytest.mark.parametrize(
        ("command", "name"),
        [
            ("export_markdown", "out.md"),
            ("export_html", "out.html"),
            ("export_pdf", "out.pdf"),
            ("export_pptx", "out.pptx"),
        ],
    )
    def test_どの形式でも知らせる(self, window, monkeypatch, tmp_path, command, name) -> None:
        save_to(monkeypatch, tmp_path / name)
        getattr(window, command)()
        assert name in window.statusBar().currentMessage()
        assert window.reveal_button.isVisible() is True
