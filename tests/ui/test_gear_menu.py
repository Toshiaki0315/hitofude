"""メニューを開く歯車（ユーザー要望）。

置き場は**ステータスバーの右端**。書式ツールバーは Cmd+3 で隠せるので、
そこに置くと設定への入口ごと消える（ユーザー指摘）。ステータスバーは
常に見えている。

表示の切り替えとモードには**チェック印**を付け、今どうなっているかを
メニューを開くだけで分かるようにする（ユーザー要望）。
"""

import pytest
from PySide6.QtWidgets import QToolButton

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def gear_menu(window: MainWindow):
    return window.menu_button.menu()


def action(window: MainWindow, label: str):
    return window.menu_actions[label]


class TestPlacement:
    def test_歯車はステータスバーにいる(self, window) -> None:
        button = window.menu_button
        assert isinstance(button, QToolButton)
        assert button.parent() is window.statusBar()

    def test_書式ツールバーを隠しても歯車は残る(self, window) -> None:
        """ユーザー指摘の再発防止。入口が消えると設定に戻れない。"""
        window.toggle_toolbar()
        assert not window._pane.toolbar_visible()
        assert window.menu_button.isVisibleTo(window.statusBar())

    def test_押した瞬間に開く(self, window) -> None:
        assert window.menu_button.popupMode() is QToolButton.ToolButtonPopupMode.InstantPopup

    def test_アイコンがある(self, window) -> None:
        assert not window.menu_button.icon().isNull()

    def test_ツールバーに歯車はもう無い(self, window) -> None:
        assert not hasattr(window._pane.toolbar, "menu_button")


class TestMenuContents:
    def test_主要な項目が入っている(self, window) -> None:
        labels = [a.text() for a in gear_menu(window).actions() if a.text()]
        assert "環境設定…" in labels
        assert "サイドバー" in labels
        assert "ショートカット一覧" in labels

    def test_メニューバーと同じアクションを使う(self, window) -> None:
        """別に作るとショートカット表示や状態が二重管理になる。"""
        registered = set(map(id, window.actions()))
        for entry in gear_menu(window).actions():
            if entry.text():
                assert id(entry) in registered, entry.text()


class TestViewChecks:
    """表示されているものに左側のチェックを入れる（ユーザー要望）。"""

    @pytest.mark.parametrize(
        "label", ["サイドバー", "ノートリスト", "書式ツールバー", "バックリンク"]
    )
    def test_表示の項目はチェック可能(self, window, label) -> None:
        assert action(window, label).isCheckable()

    def test_開いた時点の状態が印になる(self, window) -> None:
        gear_menu(window).aboutToShow.emit()
        assert action(window, "サイドバー").isChecked()
        assert action(window, "ノートリスト").isChecked()

    def test_隠すとチェックが外れる(self, window) -> None:
        window.toggle_sidebar()
        gear_menu(window).aboutToShow.emit()
        assert not action(window, "サイドバー").isChecked()

    def test_ツールバーの状態も追従する(self, window) -> None:
        window.toggle_toolbar()
        gear_menu(window).aboutToShow.emit()
        assert not action(window, "書式ツールバー").isChecked()

    def test_バックリンクの開閉も追従する(self, window) -> None:
        before = window._pane.backlinks.expanded()
        window.toggle_backlinks()
        gear_menu(window).aboutToShow.emit()
        assert action(window, "バックリンク").isChecked() is (not before)


class TestModeChecks:
    """選ばれているモードに左側のチェックを入れる（ユーザー要望）。"""

    @pytest.mark.parametrize(
        "label", ["ソースモード（Raw）", "フォーカスモード", "タイプライタモード"]
    )
    def test_モードの項目はチェック可能(self, window, label) -> None:
        assert action(window, label).isCheckable()

    def test_Rawに入るとチェックが付く(self, window) -> None:
        window._editor.set_source_mode(True)
        gear_menu(window).aboutToShow.emit()
        assert action(window, "ソースモード（Raw）").isChecked()
        assert not action(window, "フォーカスモード").isChecked()

    def test_メニューバー側を開いても同じ印が出る(self, window) -> None:
        """同じアクションなので、どちらから見ても状態は 1 つ。"""
        window._editor.set_focus_mode(True)
        for menu in window.menuBar().findChildren(type(gear_menu(window))):
            if any(a.text() == "フォーカスモード" for a in menu.actions()):
                menu.aboutToShow.emit()
        assert action(window, "フォーカスモード").isChecked()


class TestLeftPlacement:
    """歯車は左端・バーは高く（ユーザー指摘）。右端は角に埋もれて見えにくい。"""

    def test_歯車はバーの左側にいる(self, window) -> None:
        window.resize(1000, 500)
        window.show()
        bar = window.statusBar()
        assert window.menu_button.x() < bar.width() / 4

    def test_バーに高さがある(self, window) -> None:
        from hitofude.ui.status_bar import STATUS_BAR_HEIGHT

        window.show()
        assert window.statusBar().height() >= STATUS_BAR_HEIGHT

    def test_通知が出ても歯車は隠れない(self, window) -> None:
        """Qt の showMessage は左側のウィジェットを隠す。専用ラベルなら
        隠れない（この改修の理由）。"""
        window.show()
        window.notify("書き出しました")
        assert window.menu_button.isVisibleTo(window.statusBar())
        assert window.statusBar().currentMessage() == ""  # showMessage を使っていない


class TestNotify:
    """一時通知。showMessage の置き換え（歯車を左に置くため）。"""

    def test_通知が読める(self, window) -> None:
        window.notify("3 件を取り込みました")
        assert "3 件" in window.notice()

    def test_時間が経つと消える(self, window, qtbot) -> None:
        window.notify("すぐ消える", ms=50)
        qtbot.wait_until(lambda: window.notice() == "", timeout=2000)


class TestFrameless:
    def test_歯車に枠を描かない(self, window) -> None:
        """ユーザー要望。部分的な QSS だけ当てると、環境によって
        スタイル既定の枠が出る。境界なしの明示を固定する。"""
        sheet = window.menu_button.styleSheet()
        assert "border: none" in sheet
