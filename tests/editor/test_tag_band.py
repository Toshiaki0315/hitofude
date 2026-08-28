"""タグの下地をマーカーと同じ帯にする（ユーザー要望 2026-08-28）。

**作りが違っていた。** マーカー（`::…::`）と行内コードは
`painter_overlay` が**文字の実寸の上下に余白を取った角丸**で描くのに、
タグだけ `QTextCharFormat.setBackground()` だった——Qt は**行の高さ
いっぱいの四角**を塗るので、角が立ち、上下が本文の行送りぶんまで
伸びる。タグを 2 行続けると下地どうしが接して見える（ユーザー報告）。

表の中では既に帯として描いている（`_cell_band`）ので、本文だけが
取り残されていた形。
"""

import pytest
from PySide6.QtCore import Qt

from hitofude.core.models import SpanType
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind
from tests.editor.test_painter_overlay import away, visible_decorations

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def bands(editor: MarkdownEditor, name: str) -> list:
    return [
        d
        for d in visible_decorations(editor)
        if d.kind is DecorationKind.INLINE_BAND and d.text == name
    ]


class TestTagBand:
    def test_タグに帯が出る(self, editor) -> None:
        """**これが本題。** マーカーと同じ仕組みで描く。"""
        away(editor, "本文 #テスト を書く\n")
        assert len(bands(editor, "tag")) == 1

    def test_マーカーと同じ高さ(self, editor) -> None:
        """上下の余白が揃うこと。"""
        away(editor, "::目立つ:: と #テスト\n")
        marker = bands(editor, "highlight")[0]
        tag = bands(editor, "tag")[0]
        assert tag.rect.height() == pytest.approx(marker.rect.height(), abs=0.5)
        assert tag.rect.top() == pytest.approx(marker.rect.top(), abs=0.5)

    def test_行の高さいっぱいには塗らない(self, editor) -> None:
        """**文字書式の背景をやめる。** 残っていると Qt が四角を塗り、
        角丸の帯の下から角が出る。
        """
        away(editor, "本文 #テスト を書く\n")
        block = editor.document().findBlockByNumber(0)
        for run in block.layout().formats():
            # **`color().isValid()` では見分けられない。** 背景を持たない
            # 書式のブラシも「有効な黒・α255」を返す（実測）。塗るか
            # どうかはブラシの種類で見る
            assert run.format.background().style() is Qt.BrushStyle.NoBrush, (
                "タグに文字書式の背景が残っている"
            )

    def test_階層タグも1つの帯(self, editor) -> None:
        away(editor, "本文 #hitofude/使い方 を書く\n")
        assert len(bands(editor, "tag")) == 1


class TestStillTagged:
    """**色と当たり判定は変えない。**"""

    def test_文字色は残る(self, editor) -> None:
        """**下地をやめても字の色は残す。** タグだと分かる手掛かり。"""
        from hitofude.theme import LIGHT

        away(editor, "本文 #テスト を書く\n")
        block = editor.document().findBlockByNumber(0)
        colors = {
            run.format.foreground().color().name().upper() for run in block.layout().formats()
        }
        assert LIGHT.tag_foreground.upper() in colors

    def test_走査は今までどおり(self, editor) -> None:
        from hitofude.core.inline_scanner import scan

        found = [span for span in scan("本文 #テスト を書く") if span.type is SpanType.TAG]
        assert len(found) == 1
