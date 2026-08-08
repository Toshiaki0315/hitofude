"""メインウィンドウでエディタが使えることのテスト（spec §5.1）。

Phase 2 でエディタを作ったがウィンドウに繋いでいなかったため
`make run` しても何も打てなかった、という事象の回帰テスト。
3 ペイン構成そのものは `test_main_window_flow.py` が見る。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    # 使い方ノートを置かせない（件数を数えるテストがずれるため）
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")

    widget = MainWindow(config)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


class TestEditorIsReachable:
    def test_エディタが3ペインに入っている(self, window) -> None:
        assert window.centralWidget().indexOf(window.editor) >= 0

    def test_editorプロパティで取れる(self, window) -> None:
        assert isinstance(window.editor, MarkdownEditor)

    def test_文字を打ち込める(self, window, qtbot) -> None:
        """`make run` で入力できなかった事象そのものを検査する。"""
        qtbot.keyClicks(window.editor, "hello")
        assert window.editor.toPlainText() == "hello"

    def test_打った内容が装飾される(self, window, qtbot) -> None:
        # keyClicks は ASCII しか送れない（Qt の qasciikey.cpp が assert で落ちる）
        qtbot.keyClicks(window.editor, "# Heading")
        data = window.editor.document().findBlockByNumber(0).userData()
        assert data is not None
        assert data.info.marker_len == 2

    def test_日本語を入れても装飾される(self, window) -> None:
        """IME の確定は `insertText` 相当で入る。打鍵の再現は keyClicks では不可能。"""
        window.editor.textCursor().insertText("これは**強調**です")
        spans = window.editor.document().findBlockByNumber(0).userData().spans
        assert len(spans) == 1

    def test_起動直後にエディタへフォーカスが当たる(self, window) -> None:
        assert window.focusWidget() is window.editor

    def test_編集可能である(self, window) -> None:
        assert window.editor.isReadOnly() is False


class TestTheme:
    def test_テーマ監視がエディタへ伝わる(self, window) -> None:
        from hitofude.theme import DARK, ThemeMode

        window.theme_watcher.set_mode(ThemeMode.DARK)
        assert window.editor.palette().base().color().name() == DARK.background.lower()

    def test_ライトへ戻せる(self, window) -> None:
        from hitofude.theme import LIGHT, ThemeMode

        window.theme_watcher.set_mode(ThemeMode.DARK)
        window.theme_watcher.set_mode(ThemeMode.LIGHT)
        assert window.editor.palette().base().color().name() == LIGHT.background.lower()

    def test_ノートリストにも伝わる(self, window) -> None:
        from hitofude.theme import DARK, ThemeMode

        window.theme_watcher.set_mode(ThemeMode.DARK)
        window.note_list.viewport().update()  # 例外が出ないこと
        assert window.theme_watcher.colors is DARK


class TestWindowBasics:
    """Phase 0-B から引き継いだ基本の検査。"""

    def test_表示できる(self, window) -> None:
        assert window.isVisible()

    def test_ウィンドウタイトルがアプリ名である(self, window) -> None:
        from hitofude import APP_NAME

        assert APP_NAME in window.windowTitle()

    def test_最小サイズが3ペインを置ける幅を確保している(self, window) -> None:
        """spec §5.1: サイドバー 180px + ノートリスト 280px。"""
        assert window.minimumWidth() >= 180 + 280
