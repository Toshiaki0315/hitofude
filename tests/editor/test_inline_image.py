"""本文の中に画像を表示する（タスク A-2 後半）。

**R5 に触れない。** `QTextBlockFormat` は使わず、R4 と同じ「文字の大きさ」
というレバーだけで高さを作る。記号を 0.5pt に潰し、1 文字だけ大きくする。
行全体を大きくすると横に伸びて折り返し、高さが跳ねる（実測: 240pt で 788px）。
"""

from pathlib import Path

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path: Path) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(900, 700)
    widget.set_image_base(tmp_path)
    widget.show()
    return widget


def height_of(editor: MarkdownEditor, line: int) -> float:
    document = editor.document()
    return document.documentLayout().blockBoundingRect(document.findBlockByNumber(line)).height()


def images_in(editor: MarkdownEditor) -> list:
    return [d for d in visible_decorations(editor) if d.kind is DecorationKind.IMAGE]


class TestHeight:
    def test_画像行が高くなる(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "attachments" / "a.png", 300, 150)
        editor.setPlainText("本文\n![](attachments/a.png)\n本文\n")
        assert height_of(editor, 1) > height_of(editor, 0) * 3

    def test_絵の高さに見合う(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "attachments" / "a.png", 300, 150)
        editor.setPlainText("![](attachments/a.png)\n")
        assert height_of(editor, 0) == pytest.approx(150, abs=30)

    def test_縦長の絵ならもっと高い(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "yoko.png", 300, 100)
        write_png(tmp_path / "tate.png", 300, 400)
        editor.setPlainText("![](yoko.png)\n![](tate.png)\n")
        assert height_of(editor, 1) > height_of(editor, 0) * 2

    def test_他の行の高さは変わらない(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png")
        editor.setPlainText("本文\n")
        plain = height_of(editor, 0)
        editor.setPlainText("本文\n![](a.png)\n")
        assert height_of(editor, 0) == plain

    def test_読めない画像は高くしない(self, editor) -> None:
        """壊れたリンクは文字のまま見せる。空白だけ空くより分かる。"""
        editor.setPlainText("本文\n![](attachments/居ない.png)\n")
        assert height_of(editor, 1) == pytest.approx(height_of(editor, 0), abs=1)

    def test_本文は変わらない(self, editor, tmp_path, write_png) -> None:
        """R1: 見た目を変えてもソースは触らない。"""
        write_png(tmp_path / "a.png")
        source = "本文\n![](a.png)\n本文\n"
        editor.setPlainText(source)
        assert editor.toPlainText() == source

    def test_Undoを消費しない(self, editor, tmp_path, write_png) -> None:
        """ADR-0002 が `QTextBlockFormat` を却下した理由に触れないこと。"""
        write_png(tmp_path / "a.png")
        editor.setPlainText("![](a.png)\n")
        editor.textCursor().insertText("追記")
        editor.undo()
        assert "追記" not in editor.toPlainText()

    def test_文中の画像は高くしない(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png")
        editor.setPlainText("本文\nこれは ![](a.png) です\n")
        assert height_of(editor, 1) == pytest.approx(height_of(editor, 0), abs=1)


class TestDrawing:
    def test_画像が描画対象に入る(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png")
        editor.setPlainText("![](a.png)\n")
        assert len(images_in(editor)) == 1

    def test_絵の大きさで置かれる(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png", 300, 150)
        editor.setPlainText("![](a.png)\n")
        rect = images_in(editor)[0].rect
        assert rect.width() == 300
        assert rect.height() == 150

    def test_行の中に収まる(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png", 300, 150)
        editor.setPlainText("本文\n![](a.png)\n本文\n")
        image = images_in(editor)[0]
        document = editor.document()
        block = document.findBlockByNumber(1)
        geometry = document.documentLayout().blockBoundingRect(block)
        assert image.rect.height() <= geometry.height() + 1

    def test_読めない画像は描かない(self, editor) -> None:
        editor.setPlainText("![](居ない.png)\n")
        assert images_in(editor) == []

    def test_描いても落ちない(self, editor, tmp_path, write_png) -> None:
        from PySide6.QtGui import QColor, QImage

        write_png(tmp_path / "a.png")
        editor.setPlainText("![](a.png)\n")
        image = QImage(editor.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        editor.render(image)


class TestCursorInside:
    """カーソルを入れても高さを変えない（決めた方針）。

    他のマーカーと同じ「中に入ると記号が現れる」を当てると、行の高さが
    縮んで下の全部が飛び上がる。`docs/manual_test.md` §2 の
    「行の高さが変わらない」約束を破るため、画像だけ別扱いにする。
    """

    def test_カーソルを入れても高さが変わらない(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png", 300, 150)
        editor.setPlainText("本文\n![](a.png)\n本文\n")
        before = height_of(editor, 1)

        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(1).position() + 2)
        editor.setTextCursor(cursor)
        assert height_of(editor, 1) == before

    def test_カーソルを入れても絵が消えない(self, editor, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png")
        editor.setPlainText("![](a.png)\n")
        cursor = editor.textCursor()
        cursor.setPosition(2)
        editor.setTextCursor(cursor)
        assert len(images_in(editor)) == 1

    def test_ソースモードでは文字に戻る(self, editor, tmp_path, write_png) -> None:
        """`Cmd+/` はすべてを生の Markdown で見せる。"""
        write_png(tmp_path / "a.png", 300, 150)
        editor.setPlainText("本文\n![](a.png)\n")
        tall = height_of(editor, 1)

        editor.toggle_source_mode()
        assert height_of(editor, 1) < tall


class TestExternalChange:
    def test_差し替えたら読み直せる(self, editor, tmp_path, write_png) -> None:
        import os

        path = write_png(tmp_path / "a.png", 300, 100)
        editor.setPlainText("![](a.png)\n")
        first = height_of(editor, 0)

        write_png(tmp_path / "a.png", 300, 400)
        os.utime(path, (0, 0))
        editor.refresh_images()
        assert height_of(editor, 0) > first
