"""見出し単位の折りたたみ（I-4 / ADR-0019）。

`QTextBlock.setVisible(False)` で節の行を畳む。ソースは触らない（R1）ので
`toPlainText()` は不変、Undo スタックも消費しない（スパイクで実証済み）。
状態はセッション限り。
"""

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

pytestmark = pytest.mark.gui

DOC = "# 章1\n\n本文A\n\n## 節1\n\n本文B\n\n# 章2\n\n本文C\n"
# 行番号:      0     1  2      3  4      5  6      7  8      9  10


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(760, 400)
    widget.show()
    widget.setPlainText(DOC)
    return widget


def visible_flags(editor: MarkdownEditor) -> list[bool]:
    document = editor.document()
    return [document.findBlockByNumber(n).isVisible() for n in range(document.blockCount())]


class TestFold:
    def test_章を畳むと次の章の手前まで隠れる(self, editor) -> None:
        editor.fold(0)
        flags = visible_flags(editor)
        assert flags[0] is True  # 見出し自身は残る
        assert flags[1:8] == [False] * 7  # 節1（H2）も巻き込む
        assert flags[8] is True  # 次の H1

    def test_節は同じ深さの手前まで(self, editor) -> None:
        editor.fold(4)
        flags = visible_flags(editor)
        assert flags[4] is True
        assert flags[5:8] == [False] * 3
        assert flags[8] is True

    def test_畳んでも本文は変わらない(self, editor) -> None:
        editor.fold(0)
        assert editor.toPlainText() == DOC

    def test_Undoを消費しない(self, editor) -> None:
        before = editor.document().availableUndoSteps()
        editor.fold(0)
        editor.unfold(0)
        assert editor.document().availableUndoSteps() == before

    def test_開くと戻る(self, editor) -> None:
        editor.fold(0)
        editor.unfold(0)
        assert all(visible_flags(editor))

    def test_二回切り替えで元どおり(self, editor) -> None:
        editor.toggle_fold(0)
        editor.toggle_fold(0)
        assert all(visible_flags(editor))

    def test_後続の行が上へ詰まる(self, editor) -> None:
        document = editor.document()
        before = editor.blockBoundingGeometry(document.findBlockByNumber(8)).top()
        editor.fold(0)
        after = editor.blockBoundingGeometry(document.findBlockByNumber(8)).top()
        assert after < before

    def test_見出しでない行は畳めない(self, editor) -> None:
        editor.fold(2)
        assert all(visible_flags(editor))

    def test_本文のない見出しは畳めない(self, editor) -> None:
        editor.setPlainText("# 章1\n# 章2\n本文\n")
        editor.fold(0)
        assert all(visible_flags(editor))


class TestAutoUnfold:
    def test_隠れた行へカーソルが入ると開く(self, editor) -> None:
        editor.fold(0)
        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(2).position())
        editor.setTextCursor(cursor)
        assert all(visible_flags(editor))

    def test_畳むときカーソルは見出しへ退避する(self, editor) -> None:
        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(2).position())
        editor.setTextCursor(cursor)
        editor.fold(0)
        assert editor.textCursor().blockNumber() == 0
        assert not visible_flags(editor)[2]  # 退避で開き直さない

    def test_Rawに切り替えると全部開く(self, editor) -> None:
        """Raw はソースを全部見せるモード。隠れた行があっては嘘になる。"""
        editor.fold(0)
        editor.set_source_mode(True)
        assert all(visible_flags(editor))

    def test_見出しでなくなったら開く(self, editor) -> None:
        """畳んだ見出しの `#` を消すと、隠れた本文へ入る口が無くなる。"""
        editor.fold(0)
        cursor = editor.textCursor()
        block = editor.document().findBlockByNumber(0)
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + 2, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        assert all(visible_flags(editor))


class TestFoldMarker:
    def test_畳める見出しに開閉の印が出る(self, editor) -> None:
        editor.resize(760, 800)  # カーソル移動のスクロールで見出しが画面外に出ない高さ
        markers = [d for d in visible_decorations(editor) if d.kind is DecorationKind.FOLD_MARKER]
        assert len(markers) == 3  # 章1・節1・章2

    def test_畳んだ見出しの印は閉じた形(self, editor) -> None:
        editor.fold(0)
        markers = [d for d in visible_decorations(editor) if d.kind is DecorationKind.FOLD_MARKER]
        states = {m.text for m in markers}
        assert "folded" in states and "open" in states

    def test_コードフェンス内のシャープには出ない(self, editor) -> None:
        editor.setPlainText("```\n# コメント\n```\n本文\n")
        markers = [d for d in visible_decorations(editor) if d.kind is DecorationKind.FOLD_MARKER]
        assert markers == []

    def test_Rawでは印を出さない(self, editor) -> None:
        editor.set_source_mode(True)
        markers = [d for d in visible_decorations(editor) if d.kind is DecorationKind.FOLD_MARKER]
        assert markers == []


class TestMarginClick:
    def click_margin(self, editor: MarkdownEditor, line: int) -> None:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        block = editor.document().findBlockByNumber(line)
        rect = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
        pos = QPointF(editor.contentOffset().x() + 5, rect.top() + rect.height() / 2)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            pos,
            pos,  # globalPos。offscreen ではローカルと同じでよい
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mousePressEvent(event)

    def test_左余白のクリックで畳む(self, editor) -> None:
        self.click_margin(editor, 0)
        assert not visible_flags(editor)[2]

    def test_もう一度で開く(self, editor) -> None:
        self.click_margin(editor, 0)
        self.click_margin(editor, 0)
        assert all(visible_flags(editor))

    def test_本文の行の余白では何も起きない(self, editor) -> None:
        self.click_margin(editor, 2)
        assert all(visible_flags(editor))


class TestFoldedDecorations:
    """畳んだ節の中の飾りは描かない。高さ 0 の矩形でも描けば無駄で、
    表の罫線は 1px 残って線のゴミになる。"""

    def test_畳んだ表の罫線は描かない(self, editor) -> None:
        editor.setPlainText("# 章\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n# 次\n\n本文\n")
        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(8).position())
        editor.setTextCursor(cursor)
        editor.fold(0)
        assert DecorationKind.TABLE_RULE not in [d.kind for d in visible_decorations(editor)]
