"""ポップアップの文字の大きさ。

**ツールチップは +2pt**（押す前に読むもので、既定は小さかった）。

**メニューは OS の大きさのまま**（2026-08-22 に戻した）。本文の右クリックは
Qt が出すネイティブのメニューで、こちらだけ大きいと並べたときに別のアプリの
ように見える（ユーザーの画像）。

macOS の画面上部のメニューバーは OS が描くので、こちらからは変えられない。
変えられるのは、アプリの中で開くポップアップだけ。
"""

import pytest

from hitofude.app import MENU_FONT_STEP
from hitofude.ui.note_list_pane import NoteListPane
from hitofude.ui.sidebar import ALL, TRASH

pytestmark = pytest.mark.gui


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
    """**メニューは OS の大きさに戻した**（ユーザー要望 2026-08-22）。

    本文の右クリックは Qt が出すネイティブのメニューで、こちらだけ +2pt に
    していたため、並べると別のアプリのように見えた（ユーザーの画像）。
    ツールチップの +2pt はそのまま（あちらは比べる相手がいない）。
    """

    def same_as(self, menu, widget) -> bool:
        return menu.font().pointSizeF() == pytest.approx(widget.font().pointSizeF())

    def test_並び順のメニュー(self, qtbot) -> None:
        pane = NoteListPane()
        qtbot.addWidget(pane)
        assert self.same_as(pane.sort_button.menu(), pane)

    def test_一覧の右クリック(self, window) -> None:
        note = window.vault.create("メモ", "# メモ\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()

        menu = window.context_menu_for(note.path.relative_to(window.vault.root))
        try:
            assert self.same_as(menu, window)
        finally:
            menu.deleteLater()

    def test_サイドバーの右クリック(self, window) -> None:
        menu = window.sidebar_menu_for(TRASH)
        try:
            assert self.same_as(menu, window)
        finally:
            menu.deleteLater()

    def test_出さないメニューには効かない(self, window) -> None:
        """ゴミ箱以外はメニュー自体を出さない（G-3）。ここは変えない。"""
        assert window.sidebar_menu_for(ALL) is None
