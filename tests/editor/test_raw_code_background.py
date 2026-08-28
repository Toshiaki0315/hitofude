"""Raw ではコードの下地も描かない（ユーザー判断 2026-08-28）。

**Raw は飾りを描かないモード**（`painter_overlay` が丸ごと降りる。
記号を見せるのに罫線やチェック印が重なると読めないため）。ところが
コード行の**文字書式が背景を持っていた**ので、帯が消えたあとにそれだけ
が残り、「文字の幅・行の高さいっぱい」の角ばった灰色が出ていた
（ユーザー報告の画像）。

帯とは別の仕組みが露出した状態なので、文字書式の背景をやめる。
Raw でのコードの手掛かりは**等幅と文字色**が担う。
"""

import pytest
from PySide6.QtCore import Qt

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind
from tests.editor.test_painter_overlay import visible_decorations

pytestmark = pytest.mark.gui

NOTE = "本文\n\n```python\nprint(1)\n```\n\n末尾\n"
FIGURE = "本文\n\n```mermaid\ngraph TD\n  A-->B\n```\n\n末尾\n"


@pytest.fixture
def editor(qtbot):
    def build(text: str, *, raw: bool) -> MarkdownEditor:
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.resize(800, 400)
        widget.show()
        qtbot.waitExposed(widget)
        widget.setPlainText(text)
        widget.set_source_mode(raw)
        return widget

    return build


def backgrounds(widget: MarkdownEditor) -> list:
    found = []
    block = widget.document().begin()
    while block.isValid():
        for run in block.layout().formats():
            if run.format.background().style() is not Qt.BrushStyle.NoBrush:
                found.append((block.blockNumber(), run.format.background().color().name()))
        block = block.next()
    return found


class TestRaw:
    def test_コードに下地を塗らない(self, editor) -> None:
        """**これが本題。** 帯が消えたあとに残っていた。"""
        assert backgrounds(editor(NOTE, raw=True)) == []

    def test_図の生表示も同じ(self, editor) -> None:
        assert backgrounds(editor(FIGURE, raw=True)) == []

    def test_等幅と文字色は残る(self, editor) -> None:
        """**手掛かりまで消さない。** コードだと分かる必要はある。"""
        from hitofude.theme import LIGHT

        widget = editor(NOTE, raw=True)
        block = widget.document().findBlockByNumber(3)
        runs = block.layout().formats()
        assert runs, "書式が付いていない"
        colors = {run.format.foreground().color().name().upper() for run in runs}
        assert LIGHT.code_foreground.upper() in colors


class TestNormal:
    """**通常表示は変えない。** 下地は帯が描いている。"""

    def test_帯は今までどおり出る(self, editor) -> None:
        widget = editor(NOTE, raw=False)
        bands = [d for d in visible_decorations(widget) if d.kind is DecorationKind.CODE_BACKGROUND]
        assert bands

    def test_図の帯も出る(self, editor) -> None:
        widget = editor(FIGURE, raw=False)
        bands = [
            d for d in visible_decorations(widget) if d.kind is DecorationKind.FIGURE_BACKGROUND
        ]
        assert bands
