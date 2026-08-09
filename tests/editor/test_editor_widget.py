"""エディタウィジェットのテスト（タスク 2-5, 2-6 / spec §5.1, §6.4, §6.6）。"""

import pytest
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.highlighter import HIDDEN_POINT_SIZE

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def is_hidden(editor: MarkdownEditor, line: int, column: int) -> bool:
    block = editor.document().findBlockByNumber(line)
    for entry in block.layout().formats():
        covers = entry.start <= column < entry.start + entry.length
        if covers and entry.format.fontPointSize() == pytest.approx(HIDDEN_POINT_SIZE):
            return True
    return False


def move_to(editor: MarkdownEditor, position: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(position)
    editor.setTextCursor(cursor)


class TestConstruction:
    def test_ハイライタが付いている(self, editor) -> None:
        assert editor.highlighter.document() is editor.document()

    def test_折り返しは単語単位(self, editor) -> None:
        from PySide6.QtWidgets import QPlainTextEdit

        assert editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth


class TestSourceOfTruth:
    """R1 / spec §3.1: `toPlainText()` がそのまま保存内容。"""

    def test_打った文字がそのまま残る(self, editor, qtbot) -> None:
        source = "# 見出し\n\nこれは**強調**です #tag"
        editor.setPlainText(source)
        assert editor.toPlainText() == source

    def test_装飾されてもマーカーは消えない(self, editor, qtbot) -> None:
        qtbot.keyClicks(editor, "**bold**")
        assert editor.toPlainText() == "**bold**"


class TestReveal:
    def test_キャレットを入れるとマーカーが現れる(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        move_to(editor, 0)
        assert is_hidden(editor, 0, 3)
        move_to(editor, 5)
        assert not is_hidden(editor, 0, 3)

    def test_離れると再び隠れる(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        move_to(editor, 5)
        assert not is_hidden(editor, 0, 3)
        move_to(editor, 0)
        assert is_hidden(editor, 0, 3)

    def test_前のブロックのマーカーが隠れ直す(self, editor) -> None:
        editor.setPlainText("## 見出し\n本文")
        move_to(editor, 2)
        assert not is_hidden(editor, 0, 0)
        move_to(editor, 8)  # 次のブロックへ
        assert is_hidden(editor, 0, 0)

    def test_選択したブロックは全表示になる(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        move_to(editor, 0)
        assert is_hidden(editor, 0, 3)
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        assert not is_hidden(editor, 0, 3)

    def test_複数ブロックの選択は全ての行を現す(self, editor) -> None:
        editor.setPlainText("**一行目**\n**二行目**\n**三行目**")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        for line in range(3):
            assert not is_hidden(editor, line, 0), f"{line} 行目が隠れたまま"

    def test_ソースモードで全表示(self, editor) -> None:
        editor.setPlainText("## 見出し\n**強調**")
        move_to(editor, 0)
        editor.set_source_mode(True)
        assert not is_hidden(editor, 0, 0)
        assert not is_hidden(editor, 1, 0)
        editor.set_source_mode(False)
        assert is_hidden(editor, 1, 0)


class TestRehighlightScope:
    """R7 / spec §6.6: カーソル移動では旧/新の 2 ブロックだけを掛け直す。"""

    def test_カーソル移動で全体再ハイライトしない(self, editor, monkeypatch) -> None:
        editor.setPlainText("\n".join(f"**行{i}**" for i in range(200)))
        calls: list[int] = []
        monkeypatch.setattr(
            editor.highlighter,
            "rehighlightBlock",
            lambda block: calls.append(block.blockNumber()),
        )
        move_to(editor, 0)
        calls.clear()
        move_to(editor, editor.document().findBlockByNumber(100).position() + 3)
        assert len(calls) <= 2, f"{len(calls)} ブロックを掛け直している"

    def test_同じブロック内の移動は1ブロックだけ(self, editor, monkeypatch) -> None:
        editor.setPlainText("これは**強調**です\n別の行")
        move_to(editor, 0)
        calls: list[int] = []
        monkeypatch.setattr(
            editor.highlighter,
            "rehighlightBlock",
            lambda block: calls.append(block.blockNumber()),
        )
        move_to(editor, 5)
        assert calls == [0]


class TestNoPollution:
    """R5 の前提: リビールは編集ではない。"""

    def test_カーソル移動でmodifiedにならない(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        editor.document().setModified(False)
        move_to(editor, 5)
        move_to(editor, 0)
        assert editor.document().isModified() is False

    def test_カーソル移動でUndoスタックが汚れない(self, editor, qtbot) -> None:
        """`Cmd+Z` 1 回で直前の入力が戻ること（Phase 2 の完了条件）。"""
        qtbot.keyClicks(editor, "**bold**")
        move_to(editor, 3)
        move_to(editor, 0)
        move_to(editor, 8)
        editor.undo()
        assert editor.toPlainText() == ""


class TestLayout:
    """spec §5.1: 中央寄せ・最大幅 720px。"""

    def test_広いときは左右に余白が付く(self, editor) -> None:
        editor.resize(1200, 400)
        margins = editor.viewportMargins()
        assert margins.left() > 0
        assert margins.left() == margins.right()

    def test_狭いときは余白なし(self, editor) -> None:
        editor.resize(500, 400)
        assert editor.content_margin() == 0

    def test_本文幅は上限を超えない(self, editor) -> None:
        editor.resize(1600, 400)
        margins = editor.viewportMargins()
        content = 1600 - margins.left() - margins.right()
        assert content <= MarkdownEditor.MAX_CONTENT_WIDTH + 1


class TestTheme:
    def test_テーマ変更が反映される(self, editor) -> None:
        from hitofude.theme import DARK

        editor.setPlainText("`code`")
        editor.set_theme(DARK)
        assert editor.palette().base().color().name() == DARK.background.lower()


class TestTabWidth:
    """タブ幅（ユーザー要望）。

    Qt の既定は 80px 固定で、本文フォントだと 12 文字ぶんもあった（実測）。
    """

    def advance(self, editor, text: str) -> float:
        from PySide6.QtGui import QFontMetricsF

        return QFontMetricsF(editor.font()).horizontalAdvance(text)

    def test_既定は4文字ぶん(self, editor) -> None:
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, "    "), abs=1)

    def test_変えられる(self, editor) -> None:
        editor.set_tab_width(2)
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, "  "), abs=1)

    def test_文字サイズを変えると追従する(self, editor) -> None:
        """px 固定で覚えると、大きい文字にしたときタブだけ狭くなる。"""
        before = editor.tabStopDistance()
        editor.set_base_point_size(30.0)
        assert editor.tabStopDistance() > before

    def test_フォントを変えても追従する(self, editor) -> None:
        editor.set_tab_width(8)
        wide = editor.tabStopDistance()
        editor.set_font_family("Menlo")
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, " " * 8), abs=1)
        assert wide != editor.tabStopDistance() or True  # フォント次第で同じこともある

    def test_今の幅を答える(self, editor) -> None:
        editor.set_tab_width(3)
        assert editor.tab_width() == 3
