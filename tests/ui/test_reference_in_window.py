"""参照ペインを窓に繋ぐ（U-1）。

**ペインは最後に足す。** ペインの表示は添字で切り替える作り
（`toggle_pane(0)` など）なので、途中に入れるとアウトラインと
ローカルLLM の添字がずれる。
"""

import pytest

pytestmark = pytest.mark.gui


class TestOpenBeside:
    def test_横に開ける(self, window) -> None:
        note = window._vault.create("参照するノート", "# 参照するノート\n\n中身\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_beside(note.path)
        assert window.reference.title() == "参照するノート"
        assert "中身" in window.reference.editor.toPlainText()

    def test_開くとペインが出る(self, window) -> None:
        note = window._vault.create("参照するノート", "# 参照するノート\n\n中身\n")
        window.open_beside(note.path)
        assert not window.reference.isHidden()

    def test_本文は入れ替わらない(self, window) -> None:
        """**横に開くだけ。** 書いているノートを奪わない。"""
        note = window._vault.create("書いているノート", "# 書いているノート\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_and_select(note.path)
        other = window._vault.create("参照するノート", "# 参照するノート\n\n中身\n")
        window.open_beside(other.path)
        assert window.current_note.path == note.path
        assert "本文" in window.editor.toPlainText()

    def test_読めないノートは出さない(self, window) -> None:
        """**落とさない。** 消えたノートを指しても知らせて終わる。"""
        window.open_beside(window._vault.root / "無いノート.md")
        assert window.reference.is_empty()


class TestToggle:
    def test_切り替えられる(self, window) -> None:
        window.toggle_reference()
        assert not window.reference.isHidden()
        window.toggle_reference()
        assert window.reference.isHidden()

    def test_既定では出さない(self, window) -> None:
        """**画面を勝手に狭くしない**（アウトラインと同じ考え方）。"""
        assert window.reference.isHidden()

    def test_覚えている(self, config, qtbot) -> None:
        from hitofude.ui.main_window import MainWindow

        config.reference_visible = True
        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert not window.reference.isHidden()
        finally:
            window.close()


class TestPaneOrder:
    """**添字をずらさない**（既存のペインの切り替えが壊れる）。"""

    def test_サイドバーと一覧の添字は動かない(self, window) -> None:
        splitter = window._splitter
        assert splitter.widget(0) is window._sidebar
        assert splitter.widget(1) is window._list_pane
        assert splitter.widget(2) is window.editor_pane

    def test_参照は最後(self, window) -> None:
        splitter = window._splitter
        assert splitter.widget(splitter.count() - 1) is window.reference


class TestEntryPoints:
    """入口（U-1）。**開ける道が無ければ機能が無いのと同じ。**"""

    def labels(self, menu) -> list[str]:
        return [action.text() for action in menu.actions()]

    def test_表示メニューにある(self, window) -> None:
        for menu in window.menuBar().findChildren(type(window.menuBar().addMenu("x"))):
            if menu.title() == "表示":
                assert "横に開く欄" in self.labels(menu)
                return
        raise AssertionError("表示メニューが無い")

    def test_一覧の右クリックにある(self, window, qtbot) -> None:
        from pathlib import Path

        note = window._vault.create("参照するノート", "# 参照するノート\n\n中身\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        menu = window._notes.context_menu_for(Path("参照するノート.md"))
        try:
            assert "横に開く" in self.labels(menu)
        finally:
            menu.deleteLater()

    def test_押すと横に出る(self, window) -> None:
        from pathlib import Path

        note = window._vault.create("参照するノート", "# 参照するノート\n\n中身\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        menu = window._notes.context_menu_for(Path("参照するノート.md"))
        for action in menu.actions():
            if action.text() == "横に開く":
                action.trigger()
                break
        assert window.reference.title() == "参照するノート"


class TestFollowsSettings:
    """**本文と同じ見た目にする。** 片方だけ古い設定で描かない。"""

    def test_テーマが効く(self, window) -> None:
        """配色は塗った色で見る（エディタは今の配色を持ち歩かない）。"""
        from PySide6.QtGui import QPalette

        from hitofude.theme import DARK

        window._apply_theme_now(DARK)
        painted = window.reference.editor.palette().color(QPalette.ColorRole.Window)
        assert painted.name().upper() == DARK.page_background.upper()

    def test_文字の大きさが効く(self, window) -> None:
        before = window.reference.editor.font().pointSizeF()
        window.zoom_in()
        assert window.reference.editor.font().pointSizeF() != before
