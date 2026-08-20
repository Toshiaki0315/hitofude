"""アウトラインの開閉を、押せる場所から出す（ユーザー要望）。

`Cmd+5` と表示メニューだけでは、**あることに気づけない**。Raw の隣と
歯車のメニューにも置く。

**どこから押しても同じ状態を指す。** 片方だけ印が変わると、どちらが本当か
分からなくなる。
"""

import pytest

pytestmark = pytest.mark.gui


class TestToolbarButton:
    def test_Rawの隣にある(self, window) -> None:
        toolbar = window.editor_pane.toolbar
        assert toolbar.outline_button is not None
        assert "アウトライン" in toolbar.outline_button.toolTip()

    def test_絵で描く(self, window) -> None:
        """**文字にしない。** 「見出し」と書くと、メニューの「アウトライン」と
        呼び名が食い違う（ユーザー指摘）。呼び名はツールチップに一本化する。"""
        from hitofude.ui.format_toolbar import BUTTON_SIZE, ICON_SIZE

        button = window.editor_pane.toolbar.outline_button
        assert not button.text()
        assert not button.icon().isNull()
        assert button.iconSize().width() == ICON_SIZE
        assert button.size().width() == BUTTON_SIZE

    def test_箇条書きと別の絵(self, window) -> None:
        """並びの中で見分けが付かないと、押し間違える。"""
        toolbar = window.editor_pane.toolbar
        bullets = next(
            b
            for b, a in zip(toolbar.buttons(), toolbar.ACTIONS, strict=True)
            if a.label == "箇条書き"
        )
        assert toolbar.outline_button.icon().cacheKey() != bullets.icon().cacheKey()

    def test_テーマで描き直す(self, window) -> None:
        from hitofude.theme import DARK

        before = window.editor_pane.toolbar.outline_button.icon().cacheKey()
        window.editor_pane.toolbar.set_theme(DARK)
        assert window.editor_pane.toolbar.outline_button.icon().cacheKey() != before

    def test_押すと開く(self, window, qtbot) -> None:
        from PySide6.QtCore import Qt

        assert window.outline_pane.isHidden() is True
        qtbot.mouseClick(window.editor_pane.toolbar.outline_button, Qt.MouseButton.LeftButton)
        assert window.outline_pane.isHidden() is False

    def test_もう一度押すと閉じる(self, window, qtbot) -> None:
        from PySide6.QtCore import Qt

        button = window.editor_pane.toolbar.outline_button
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert window.outline_pane.isHidden() is True

    def test_開いていれば押された形になる(self, window) -> None:
        """**状態を映す。** Raw と同じで、今どちらかが見て分かる。"""
        window.toggle_outline()
        assert window.editor_pane.toolbar.outline_button.isChecked() is True

    def test_キーで開いても追いつく(self, window) -> None:
        """`Cmd+5` で開いたときも、ボタンの見た目が揃う。"""
        window.toggle_outline()
        assert window.editor_pane.toolbar.outline_button.isChecked() is True
        window.toggle_outline()
        assert window.editor_pane.toolbar.outline_button.isChecked() is False

    def test_フォーカスを奪わない(self, window) -> None:
        """書式ツールバーの他のボタンと同じ扱い（本文のキャレットを手放さない）。"""
        from PySide6.QtCore import Qt

        button = window.editor_pane.toolbar.outline_button
        assert button.focusPolicy() is Qt.FocusPolicy.NoFocus


class TestGearMenu:
    def labels(self, window) -> list[str]:
        menu = window.menu_button.menu()
        return [action.text() for action in menu.actions() if action.text()]

    def test_歯車のメニューにある(self, window) -> None:
        assert "アウトライン" in self.labels(window)

    def test_チェック印が状態を映す(self, window) -> None:
        from hitofude.ui.menus import sync_view_checks

        window.toggle_outline()
        sync_view_checks(window)
        assert window.menu_actions["アウトライン"].isChecked() is True

    def test_同じアクションを使い回す(self, window) -> None:
        """**写しを作らない。** 2 つあると、片方だけ状態が古くなる。"""
        menu = window.menu_button.menu()
        found = next(a for a in menu.actions() if a.text() == "アウトライン")
        assert found is window.menu_actions["アウトライン"]
