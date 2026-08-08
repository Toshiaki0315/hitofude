"""ペインの区切り線とフォント設定の反映（ユーザー要望）。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt

from hitofude.config import Config
from hitofude.theme import DARK, LIGHT, ThemeMode
from hitofude.ui.main_window import MainWindow
from hitofude.ui.panes import SPLITTER_HANDLE_WIDTH

pytestmark = pytest.mark.gui


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    # 使い方ノートを置かせない。件数を数えるテストが 1 件ずれるため。
    # 初回ノートそのものは TestWelcomeNote が見る
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")
    return config


@pytest.fixture
def window(qtbot, config: Config) -> MainWindow:
    widget = MainWindow(config)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


class TestSplitterDivider:
    """ペインの間に区切りの線を出す。"""

    def test_ハンドルが細い(self, window) -> None:
        """太いと「掴む場所」に見えてしまう。境界として読ませたい。"""
        assert window.centralWidget().handleWidth() == SPLITTER_HANDLE_WIDTH
        assert SPLITTER_HANDLE_WIDTH <= 2

    def test_線の色がテーマの罫線色(self, window) -> None:
        assert window.centralWidget().rule_color == LIGHT.rule

    def test_テーマを変えると線の色も変わる(self, window) -> None:
        window.theme_watcher.set_mode(ThemeMode.DARK)
        assert window.centralWidget().rule_color == DARK.rule

    def test_スタイルシートを使わない(self, window) -> None:
        """setStyleSheet は子に波及し QPalette を上書きするため、
        エディタのテーマ切替が効かなくなる（回帰テスト）。"""
        assert window.centralWidget().styleSheet() == ""

    def test_線がピクセルとして現れる(self, window) -> None:
        from PySide6.QtGui import QColor, QImage

        window.resize(900, 400)
        image = QImage(window.centralWidget().size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        window.centralWidget().render(image)

        rule = QColor(LIGHT.rule).rgb()
        found = any(
            image.pixel(x, y) == rule
            for x in range(image.width())
            for y in range(0, image.height(), 20)
        )
        assert found, "区切り線の色のピクセルが見つからない"


class TestFontSettings:
    """フォントの設定が実際に反映されること。"""

    def test_本文フォントを変えられる(self, window, config) -> None:
        config.font_family = "Courier New"
        window._apply_preferences()
        assert window.editor.font().family() == "Courier New"

    def test_文字サイズを変えられる(self, window, config) -> None:
        config.font_point_size = 19.0
        window._apply_preferences()
        assert window.editor.font().pointSizeF() == pytest.approx(19.0)

    def test_文字サイズは見出しにも効く(self, window, config) -> None:
        window.editor.setPlainText("# 見出し")
        config.font_point_size = 20.0
        window._apply_preferences()

        block = window.editor.document().findBlockByNumber(0)
        sizes = [entry.format.fontPointSize() for entry in block.layout().formats()]
        assert any(size > 30 for size in sizes), f"見出しが拡大されていない: {sizes}"

    def test_等幅フォントを変えられる(self, window, config) -> None:
        """以前はここが配線されておらず、設定しても反映されなかった。"""
        window.editor.setPlainText("`code`")
        config.mono_family = "Courier New"
        window._apply_preferences()

        block = window.editor.document().findBlockByNumber(0)
        families = [entry.format.fontFamilies() for entry in block.layout().formats()]
        assert any(f and "Courier New" in f for f in families), families

    def test_一覧の文字も本文フォントに合わせる(self, window, config) -> None:
        config.font_family = "Courier New"
        window._apply_preferences()
        assert window.note_list.font().family() == "Courier New"

    def test_起動時に設定が読まれる(self, qtbot, config) -> None:
        config.font_family = "Courier New"
        config.font_point_size = 17.0

        widget = MainWindow(config)
        qtbot.addWidget(widget)
        try:
            assert widget.editor.font().family() == "Courier New"
            assert widget.editor.font().pointSizeF() == pytest.approx(17.0)
        finally:
            widget.close()


class TestTableFormatting:
    """表の整形（GFM / Qiita と同じ記法）。"""

    SOURCE = "本文\n\n| 名前 | 個数 |\n|---|---:|\n| りんご | 3 |\n| みかん | 12 |\n"

    def _put_caret(self, window, line: int) -> None:
        cursor = window.editor.textCursor()
        cursor.setPosition(window.editor.document().findBlockByNumber(line).position())
        window.editor.setTextCursor(cursor)

    def test_縦線が揃う(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        self._put_caret(window, 2)
        assert window.editor.format_table() is True

        from hitofude.editor.table import display_width

        lines = window.editor.toPlainText().split("\n")[2:6]
        assert len({display_width(line) for line in lines}) == 1

    def test_右揃えの指定を保つ(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        self._put_caret(window, 3)
        window.editor.format_table()
        assert "---:" in window.editor.toPlainText()

    def test_表の外では何もしない(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        self._put_caret(window, 0)
        assert window.editor.format_table() is False

    def test_内容は変わらない(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        self._put_caret(window, 4)
        window.editor.format_table()
        text = window.editor.toPlainText()
        for word in ("名前", "個数", "りんご", "みかん", "12"):
            assert word in text

    def test_Undoは1手で戻る(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        self._put_caret(window, 2)
        window.editor.format_table()
        window.editor.undo()
        assert window.editor.toPlainText() == self.SOURCE

    def test_表の行は等幅で表示される(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        data = window.editor.document().findBlockByNumber(2).userData()
        from hitofude.core.models import BlockType

        assert data.info.type is BlockType.TABLE_ROW

    def test_パイプを含むだけの文は表にしない(self, window) -> None:
        """以前は等幅フォントになってしまっていた。"""
        from hitofude.core.models import BlockType

        window.editor.setPlainText("価格は 100 | 税込です\n")
        data = window.editor.document().findBlockByNumber(0).userData()
        assert data.info.type is BlockType.PARAGRAPH


class TestShortcutRegistration:
    """メニューとショートカットの登録漏れ・衝突を検出する（回帰テスト）。

    「表を整形」はメニューへの追加が抜けたまま気づけなかった。
    `format_table()` を直接呼ぶテストしか無く、**ユーザーが辿る経路**を
    誰も見ていなかったため。
    """

    def _shortcuts(self, window) -> dict[str, str]:
        found: dict[str, str] = {}
        for action in window.actions():
            text = action.shortcut().toString()
            if text:
                found[text] = action.text()
        return found

    def test_表を整形が登録されている(self, window) -> None:
        assert "Ctrl+Shift+L" in self._shortcuts(window)

    @pytest.mark.parametrize(
        ("shortcut", "label"),
        [
            ("Ctrl+N", "新規ノート"),
            ("Ctrl+S", "保存"),
            ("Ctrl+O", "クイックオープン"),
            ("Ctrl+Shift+F", "全文検索"),
            ("Ctrl+F", "このノート内を検索"),
            ("Ctrl+G", "次を検索"),
            ("Ctrl+Shift+G", "前を検索"),
            ("Ctrl+Shift+L", "表を整形"),
            ("Ctrl+Shift+P", "ピン留め"),
            ("Ctrl+Shift+M", "Markdown で書き出す…"),
            ("Ctrl+Shift+E", "HTML で書き出す…"),
            ("Ctrl+P", "PDF で書き出す…"),
            ("Ctrl+,", "環境設定…"),
            ("Ctrl+1", "サイドバー"),
            ("Ctrl+2", "ノートリスト"),
            ("Ctrl+/", "ソースモード"),
        ],
    )
    def test_主要なショートカットが揃っている(self, window, shortcut: str, label: str) -> None:
        assert self._shortcuts(window).get(shortcut) == label

    def test_ショートカットが衝突していない(self, window) -> None:
        texts = [
            action.shortcut().toString()
            for action in window.actions()
            if action.shortcut().toString()
        ]
        duplicates = {text for text in texts if texts.count(text) > 1}
        assert not duplicates, f"重複: {duplicates}"

    def test_Optionを含むショートカットを使わない(self, window) -> None:
        """macOS では Option が文字合成に使われ、ショートカットが発火しない。"""
        using_alt = [
            action.text()
            for action in window.actions()
            if "Alt" in action.shortcut().toString() or "Opt" in action.shortcut().toString()
        ]
        assert using_alt == []

    def test_ショートカットで表が整形される(self, window, qtbot) -> None:
        """ユーザーが辿る経路そのものを通す。"""
        from hitofude.editor.table import display_width

        window.editor.setPlainText("| 名前 | 個数 |\n|---|---:|\n| りんご | 3 |\n")
        cursor = window.editor.textCursor()
        cursor.setPosition(0)
        window.editor.setTextCursor(cursor)

        qtbot.keyClick(
            window.editor,
            Qt.Key.Key_L,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        lines = window.editor.toPlainText().split("\n")[:3]
        assert len({display_width(line) for line in lines}) == 1, lines

    def test_表全体を選択したまま整形できる(self, window, qtbot) -> None:
        """選択の末尾は表の下の空行になる。先頭側を見ないと見つからない。"""
        from PySide6.QtGui import QTextCursor

        from hitofude.editor.table import display_width

        window.editor.setPlainText("| 名前 | 個数 |\n|---|---:|\n| りんご | 3 |\n")
        cursor = window.editor.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        window.editor.setTextCursor(cursor)

        qtbot.keyClick(
            window.editor,
            Qt.Key.Key_L,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        lines = window.editor.toPlainText().split("\n")[:3]
        assert len({display_width(line) for line in lines}) == 1, lines
        assert "りんご" in window.editor.toPlainText()
