"""数式ブロックのインライン展開（I-1 / ADR-0020）。

$$ 〜 $$ を、キャレットが外にあるとき組版した絵で見せる。仕組みは画像
（ADR-0004）と同じ「行を隠して高さを予約し、絵は paintEvent で描く」。
リビールは表（ADR-0017）と同じ**ブロック単位**: キャレットが式のどの行に
入っても、式全体が生の LaTeX に戻る。
"""

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

pytestmark = pytest.mark.gui

MATH = "$$\nE = mc^2\n$$\n\n本文\n"
# 行番号:  0    1          2   3  4


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(760, 400)
    widget.show()
    return widget


def move_to(editor: MarkdownEditor, line: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(line).position())
    editor.setTextCursor(cursor)


def hidden(editor: MarkdownEditor, line: int) -> bool:
    block = editor.document().findBlockByNumber(line)
    return any(f.format.fontPointSize() == pytest.approx(0.5) for f in block.layout().formats())


def figures(editor: MarkdownEditor):
    return [d for d in visible_decorations(editor) if d.kind is DecorationKind.MATH]


class TestFigure:
    def test_外にいると絵になる(self, editor) -> None:
        editor.setPlainText(MATH)
        move_to(editor, 4)
        assert hidden(editor, 1), "式の行が生のまま"
        found = figures(editor)
        assert len(found) == 1
        assert found[0].pixmap is not None

    def test_行の高さが絵のぶん確保される(self, editor) -> None:
        editor.setPlainText(MATH)
        move_to(editor, 4)
        body = editor.blockBoundingGeometry(editor.document().findBlockByNumber(1)).height()
        plain = editor.blockBoundingGeometry(editor.document().findBlockByNumber(4)).height()
        assert body > plain  # 分数などで本文 1 行より高くなる

    def test_本文は変わらない(self, editor) -> None:
        editor.setPlainText(MATH)
        move_to(editor, 4)
        assert editor.toPlainText() == MATH

    def test_Undoを消費しない(self, editor) -> None:
        editor.setPlainText(MATH)
        before = editor.document().availableUndoSteps()
        move_to(editor, 4)
        move_to(editor, 1)
        move_to(editor, 4)
        assert editor.document().availableUndoSteps() == before

    def test_複数行の式も1枚の絵(self, editor) -> None:
        editor.setPlainText("$$\na = 1 \\\\\nb = 2\n$$\n\n本文\n")
        move_to(editor, 5)
        assert hidden(editor, 1) and hidden(editor, 2)
        assert len(figures(editor)) == 1


class TestReveal:
    def test_キャレットが入ると式全体が生に戻る(self, editor) -> None:
        editor.setPlainText(MATH)
        move_to(editor, 4)
        move_to(editor, 1)
        assert not hidden(editor, 1)
        assert figures(editor) == []

    def test_区切り行にいても生(self, editor) -> None:
        """リビールはブロック単位。$$ の行も式のうち。"""
        editor.setPlainText(MATH)
        move_to(editor, 4)
        move_to(editor, 0)
        assert not hidden(editor, 1)
        assert figures(editor) == []

    def test_出ると絵に戻る(self, editor) -> None:
        editor.setPlainText(MATH)
        move_to(editor, 1)
        move_to(editor, 4)
        assert hidden(editor, 1)
        assert len(figures(editor)) == 1


class TestFallback:
    def test_壊れた式は生のまま(self, editor) -> None:
        editor.setPlainText("$$\n\\frac{1}{\n$$\n\n本文\n")
        move_to(editor, 4)
        assert not hidden(editor, 1)
        assert figures(editor) == []

    def test_Rawでは生のまま(self, editor) -> None:
        editor.setPlainText(MATH)
        editor.set_source_mode(True)
        move_to(editor, 4)
        assert not hidden(editor, 1)
        assert figures(editor) == []

    def test_閉じていない式は生のまま(self, editor) -> None:
        editor.setPlainText("$$\nE = mc^2\n\n本文\n")
        move_to(editor, 3)
        assert not hidden(editor, 1)


class TestInitialPass:
    def test_前置きがあっても最初から絵になる(self, editor) -> None:
        """初回ハイライト時は自分の userData がまだ無い。ラン検出が
        userData に頼り切ると、キャレットが式に触れるまで絵にならない（回帰）。"""
        editor.setPlainText("前置きの文。\n\n$$\nE = mc^2\n$$\n\n本文\n")
        move_to(editor, 6)
        assert hidden(editor, 3), "初回パスで式が生のまま"
        assert len(figures(editor)) == 1
