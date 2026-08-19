"""アウトラインを出しっぱなしにできるようにする（提案 5）。

`Cmd+R` のパレットはあるが、**長い文書を見渡しながら書く**用途には、
そばに出したままのほうが向く。本文の右に置き、`Cmd+5` で開閉する。

見出しの取り出しは `core/outline.py`（既にある）。ここは出す側だけ。
"""

import pytest

from hitofude.core.outline import Heading
from hitofude.ui.outline_pane import OutlinePane

pytestmark = pytest.mark.gui

SOURCE = "# 題名\n\n本文\n\n## 中見出し\n\n本文\n\n### 小見出し\n\n本文\n"


@pytest.fixture
def pane(qtbot) -> OutlinePane:
    widget = OutlinePane()
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestContents:
    def test_見出しが並ぶ(self, pane) -> None:
        pane.set_headings([Heading(line=0, level=1, text="題名")])
        assert pane.labels() == ["題名"]

    def test_階層は字下げで見せる(self, pane) -> None:
        """**深さを数字で出さない。** 読み取りにくい（パレットと同じ作法）。"""
        pane.set_headings(
            [Heading(line=0, level=1, text="親"), Heading(line=4, level=2, text="子")]
        )
        from hitofude.ui.outline_pane import INDENT

        assert pane.labels()[1].startswith(INDENT)
        assert "2" not in pane.labels()[1]

    def test_見出しが無ければ案内を出す(self, pane) -> None:
        """空のまま出ていると、壊れているのか見出しが無いのか分からない。"""
        pane.set_headings([])
        assert pane.empty_notice_visible() is True

    def test_見出しがあれば案内は消える(self, pane) -> None:
        pane.set_headings([Heading(line=0, level=1, text="題名")])
        assert pane.empty_notice_visible() is False

    def test_装飾の記号はそのまま出す(self, pane) -> None:
        """`core/outline.py` の約束。ここで削ると本文と食い違う。"""
        pane.set_headings([Heading(line=0, level=1, text="**強調**した見出し")])
        assert "**強調**した見出し" in pane.labels()[0]


class TestJump:
    def test_押すと行番号を知らせる(self, pane, qtbot) -> None:
        """**飛ぶのはここではない**（ウィジェットはエディタを知らない）。"""
        pane.set_headings(
            [Heading(line=0, level=1, text="題名"), Heading(line=4, level=2, text="次")]
        )
        with qtbot.waitSignal(pane.heading_activated, timeout=1000) as blocker:
            pane.activate_row(1)
        assert blocker.args[0] == 4


class TestInWindow:
    def test_既定では出さない(self, window) -> None:
        """**画面を勝手に狭くしない。** 要る人が開く。"""
        assert window.outline_pane.isHidden() is True

    def test_Cmd5で開閉する(self, window) -> None:
        window.toggle_outline()
        assert window.outline_pane.isHidden() is False
        window.toggle_outline()
        assert window.outline_pane.isHidden() is True

    def test_開いたノートの見出しが出る(self, window) -> None:
        note = window.vault.create("見出しのノート", SOURCE)
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.toggle_outline()
        window.open_and_select(note.path)

        assert "中見出し" in "".join(window.outline_pane.labels())

    def test_打つと追いつく(self, window) -> None:
        window.toggle_outline()
        window.new_note()
        window.editor.setPlainText("# あとから足した見出し\n")
        window._update_outline()

        assert "あとから足した見出し" in "".join(window.outline_pane.labels())

    def test_押すとその行へ飛ぶ(self, window) -> None:
        window.toggle_outline()
        window.new_note()
        window.editor.setPlainText(SOURCE)
        window._update_outline()

        window.outline_pane.activate_row(1)
        assert window.editor.textCursor().blockNumber() == 4

    def test_開閉を覚える(self, window) -> None:
        window.toggle_outline()
        assert window.config.outline_visible is True
        window.toggle_outline()
        assert window.config.outline_visible is False

    def test_メニューにある(self, window) -> None:
        from PySide6.QtGui import QKeySequence

        found = {a.text(): a.shortcut().toString() for a in window.actions()}
        assert "アウトライン" in found
        assert found["アウトライン"] == QKeySequence("Ctrl+5").toString()

    def test_チェック印が付く(self, window) -> None:
        from hitofude.ui.menus import sync_view_checks

        window.toggle_outline()
        sync_view_checks(window)
        assert window.menu_actions["アウトライン"].isChecked() is True

    def test_次に開いたときも出ている(self, qtbot, config) -> None:
        """**開いたままにした人には、次も開いた状態で出す。**"""
        from hitofude.ui.main_window import MainWindow

        config.outline_visible = True
        second = MainWindow(config)
        qtbot.addWidget(second)
        try:
            assert second.outline_pane.isHidden() is False
        finally:
            second.close()
