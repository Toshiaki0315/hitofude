"""`[[ノート名]]` を `Cmd+クリック` で開く（E-6 / ADR-0011）。

**無ければ作る。** 書いた時点ではまだ無いノートを指すのがふつうで、
「押しても何も起きない」だと、作るために一覧へ戻る手間が要る。

判定は `core/wikilink.py` と `core/activation.py`（GUI 非依存）。ここは
名前を実際のノートへ繋ぐところと、その副作用を見る。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.ui.main_window import MainWindow

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
    note = window.vault.create(title, f"# {title}\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return note.path


def titles(window: MainWindow) -> list[str]:
    model = window.note_list.model()
    return [model.index(row).data() for row in range(model.rowCount())]


class TestOpenExisting:
    def test_あるノートを開く(self, window) -> None:
        path = make_note(window, "会議メモ")
        assert window.activate_note("会議メモ") == path
        assert window.current_note.path == path

    def test_一覧の選択も動く(self, window) -> None:
        """開いたノートが一覧で選ばれていないと、今どこに居るか分からない。"""
        make_note(window, "会議メモ")
        window.activate_note("会議メモ")
        assert window.note_list.currentIndex().data() == "会議メモ"

    def test_大小を無視して届く(self, window) -> None:
        make_note(window, "Weekly Report")
        assert window.activate_note("weekly report") is not None

    def test_前後の空白は無視(self, window) -> None:
        make_note(window, "会議メモ")
        assert window.activate_note(" 会議メモ ") is not None

    def test_ノートは増えない(self, window) -> None:
        make_note(window, "会議メモ")
        before = len(titles(window))
        window.activate_note("会議メモ")
        assert len(titles(window)) == before


class TestCreateMissing:
    """ADR-0011: 行き先が無ければ作る。"""

    def test_無ければ作る(self, window) -> None:
        path = window.activate_note("まだ無いノート")
        assert path is not None
        assert path.is_file()

    def test_見出しが入っている(self, window) -> None:
        """開いた直後に題名が決まっている（一覧にも出る）。"""
        window.activate_note("まだ無いノート")
        assert "# まだ無いノート" in window.editor.toPlainText()

    def test_開いて編集できる(self, window) -> None:
        window.activate_note("まだ無いノート")
        assert window.current_note.path.name == "まだ無いノート.md"

    def test_一覧に出る(self, window) -> None:
        window.activate_note("まだ無いノート")
        assert "まだ無いノート" in titles(window)

    def test_二度押しても増えない(self, window) -> None:
        """1 度目で作られ、2 度目はそれが開く。"""
        first = window.activate_note("まだ無いノート")
        second = window.activate_note("まだ無いノート")
        assert first == second
        assert titles(window).count("まだ無いノート") == 1

    def test_空の名前では作らない(self, window) -> None:
        before = len(titles(window))
        assert window.activate_note("   ") is None
        assert len(titles(window)) == before


class TestWiring:
    def test_エディタからの合図で開く(self, window) -> None:
        """`Cmd+クリック` の受け口が繋がっていること。"""
        path = make_note(window, "会議メモ")
        window.editor.note_activated.emit("会議メモ")
        assert window.current_note.path == path

    def test_書きかけの内容を保存してから移る(self, window) -> None:
        """デバウンス待ちの文字を落とさない。"""
        source = make_note(window, "元のノート")
        make_note(window, "会議メモ")
        window.open_note(source)
        window.editor.textCursor().insertText("\n[[会議メモ]]\n")

        window.activate_note("会議メモ")
        assert "[[会議メモ]]" in source.read_text(encoding="utf-8")

    def test_戻れる(self, window) -> None:
        """`Cmd+[` で元のノートへ戻れる（C-8 の履歴に積まれている）。"""
        source = make_note(window, "元のノート")
        make_note(window, "会議メモ")
        window.open_note(source)

        window.activate_note("会議メモ")
        window.open_previous_note()
        assert window.current_note.path == source
