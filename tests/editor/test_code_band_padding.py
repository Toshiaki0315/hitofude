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
