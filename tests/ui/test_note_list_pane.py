"""ノート一覧の上に置くヘッダ（ユーザー要望）。

新規ノートがメニューと `Cmd+N` からしか作れなかった。**画面の中にも入口を置く**。
`EditorPane` と同じ形で、一覧をヘッダごと包む。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt

from hitofude.config import Config
from hitofude.theme import DARK, LIGHT
from hitofude.ui.note_list import NoteListView
from hitofude.ui.note_list_pane import NoteListPane

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> NoteListPane:
    widget = NoteListPane(theme=LIGHT)
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestStructure:
    def test_一覧を持っている(self, pane) -> None:
        assert isinstance(pane.note_list, NoteListView)

    def test_一覧が見えている(self, pane) -> None:
        assert pane.note_list.isVisible()

    def test_新規ボタンが見えている(self, pane) -> None:
        assert pane.new_button.isVisible()

    def test_ボタンに説明が付いている(self, pane) -> None:
        """記号だけでは何のボタンか分からない。"""
        assert "新規" in pane.new_button.toolTip()

    def test_ショートカットも案内する(self, pane) -> None:
        assert "Cmd+N" in pane.new_button.toolTip()

    def test_一覧より細くならない(self, pane) -> None:
        from hitofude.ui.panes import NOTE_LIST_MIN_WIDTH

        assert pane.minimumWidth() >= NOTE_LIST_MIN_WIDTH


class TestButton:
    def test_押すと知らせが飛ぶ(self, pane, qtbot) -> None:
        with qtbot.waitSignal(pane.new_note_requested, timeout=1000):
            qtbot.mouseClick(pane.new_button, Qt.MouseButton.LeftButton)

    def test_自分ではノートを作らない(self, pane, qtbot) -> None:
        """作るのは `MainWindow` の仕事。ここは入口を置くだけ。"""
        assert not hasattr(pane, "vault")


class TestTheme:
    def test_テーマを変えられる(self, pane) -> None:
        pane.set_theme(DARK)
        assert pane.note_list.isVisible()

    def test_ダークでも描画で落ちない(self, pane) -> None:
        from PySide6.QtGui import QColor, QImage

        pane.set_theme(DARK)
        pane.resize(280, 400)
        image = QImage(pane.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("black"))
        pane.render(image)


class TestInWindow:
    """`MainWindow` に組み込んだときの振る舞い。"""

    @pytest.fixture
    def window(self, qtbot, tmp_path: Path):
        from hitofude.ui.main_window import MainWindow

        settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "HitofudeNotes"
        marker = config.vault_path / ".hitofude" / "seeded"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("test", encoding="utf-8")

        widget = MainWindow(config)
        qtbot.addWidget(widget)
        widget.show()
        yield widget
        widget.close()

    def test_3ペインの2番目に入っている(self, window) -> None:
        assert window.centralWidget().widget(1) is window.note_list_pane

    def test_note_listは今まで通り取れる(self, window) -> None:
        assert window.note_list is window.note_list_pane.note_list

    def test_ボタンでノートが増える(self, window, qtbot) -> None:
        before = window.note_list.model().rowCount()
        qtbot.mouseClick(window.note_list_pane.new_button, Qt.MouseButton.LeftButton)
        assert window.note_list.model().rowCount() == before + 1

    def test_ボタンで作ったノートが開く(self, window, qtbot) -> None:
        qtbot.mouseClick(window.note_list_pane.new_button, Qt.MouseButton.LeftButton)
        assert window.current_note is not None
        assert window.current_note.title == "無題"

    def test_ボタンで作ると一覧でも選ばれる(self, window, qtbot) -> None:
        qtbot.mouseClick(window.note_list_pane.new_button, Qt.MouseButton.LeftButton)
        selected = window.note_list.current_path()
        assert selected == window.current_note.path.relative_to(window.vault.root)

    def test_Cmd_1などの表示切り替えは今まで通り(self, window) -> None:
        """隠す対象はヘッダごとのペイン。"""
        window.toggle_note_list()
        assert window.note_list_pane.isHidden()
        window.toggle_note_list()
        assert not window.note_list_pane.isHidden()

    def test_テーマ切り替えが届く(self, window) -> None:
        from hitofude.theme import ThemeMode

        window.theme_watcher.set_mode(ThemeMode.DARK)
        assert window.note_list.isVisible()
