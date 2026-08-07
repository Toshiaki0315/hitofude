"""メインウィンドウにエディタが載っていることのテスト（spec §5.1）。

Phase 2 でエディタを作ったが、ウィンドウに繋いでいなかったため
`make run` しても何も打てなかった。その回帰テスト。
3 ペイン構成（サイドバー / ノートリスト / エディタ）はタスク 5-1 で入れる。
"""

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot) -> MainWindow:
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestEditorIsReachable:
    def test_中央ウィジェットがエディタ(self, window) -> None:
        assert isinstance(window.centralWidget(), MarkdownEditor)

    def test_editorプロパティで取れる(self, window) -> None:
        assert window.editor is window.centralWidget()

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
