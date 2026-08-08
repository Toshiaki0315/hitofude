"""起動したら前回のノートを開く（タスク A-1）。

一覧に件数があってもエディタが空のまま開いていた。`Cmd+O` を覚えていれば
困らないが、**開いて即書き始められない**のは毎回効く。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")
    return config


def open_window(qtbot, config: Config) -> MainWindow:
    window = MainWindow(config)
    qtbot.addWidget(window)
    window.show()
    return window


def make_note(window: MainWindow, title: str, body: str = "本文\n") -> Path:
    note = window.vault.create(title, f"# {title}\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return note.path


class TestReopen:
    def test_前回のノートが開く(self, qtbot, config) -> None:
        first = open_window(qtbot, config)
        path = make_note(first, "続きを書くノート")
        first.open_note(path)
        first.close()

        again = open_window(qtbot, config)
        assert again.current_note is not None
        assert again.current_note.path == path

    def test_本文も読み込まれている(self, qtbot, config) -> None:
        first = open_window(qtbot, config)
        path = make_note(first, "続きを書くノート", "きのうの続き\n")
        first.open_note(path)
        first.close()

        again = open_window(qtbot, config)
        assert "きのうの続き" in again.editor.toPlainText()

    def test_一覧の選択も合う(self, qtbot, config) -> None:
        """開いているのに一覧で選ばれていないと、どれを見ているか分からない。"""
        first = open_window(qtbot, config)
        path = make_note(first, "続きを書くノート")
        make_note(first, "別のノート")
        first.open_note(path)
        first.close()

        again = open_window(qtbot, config)
        assert again.note_list.current_path() == path.relative_to(again.vault.root)

    def test_カーソルが本文の先頭にある(self, qtbot, config) -> None:
        """開いた直後に打ち始めても front matter を壊さない。"""
        from hitofude.core import frontmatter

        first = open_window(qtbot, config)
        path = make_note(first, "続きを書くノート")
        first.open_note(path)
        first.close()

        again = open_window(qtbot, config)
        expected = frontmatter.body_offset(again.editor.toPlainText())
        assert again.editor.textCursor().position() == expected

    def test_タイトルにも出る(self, qtbot, config) -> None:
        first = open_window(qtbot, config)
        first.open_note(make_note(first, "続きを書くノート"))
        first.close()

        again = open_window(qtbot, config)
        assert "続きを書くノート" in again.windowTitle()

    def test_未保存の印は付かない(self, qtbot, config) -> None:
        first = open_window(qtbot, config)
        first.open_note(make_note(first, "続きを書くノート"))
        first.close()

        again = open_window(qtbot, config)
        assert not again.windowTitle().startswith("•")


class TestNothingToReopen:
    def test_初回は何も開かない(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        assert window.current_note is None

    def test_消えたノートは開かない(self, qtbot, config) -> None:
        first = open_window(qtbot, config)
        path = make_note(first, "あとで消すノート")
        first.open_note(path)
        first.close()
        path.unlink()

        again = open_window(qtbot, config)
        assert again.current_note is None

    def test_ゴミ箱へ入れたノートは開かない(self, qtbot, config) -> None:
        first = open_window(qtbot, config)
        path = make_note(first, "捨てるノート")
        first.open_note(path)
        first.trash_current()
        first.close()

        again = open_window(qtbot, config)
        assert again.current_note is None

    def test_保管フォルダを変えたら前のノートは開かない(
        self, qtbot, config, tmp_path: Path
    ) -> None:
        """相対パスで覚えているので、移した先の同名ファイルを掴むこともない。

        移した先が空なら使い方ノートが置かれる（既存の振る舞い）。
        ここで見たいのは**前の vault のノートを開かないこと**。
        """
        first = open_window(qtbot, config)
        old = make_note(first, "元の場所のノート")
        first.open_note(old)
        first.close()

        config.vault_path = tmp_path / "別のフォルダ"
        again = open_window(qtbot, config)
        assert again.current_note is None or again.current_note.path != old

    def test_壊れた値でも起動する(self, qtbot, config) -> None:
        """設定ファイルは手で編集できる。読めない値で起動が止まらないこと。"""
        config.settings.setValue("session/last_note", "../../外のファイル.md")
        window = open_window(qtbot, config)
        assert window.current_note is None
        assert window.isVisible()


class TestRecording:
    def test_開いた時点で覚える(self, qtbot, config) -> None:
        """終了時だけに書くと、強制終了で忘れる。"""
        window = open_window(qtbot, config)
        path = make_note(window, "覚えるノート")
        window.open_note(path)
        assert config.last_note == path.relative_to(window.vault.root)

    def test_相対パスで覚える(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.open_note(make_note(window, "覚えるノート"))
        assert config.last_note is not None
        assert not config.last_note.is_absolute()

    def test_ゴミ箱へ入れたら忘れる(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.open_note(make_note(window, "捨てるノート"))
        window.trash_current()
        assert config.last_note is None

    def test_改名に追従する(self, qtbot, config) -> None:
        """保存で見出しが変わるとファイル名も変わる。古い名前を覚えたままにしない。"""
        window = open_window(qtbot, config)
        window.open_note(make_note(window, "元の見出し"))
        window.editor.textCursor().insertText("# 新しい見出し\n\n")
        window.flush()

        assert config.last_note == window.current_note.path.relative_to(window.vault.root)


class TestSeededManual:
    """初回の使い方ノートは今まで通り開く（既存の振る舞いを壊さない）。"""

    def test_初回は使い方ノートが開く(self, qtbot, tmp_path: Path) -> None:
        settings = QSettings(str(tmp_path / "seed.ini"), QSettings.Format.IniFormat)
        fresh = Config(settings)
        fresh.vault_path = tmp_path / "SeedVault"

        window = open_window(qtbot, fresh)
        assert window.current_note is not None
        assert "使い方" in window.current_note.title

    def test_2回目は前回のノートが開く(self, qtbot, tmp_path: Path) -> None:
        settings = QSettings(str(tmp_path / "seed2.ini"), QSettings.Format.IniFormat)
        fresh = Config(settings)
        fresh.vault_path = tmp_path / "SeedVault2"

        first = open_window(qtbot, fresh)
        path = make_note(first, "自分で書いたノート")
        first.open_note(path)
        first.close()

        again = open_window(qtbot, fresh)
        assert again.current_note.path == path
