"""ポップアップメニューの文字を少し大きくする（ユーザー要望）。

一覧の並び順、一覧の右クリック、サイドバーの右クリック。**どれも押す前に
読むもの**で、既定の大きさでは小さかった。

macOS の画面上部のメニューバーは OS が描くので、こちらからは変えられない。
変えられるのは、アプリの中で開くポップアップだけ。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.ui.icons import MENU_FONT_STEP
from hitofude.ui.main_window import MainWindow
from hitofude.ui.note_list_pane import NoteListPane
from hitofude.ui.sidebar import ALL, TRASH

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


def bigger_than(menu, widget) -> bool:
    return menu.font().pointSizeF() == pytest.approx(widget.font().pointSizeF() + MENU_FONT_STEP)


class TestStep:
    def test_2ポイント大きくする(self) -> None:
        assert MENU_FONT_STEP == 2


class TestTooltips:
    """ボタンに乗せたときの説明も同じだけ大きくする（ユーザー要望）。

    **ツールチップはアプリ全体で 1 つ**の設定を持つ（`QToolTip.setFont`）。
    ボタンごとに当てて回る必要はないし、当てて回ると当て漏れる。
    """

    def test_2ポイント大きい(self, qapp) -> None:
        from PySide6.QtWidgets import QToolTip

        from hitofude.app import apply_chrome_font

        apply_chrome_font(qapp)
        expected = qapp.font().pointSizeF() + MENU_FONT_STEP
        assert QToolTip.font().pointSizeF() == pytest.approx(expected)

    def test_起動時に当たっている(self, qapp) -> None:
        """`create_application()` を通れば設定済みになっていること。"""
        from PySide6.QtWidgets import QToolTip

        from hitofude.app import create_application

        app = create_application([])
        expected = app.font().pointSizeF() + MENU_FONT_STEP
        assert QToolTip.font().pointSizeF() == pytest.approx(expected)


class TestMenus:
    def test_並び順のメニュー(self, qtbot) -> None:
        pane = NoteListPane()
        qtbot.addWidget(pane)
        assert bigger_than(pane.sort_button.menu(), pane)

    def test_一覧の右クリック(self, window) -> None:
        note = window.vault.create("メモ", "# メモ\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()

        menu = window.context_menu_for(note.path.relative_to(window.vault.root))
        try:
            assert bigger_than(menu, window)
        finally:
            menu.deleteLater()

    def test_サイドバーの右クリック(self, window) -> None:
        menu = window.sidebar_menu_for(TRASH)
        try:
            assert bigger_than(menu, window)
        finally:
            menu.deleteLater()

    def test_出さないメニューには効かない(self, window) -> None:
        """ゴミ箱以外はメニュー自体を出さない（G-3）。ここは変えない。"""
        assert window.sidebar_menu_for(ALL) is None
