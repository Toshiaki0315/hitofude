"""Mermaid ブロックのインライン展開（I-1 / ADR-0021）。

```mermaid 〜 ``` を、キャレットが外にあるとき図で見せる。仕組みは数式
（ADR-0020）と同じ: 行を隠して高さを予約し、絵は paintEvent。描画は
非同期なので、絵が出来るまでは生のまま（出来た瞬間に掛け直す）。
"""

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

pytestmark = pytest.mark.gui

MERMAID = "```mermaid\ngraph TD\n  A[開始] --> B[終了]\n```\n\n本文\n"
# 行番号:     0            1          2                  3    4  5
SOURCE = "graph TD\n  A[開始] --> B[終了]"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(760, 500)
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
    return [d for d in visible_decorations(editor) if d.kind is DecorationKind.MERMAID]


def wait_rendered(editor: MarkdownEditor, qtbot) -> None:
    qtbot.waitUntil(lambda: editor._mermaid.done(SOURCE, dark=False), timeout=30000)


class TestFigure:
    def test_描き上がると図になる(self, editor, qtbot) -> None:
        editor.setPlainText(MERMAID)
        move_to(editor, 5)
        wait_rendered(editor, qtbot)
        qtbot.waitUntil(lambda: hidden(editor, 1), timeout=5000)
        found = figures(editor)
        assert len(found) == 1
        assert found[0].pixmap is not None

    def test_描き上がるまでは生のまま(self, editor) -> None:
        editor.setPlainText("```mermaid\ngraph LR\n  P --> Q{未描画}\n```\n\n本文\n")
        move_to(editor, 5)
        assert not hidden(editor, 1)

    def test_本文は変わらない(self, editor, qtbot) -> None:
        editor.setPlainText(MERMAID)
        move_to(editor, 5)
        wait_rendered(editor, qtbot)
        qtbot.waitUntil(lambda: hidden(editor, 1), timeout=5000)
        assert editor.toPlainText() == MERMAID

    def test_キャレットが入ると生に戻る(self, editor, qtbot) -> None:
        editor.setPlainText(MERMAID)
        move_to(editor, 5)
        wait_rendered(editor, qtbot)
        qtbot.waitUntil(lambda: hidden(editor, 1), timeout=5000)
        move_to(editor, 2)
        assert not hidden(editor, 1)
        assert figures(editor) == []

    def test_出ると図に戻る(self, editor, qtbot) -> None:
        editor.setPlainText(MERMAID)
        move_to(editor, 5)
        wait_rendered(editor, qtbot)
        qtbot.waitUntil(lambda: hidden(editor, 1), timeout=5000)
        move_to(editor, 1)
        move_to(editor, 5)
        assert hidden(editor, 1)
        assert len(figures(editor)) == 1


class TestFallback:
    def test_mermaid以外のフェンスは今まで通り(self, editor) -> None:
        editor.setPlainText("```python\nprint(1)\n```\n\n本文\n")
        move_to(editor, 5)
        assert not hidden(editor, 1)

    def test_Rawでは生のまま(self, editor, qtbot) -> None:
        editor.setPlainText(MERMAID)
        move_to(editor, 5)
        wait_rendered(editor, qtbot)
        editor.set_source_mode(True)
        assert not hidden(editor, 1)
        assert figures(editor) == []

    def test_閉じていないフェンスは生のまま(self, editor, qtbot) -> None:
        editor.setPlainText("```mermaid\ngraph TD\n  A --> B\n\n本文\n")
        move_to(editor, 4)
        assert not hidden(editor, 1)


class TestInitialPass:
    def test_前置きがあっても描き上がりで図になる(self, editor, qtbot) -> None:
        """初回ハイライト時は自分の userData がまだ無い。ラン検出が
        userData に頼り切ると、依頼すら出ない（回帰）。"""
        editor.setPlainText("前置きの文。\n\n" + MERMAID)
        move_to(editor, 7)
        qtbot.waitUntil(lambda: editor._mermaid.done(SOURCE, dark=False), timeout=30000)
        qtbot.waitUntil(lambda: hidden(editor, 3), timeout=5000)
        assert len(figures(editor)) == 1
