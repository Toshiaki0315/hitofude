"""「4 文字の字下げでコードブロックとする」の切り替え（ユーザー要望 2026-08-28）。

**既定は on**（CommonMark 準拠。spec §1.3 の方針）。貼り付けで意図せず
コードに化けるのが煩わしい人が切れるようにする（ADR-0033）。

切り替えは**表示の決まりごとそのものが変わる**ので、全体を掛け直してよい
（R7 の例外）。
"""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QTextCursor

from hitofude.config import Config
from hitofude.core.models import BlockType
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.ui.preferences import PreferencesDialog

pytestmark = pytest.mark.gui

INDENTED = "本文\n\n    字下げした行\n\n末尾\n"


@pytest.fixture
def config(tmp_path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    found = Config(settings)
    found.vault_path = tmp_path / "notes"
    return found


class TestConfig:
    def test_既定はon(self, config) -> None:
        assert config.indented_code is True

    def test_覚える(self, config) -> None:
        config.indented_code = False
        assert config.indented_code is False


class TestEditor:
    @pytest.fixture
    def editor(self, qtbot) -> MarkdownEditor:
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.resize(800, 400)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setPlainText(INDENTED)
        widget.moveCursor(QTextCursor.MoveOperation.End)
        return widget

    def kind(self, editor: MarkdownEditor, number: int):
        data = editor.document().findBlockByNumber(number).userData()
        return data.info.type if data is not None else None

    def test_既定はコード(self, editor) -> None:
        assert self.kind(editor, 2) is BlockType.CODE_FENCE_BODY

    def test_切ると段落になる(self, editor) -> None:
        """**これが本題。** 切り替えたその場で見た目が変わる。"""
        editor.set_indented_code(False)
        assert self.kind(editor, 2) is BlockType.PARAGRAPH

    def test_戻せばコードに戻る(self, editor) -> None:
        editor.set_indented_code(False)
        editor.set_indented_code(True)
        assert self.kind(editor, 2) is BlockType.CODE_FENCE_BODY

    def test_フェンスは切らない(self, editor) -> None:
        """**止めるのは字下げだけ。**"""
        editor.setPlainText("本文\n\n```python\nprint(1)\n```\n\n末尾\n")
        editor.moveCursor(QTextCursor.MoveOperation.End)
        editor.set_indented_code(False)
        assert self.kind(editor, 3) is BlockType.CODE_FENCE_BODY


class TestPreferences:
    def test_設定に出る(self, config, qtbot) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog._indented_code is not None
        assert dialog._indented_code.isChecked() is True

    def test_外すと保存される(self, config, qtbot) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog._indented_code.setChecked(False)
        dialog.apply()
        assert config.indented_code is False


class TestApplied:
    """設定を変えたら**その場で**画面と書き出しに効く。"""

    def test_窓に効く(self, config, qtbot) -> None:
        from hitofude.ui.main_window import MainWindow

        config.indented_code = False
        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert window.editor.indented_code() is False
        finally:
            window.close()

    def test_設定を変えたら反映される(self, config, qtbot) -> None:
        from hitofude.ui.main_window import MainWindow

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert window.editor.indented_code() is True
            config.indented_code = False
            window._apply_preferences()
            assert window.editor.indented_code() is False
        finally:
            window.close()

    def test_書き出しも揃う(self) -> None:
        """**画面と食い違わせない。** 同じノートが違う形で書き出されない。"""
        from hitofude.editor.exporter import _rendered_body

        text = "本文\n\n    字下げした行\n"
        assert "<pre>" in _rendered_body(text, None)
        assert "<pre>" not in _rendered_body(text, None, indented_code=False)
