"""コードの帯の上下の余白（ユーザー要望 2026-08-28）。

**帯の中の余白は隠したフェンス行が作る。** ブロックの余白は使えない
（R5。`QPlainTextDocumentLayout` が無視するうえ Undo を 1 段食う）ので、
`_pad_band_edge` が縁の行の文字を**透明のまま少しだけ大きく**して高さを
残している（ADR-0004 と同じレバー）。

それが**開き側にしか当たっていなかった**——実測で上 8px・下 2px。
帯が下だけ詰まって見える。上下を揃え、余白そのものも広げる。
"""

import pytest
from PySide6.QtGui import QTextCursor

from hitofude.core.models import BlockType
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.highlighter import BAND_EDGE_PADDING

pytestmark = pytest.mark.gui

NOTE = "前の本文\n\n```python\nprint(1)\nprint(2)\n```\n\n後の本文\n"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setPlainText(NOTE)
    widget.moveCursor(QTextCursor.MoveOperation.End)
    return widget


def height_of(editor: MarkdownEditor, kind: BlockType) -> float:
    block = editor.document().begin()
    while block.isValid():
        data = block.userData()
        if data is not None and data.info.type is kind:
            return editor.blockBoundingGeometry(block).height()
        block = block.next()
        continue
    raise AssertionError(f"{kind} の行が無い")


class TestBandEdges:
    def test_閉じ側にも余白がある(self, editor) -> None:
        """**これが本題。** 下だけ詰まっていた（実測 2px）。"""
        assert height_of(editor, BlockType.CODE_FENCE_CLOSE) >= BAND_EDGE_PADDING

    def test_上下が揃っている(self, editor) -> None:
        """開きだけ広いと、帯が下にずれて見える。"""
        top = height_of(editor, BlockType.CODE_FENCE_OPEN)
        bottom = height_of(editor, BlockType.CODE_FENCE_CLOSE)
        assert top == pytest.approx(bottom, abs=1.5)

    def test_本文の行より低い(self, editor) -> None:
        """**余白であって行ではない。** 本文と同じ高さになると、
        空行が 1 つ増えたようにしか見えない。
        """
        assert height_of(editor, BlockType.CODE_FENCE_OPEN) < height_of(editor, BlockType.PARAGRAPH)


class TestStillHidden:
    """**記号は見せない**（R4 の約束は変えない）。"""

    def test_フェンスの字は透明(self, editor) -> None:
        document = editor.document()
        block = document.begin()
        while block.isValid():
            data = block.userData()
            if data is not None and data.info.type is BlockType.CODE_FENCE_CLOSE:
                layout = block.layout()
                formats = layout.formats()
                assert formats, "書式が付いていない"
                for run in formats:
                    color = run.format.foreground().color()
                    assert color.alpha() == 0 or run.format.fontPointSize() <= 1.0
                return
            block = block.next()
        raise AssertionError("閉じフェンスが無い")


NOTE_BLOCK = "前の本文\n\n:::note info\n気をつけること\n:::\n\n後の本文\n"
MATH_BLOCK = "前の本文\n\n$$\nE = mc^2\n$$\n\n後の本文\n"


def heights_of(editor: MarkdownEditor, kind: BlockType) -> list[float]:
    found: list[float] = []
    block = editor.document().begin()
    while block.isValid():
        data = block.userData()
        if data is not None and data.info.type is kind:
            found.append(editor.blockBoundingGeometry(block).height())
        block = block.next()
    return found


class TestOtherBands:
    """注釈と数式の帯も同じ作り（ユーザー要望 2026-08-28）。

    どれも「隠した縁の行に高さを持たせる」という同じ仕組みで、
    コードだけ直すと**同じ見た目の箱で余白が揃わない**。
    """

    @pytest.fixture
    def shown(self, qtbot):
        def build(text: str) -> MarkdownEditor:
            widget = MarkdownEditor()
            qtbot.addWidget(widget)
            widget.resize(800, 400)
            widget.show()
            qtbot.waitExposed(widget)
            widget.setPlainText(text)
            widget.moveCursor(QTextCursor.MoveOperation.End)
            return widget

        return build

    def test_注釈の上下が揃う(self, shown) -> None:
        editor = shown(NOTE_BLOCK)
        found = heights_of(editor, BlockType.NOTE_DELIMITER)
        assert len(found) == 2, "開きと閉じが揃っていない"
        assert found[0] == pytest.approx(found[1], abs=1.5)

    def test_注釈の閉じにも余白がある(self, shown) -> None:
        editor = shown(NOTE_BLOCK)
        assert heights_of(editor, BlockType.NOTE_DELIMITER)[-1] >= BAND_EDGE_PADDING

    def test_数式の上下が揃う(self, shown) -> None:
        editor = shown(MATH_BLOCK)
        found = heights_of(editor, BlockType.MATH_DELIMITER)
        assert len(found) == 2, "開きと閉じが揃っていない"
        assert found[0] == pytest.approx(found[1], abs=1.5)

    def test_数式の閉じにも余白がある(self, shown) -> None:
        editor = shown(MATH_BLOCK)
        assert heights_of(editor, BlockType.MATH_DELIMITER)[-1] >= BAND_EDGE_PADDING


class TestFigureBands:
    """図として描く帯（数式・Mermaid）も同じ（ユーザー要望 2026-08-28）。

    こちらは `_apply_figure` が**別経路で**縁の余白を当てており、
    そこも開き行だけだった。文字の帯を直しても図の帯が残る形だったので、
    両方を縛る。
    """

    @pytest.fixture
    def shown(self, qtbot):
        def build(text: str) -> MarkdownEditor:
            widget = MarkdownEditor()
            qtbot.addWidget(widget)
            widget.resize(800, 400)
            widget.show()
            qtbot.waitExposed(widget)
            widget.setPlainText(text)
            widget.moveCursor(QTextCursor.MoveOperation.End)
            return widget

        return build

    def test_図のフェンスも上下が揃う(self, shown) -> None:
        editor = shown("前の本文\n\n```mermaid\ngraph TD\n  A-->B\n```\n\n後の本文\n")
        opens = heights_of(editor, BlockType.CODE_FENCE_OPEN)
        closes = heights_of(editor, BlockType.CODE_FENCE_CLOSE)
        assert opens and closes
        assert opens[0] == pytest.approx(closes[0], abs=1.5)


INDENTED = "書き方はこうです。\n\n    :::note info\n    お知らせです。\n    :::\n\n末尾\n"


class TestIndentedCode:
    """字下げ（4 字）のコードブロック（ユーザー報告 2026-08-28）。

    **フェンス行が無い。** 3 行とも `CODE_FENCE_BODY` に分類されるので、
    余白を載せる縁の行が存在しない——帯が中身にぴったり張り付いて、
    上下の余白がゼロになっていた（使い方ノートの `:::note` の例で報告）。

    縁が無いなら**描く側で空ける**。帯の上下は空行に食い込むが、字下げの
    コードは前後に空行が要る（CommonMark）ので本文には掛からない。
    """

    @pytest.fixture
    def shown(self, qtbot):
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.resize(800, 400)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setPlainText(INDENTED)
        widget.moveCursor(QTextCursor.MoveOperation.End)
        return widget

    def bands(self, editor):
        from hitofude.editor.painter_overlay import DecorationKind
        from tests.editor.test_painter_overlay import visible_decorations

        return [d for d in visible_decorations(editor) if d.kind is DecorationKind.CODE_BACKGROUND]

    def test_帯が出る(self, shown) -> None:
        assert len(self.bands(shown)) == 3

    def test_上に余白がある(self, shown) -> None:
        """**これが本題。** 1 行目の字が帯の上端に張り付いていた。"""
        from hitofude.editor.painter_overlay import BAND_EDGE_PADDING

        editor = shown
        block = editor.document().findBlockByNumber(2)
        top = editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top()
        assert self.bands(editor)[0].rect.top() <= top - BAND_EDGE_PADDING + 1

    def test_下にも余白がある(self, shown) -> None:
        from hitofude.editor.painter_overlay import BAND_EDGE_PADDING

        editor = shown
        block = editor.document().findBlockByNumber(4)
        bottom = editor.blockBoundingGeometry(block).translated(editor.contentOffset()).bottom()
        assert self.bands(editor)[-1].rect.bottom() >= bottom + BAND_EDGE_PADDING - 1

    def test_フェンスのときは広げない(self, shown, qtbot) -> None:
        """**二重に空けない。** フェンスなら縁の行が既に余白を持っている。"""
        editor = shown
        editor.setPlainText("本文\n\n```python\nprint(1)\n```\n\n末尾\n")
        editor.moveCursor(QTextCursor.MoveOperation.End)
        qtbot.wait(10)
        body = editor.document().findBlockByNumber(3)
        top = editor.blockBoundingGeometry(body).translated(editor.contentOffset()).top()
        middle = [d for d in self.bands(editor) if abs(d.rect.top() - top) < 1.0]
        assert middle, "中身の行の帯が行の高さと合っていない（広げてしまった）"
