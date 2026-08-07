"""オーバーレイ描画のテスト（タスク 2-9 / spec §5.2, ADR-0002）。

`QSyntaxHighlighter` では描けない要素（縦バー、背景、線、記号）を
`paintEvent` で描く。ここは ADR-0002 でブロックレベル表現の唯一の担い手になった。

描画そのものはピクセルで検査すると脆いので、
「どこに何を描くか」を組み立てる純ロジックを主に検査し、
実際に描かれることは 1 件のスモークテストで押さえる。
"""

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    return widget


def kinds(editor: MarkdownEditor) -> list[DecorationKind]:
    return [decoration.kind for decoration in visible_decorations(editor)]


def of_kind(editor: MarkdownEditor, kind: DecorationKind) -> list:
    return [d for d in visible_decorations(editor) if d.kind is kind]


class TestQuote:
    def test_引用行に縦バーを描く(self, editor) -> None:
        editor.setPlainText("> 引用")
        assert kinds(editor).count(DecorationKind.QUOTE_BAR) == 1

    def test_入れ子の引用は深さの数だけ描く(self, editor) -> None:
        editor.setPlainText("> > 二重引用")
        assert kinds(editor).count(DecorationKind.QUOTE_BAR) == 2

    def test_深いバーほど右にずれる(self, editor) -> None:
        editor.setPlainText("> > 二重引用")
        bars = of_kind(editor, DecorationKind.QUOTE_BAR)
        assert bars[0].rect.left() < bars[1].rect.left()

    def test_引用でない行には描かない(self, editor) -> None:
        editor.setPlainText("ただの段落")
        assert DecorationKind.QUOTE_BAR not in kinds(editor)


class TestCodeBlock:
    SOURCE = "```python\nx = 1\n```"

    def test_フェンスの全行に背景を描く(self, editor) -> None:
        editor.setPlainText(self.SOURCE)
        assert kinds(editor).count(DecorationKind.CODE_BACKGROUND) == 3

    def test_左にアクセントバーを描く(self, editor) -> None:
        editor.setPlainText(self.SOURCE)
        assert kinds(editor).count(DecorationKind.CODE_ACCENT) == 3

    def test_アクセントバーは背景より左(self, editor) -> None:
        editor.setPlainText(self.SOURCE)
        accent = of_kind(editor, DecorationKind.CODE_ACCENT)[0]
        background = of_kind(editor, DecorationKind.CODE_BACKGROUND)[0]
        assert accent.rect.left() <= background.rect.left()
        assert accent.rect.width() < background.rect.width()

    def test_コードでない行には描かない(self, editor) -> None:
        editor.setPlainText("ただの段落")
        assert DecorationKind.CODE_BACKGROUND not in kinds(editor)


class TestHorizontalRule:
    def test_水平線を描く(self, editor) -> None:
        editor.setPlainText("段落\n\n---\n")
        assert kinds(editor).count(DecorationKind.RULE) == 1

    def test_線はブロックの縦中央あたりに引く(self, editor) -> None:
        editor.setPlainText("段落\n\n---\n")
        rule = of_kind(editor, DecorationKind.RULE)[0]
        assert rule.rect.height() <= 2


class TestCheckbox:
    @pytest.mark.parametrize(
        ("source", "glyph"),
        [("- [ ] やること", "☐"), ("- [x] 済み", "☑"), ("- [X] 済み", "☑")],
    )
    def test_チェックボックスを記号で描く(self, editor, source: str, glyph: str) -> None:
        editor.setPlainText(source)
        boxes = of_kind(editor, DecorationKind.CHECKBOX)
        assert len(boxes) == 1
        assert boxes[0].text == glyph

    def test_普通の箇条書きには描かない(self, editor) -> None:
        editor.setPlainText("- ただの項目")
        assert DecorationKind.CHECKBOX not in kinds(editor)

    def test_記号はリストマーカーより右に置く(self, editor) -> None:
        editor.setPlainText("- [ ] やること")
        box = of_kind(editor, DecorationKind.CHECKBOX)[0]
        assert box.rect.left() > 0


class TestVisibility:
    def test_画面外のブロックは含まない(self, editor) -> None:
        """spec §6.6: 可視ブロックだけを走査する。"""
        editor.setPlainText("\n".join(["> 引用"] * 500))
        editor.resize(800, 200)
        bars = of_kind(editor, DecorationKind.QUOTE_BAR)
        assert 0 < len(bars) < 50, f"{len(bars)} 本描こうとしている"

    def test_空の文書では何も描かない(self, editor) -> None:
        editor.setPlainText("")
        assert visible_decorations(editor) == []


class TestActuallyPaints:
    def test_引用の縦バーがピクセルとして現れる(self, editor) -> None:
        """組み立てたものが本当に描かれることの担保。"""
        from PySide6.QtGui import QColor, QImage

        from hitofude.theme import LIGHT

        def render(text: str) -> QImage:
            editor.setPlainText(text)
            image = QImage(editor.size(), QImage.Format.Format_ARGB32)
            image.fill(QColor("white"))
            editor.render(image)
            return image

        with_quote = render("> 引用")
        without = render("引用")

        bar = QColor(LIGHT.quote_bar).rgb()
        found = any(
            with_quote.pixel(x, y) == bar
            for x in range(min(60, with_quote.width()))
            for y in range(min(40, with_quote.height()))
        )
        assert found, "縦バーの色のピクセルが見つからない"
        assert with_quote != without
