"""一覧からのノート操作のテスト（ゴミ箱からの復元 / ピン留め）。

`Vault.restore()` は実装もテストも済んでいたのに **UI から一度も呼ばれて
いなかった**。ゴミ箱を開いても中身を眺めるだけで戻せず、30 日で消えていた。
「お気に入り」フィルタも同様に、絞り込みはできるのに**ピン留めする操作が
無く常に空**だった。ここはその行き止まりの回帰テスト。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import ALL, PINNED, TRASH

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")

    widget = MainWindow(config)
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def make_note(window: MainWindow, title: str, body: str = "本文\n") -> Path:
    # タイトルは本文の H1 から導かれる（document.title_of）。
    # ファイル名だけ付けても一覧には出ない
    note = window.vault.create(title, f"# {title}\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return note.path


def titles(window: MainWindow) -> list[str]:
    model = window.note_list.model()
    return [model.index(row).data() for row in range(model.rowCount())]


class TestRestore:
    def test_ゴミ箱から戻せる(self, window) -> None:
        path = make_note(window, "戻すノート")
        trashed = window.vault.trash(path)
        window.refresh()

        restored = window.restore_note(trashed)
        assert restored is not None
        assert restored.parent == window.vault.root
        assert restored.is_file()

    def test_戻すとゴミ箱から消える(self, window) -> None:
        path = make_note(window, "戻すノート")
        trashed = window.vault.trash(path)
        window.restore_note(trashed)
        assert not trashed.exists()

    def test_戻すと一覧に出る(self, window) -> None:
        """索引に入らないと一覧に出ない。ファイルを動かすだけでは足りない。"""
        path = make_note(window, "戻すノート")
        window.trash_note(path)
        assert "戻すノート" not in titles(window)

        window.restore_note(window.vault.trash_dir / "戻すノート.md")
        window.set_filter(ALL)
        assert "戻すノート" in titles(window)

    def test_本文が保たれる(self, window) -> None:
        path = make_note(window, "戻すノート", "# 見出し\n\n**大事な本文**\n")
        restored = window.restore_note(window.vault.trash(path))
        assert "**大事な本文**" in restored.read_text(encoding="utf-8")

    def test_同名が既にあっても上書きしない(self, window) -> None:
        path = make_note(window, "同じ名前", "古いほう\n")
        trashed = window.vault.trash(path)
        make_note(window, "同じ名前", "新しいほう\n")

        restored = window.restore_note(trashed)
        assert restored.name != "同じ名前.md"
        assert "新しいほう" in (window.vault.root / "同じ名前.md").read_text(encoding="utf-8")

    def test_無いファイルを戻してもNone(self, window) -> None:
        assert window.restore_note(window.vault.trash_dir / "居ない.md") is None


class TestPin:
    def test_ピン留めできる(self, window) -> None:
        path = make_note(window, "留めるノート")
        assert window.toggle_pin(path) is True

    def test_もう一度で外れる(self, window) -> None:
        path = make_note(window, "留めるノート")
        window.toggle_pin(path)
        assert window.toggle_pin(path) is False

    def test_お気に入りに出る(self, window) -> None:
        """索引まで届かないとフィルタが空のまま。"""
        path = make_note(window, "留めるノート")
        make_note(window, "留めないノート")

        window.toggle_pin(path)
        window.set_filter(PINNED)
        assert titles(window) == ["留めるノート"]

    def test_外すとお気に入りから消える(self, window) -> None:
        path = make_note(window, "留めるノート")
        window.toggle_pin(path)
        window.toggle_pin(path)
        window.set_filter(PINNED)
        assert titles(window) == []

    def test_本文を変えない(self, window) -> None:
        path = make_note(window, "留めるノート", "# 見出し\n\n**強調**\n")
        window.toggle_pin(path)
        assert "**強調**" in path.read_text(encoding="utf-8")

    def test_開いているノートでも中身が食い違わない(self, window) -> None:
        """ピン留めは front matter を書く。エディタが古い本文のままだと、
        次の保存でピン留めが黙って消える。"""
        path = make_note(window, "開いているノート")
        window.open_note(path)
        window.toggle_pin(path)

        assert window.editor.toPlainText() == path.read_text(encoding="utf-8")

    def test_開いているノートの未保存分を失わない(self, window) -> None:
        path = make_note(window, "開いているノート")
        window.open_note(path)
        window.editor.textCursor().insertText("打ちかけの文字")
        window.toggle_pin(path)

        # 保存で見出しが変わるとファイル名も変わるので、今のパスを見る
        saved = window.current_note.path
        assert "打ちかけの文字" in saved.read_text(encoding="utf-8")
        assert "打ちかけの文字" in window.editor.toPlainText()

    def test_保存で改名されてもピン留めできる(self, window) -> None:
        """`flush()` がファイル名を変えるので、古いパスを掴んだままにしない。"""
        path = make_note(window, "開いているノート")
        window.open_note(path)
        window.editor.textCursor().insertText("# 変わった見出し\n\n")

        assert window.toggle_pin(path) is True
        assert window.current_note.pinned is True

    def test_開いているノートでカーソルが飛ばない(self, window) -> None:
        path = make_note(window, "開いているノート", "一行目\n二行目\n三行目\n")
        window.open_note(path)
        cursor = window.editor.textCursor()
        cursor.setPosition(len(window.editor.toPlainText()) - 3)
        window.editor.setTextCursor(cursor)
        before = window.editor.textCursor().position()

        window.toggle_pin(path)
        assert window.editor.textCursor().position() == before

    def test_無いファイルなら何もしない(self, window) -> None:
        assert window.toggle_pin(window.vault.root / "居ない.md") is False


class TestContextMenu:
    """右クリックで出る項目。フィルタによって中身が変わる。"""

    def labels(self, window, path: Path) -> list[str]:
        menu = window.context_menu_for(path.relative_to(window.vault.root))
        try:
            return [action.text() for action in menu.actions() if action.text()]
        finally:
            menu.deleteLater()

    def test_ゴミ箱では元に戻すを出す(self, window) -> None:
        path = make_note(window, "ノート")
        trashed = window.vault.trash(path)
        window.set_filter(TRASH)
        assert "元に戻す" in self.labels(window, trashed)

    def test_ゴミ箱ではピン留めを出さない(self, window) -> None:
        path = make_note(window, "ノート")
        trashed = window.vault.trash(path)
        window.set_filter(TRASH)
        assert "ピン留め" not in self.labels(window, trashed)

    def test_通常はピン留めを出す(self, window) -> None:
        assert "ピン留め" in self.labels(window, make_note(window, "ノート"))

    def test_留めてあるなら外す表示になる(self, window) -> None:
        path = make_note(window, "ノート")
        window.toggle_pin(path)
        assert "ピン留めを外す" in self.labels(window, path)

    def test_ゴミ箱へ移動も出す(self, window) -> None:
        path = make_note(window, "ノート")
        assert "ゴミ箱へ移動" in self.labels(window, path)

    def test_右クリックが有効になっている(self, window) -> None:
        from PySide6.QtCore import Qt

        assert window.note_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
