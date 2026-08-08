"""画像の貼り付け・ドロップ（タスク A-2）。

エディタは**どこへ保存するかを知らない**。受け取ったバイト列を渡し、
返ってきた Markdown を挿すだけ。保存先を決めるのは `storage/vault.py` で、
繋ぐのは `ui/main_window.py`（R3 の分担を UI 側でも保つ）。
"""

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QColor, QImage

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui


def png_bytes(color: str = "red") -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray

    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    # 受け皿は変数で保持する（一時オブジェクトを渡すと SIGSEGV で落ちる）
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(storage)


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.setPlainText("本文\n")
    return widget


@pytest.fixture
def saved() -> list[tuple[bytes, str]]:
    return []


@pytest.fixture
def wired(editor, saved) -> MarkdownEditor:
    def handler(data: bytes, suffix: str) -> str:
        saved.append((data, suffix))
        return f"![](attachments/{len(saved)}{suffix})"

    editor.set_attachment_handler(handler)
    return editor


def image_mime() -> QMimeData:
    mime = QMimeData()
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    mime.setImageData(image)
    return mime


def file_mime(path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


class TestPasteImage:
    def test_画像を貼るとリンクが入る(self, wired) -> None:
        wired.insertFromMimeData(image_mime())
        assert "![](attachments/1.png)" in wired.toPlainText()

    def test_バイト列が渡る(self, wired, saved) -> None:
        wired.insertFromMimeData(image_mime())
        assert len(saved) == 1
        assert saved[0][0].startswith(b"\x89PNG")

    def test_クリップボードの画像はpngにする(self, wired, saved) -> None:
        """元の形式が分からないので、可逆な形式に決め打つ。"""
        wired.insertFromMimeData(image_mime())
        assert saved[0][1] == ".png"

    def test_カーソル位置に入る(self, wired) -> None:
        cursor = wired.textCursor()
        cursor.setPosition(2)
        wired.setTextCursor(cursor)
        wired.insertFromMimeData(image_mime())
        assert wired.toPlainText().startswith("本文![](")

    def test_Undo1回で消える(self, wired) -> None:
        before = wired.toPlainText()
        wired.insertFromMimeData(image_mime())
        wired.undo()
        assert wired.toPlainText() == before

    def test_受け口が無ければ何もしない(self, editor) -> None:
        """保存先が繋がっていないのに本文へ壊れたリンクを書かない。"""
        before = editor.toPlainText()
        editor.insertFromMimeData(image_mime())
        assert editor.toPlainText() == before

    def test_保存に失敗したら本文を変えない(self, editor) -> None:
        editor.set_attachment_handler(lambda data, suffix: None)
        before = editor.toPlainText()
        editor.insertFromMimeData(image_mime())
        assert editor.toPlainText() == before

    def test_文字の貼り付けは今まで通り(self, wired, saved) -> None:
        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        mime.setText("ただの文字")
        wired.insertFromMimeData(mime)
        assert "ただの文字" in wired.toPlainText()
        assert saved == []


class TestDropImageFile:
    def test_画像ファイルを落とすとリンクが入る(self, wired, tmp_path) -> None:
        source = tmp_path / "写真.png"
        source.write_bytes(png_bytes())
        wired.insertFromMimeData(file_mime(source))
        assert "![](attachments/1.png)" in wired.toPlainText()

    def test_拡張子を保つ(self, wired, saved, tmp_path) -> None:
        """JPEG を PNG に変換し直さない。無駄に劣化させない。"""
        source = tmp_path / "写真.jpg"
        source.write_bytes(png_bytes())
        wired.insertFromMimeData(file_mime(source))
        assert saved[0][1] == ".jpg"

    def test_中身がそのまま渡る(self, wired, saved, tmp_path) -> None:
        source = tmp_path / "写真.png"
        data = png_bytes("blue")
        source.write_bytes(data)
        wired.insertFromMimeData(file_mime(source))
        assert saved[0][0] == data

    def test_画像以外のファイルは扱わない(self, wired, saved, tmp_path) -> None:
        source = tmp_path / "資料.pdf"
        source.write_bytes(b"%PDF-1.4")
        wired.insertFromMimeData(file_mime(source))
        assert saved == []

    def test_複数落としたら全部入る(self, wired, tmp_path) -> None:
        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        urls = []
        for name in ("a.png", "b.png"):
            source = tmp_path / name
            source.write_bytes(png_bytes())
            urls.append(QUrl.fromLocalFile(str(source)))
        mime.setUrls(urls)

        wired.insertFromMimeData(mime)
        assert wired.toPlainText().count("![](") == 2

    def test_複数でもUndo1回で消える(self, wired, tmp_path) -> None:
        from PySide6.QtCore import QMimeData

        before = wired.toPlainText()
        mime = QMimeData()
        urls = []
        for name in ("a.png", "b.png"):
            source = tmp_path / name
            source.write_bytes(png_bytes())
            urls.append(QUrl.fromLocalFile(str(source)))
        mime.setUrls(urls)

        wired.insertFromMimeData(mime)
        wired.undo()
        assert wired.toPlainText() == before

    def test_読めないファイルでも落ちない(self, wired, tmp_path) -> None:
        missing = tmp_path / "居ない.png"
        wired.insertFromMimeData(file_mime(missing))
        assert wired.toPlainText() == "本文\n"

    def test_URLの貼り付けは今まで通りリンクになる(self, wired) -> None:
        """`Cmd+V` で URL を貼る既存の振る舞いを壊さない（spec §5.5-5）。"""
        from PySide6.QtCore import QMimeData

        wired.selectAll()
        mime = QMimeData()
        mime.setText("https://example.com")
        wired.insertFromMimeData(mime)
        assert "](https://example.com)" in wired.toPlainText()


class TestAcceptance:
    def test_画像を受け付けると答える(self, wired) -> None:
        assert wired.canInsertFromMimeData(image_mime()) is True

    def test_受け口が無ければ画像を受け付けない(self, editor) -> None:
        assert editor.canInsertFromMimeData(image_mime()) is False

    def test_文字は今まで通り受け付ける(self, editor) -> None:
        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        mime.setText("文字")
        assert editor.canInsertFromMimeData(mime) is True


class TestFrontMatterGuard:
    """front matter の前に画像を挿さない。"""

    def test_先頭に貼っても壊れない(self, wired) -> None:
        from hitofude.core import frontmatter

        wired.setPlainText("---\nid: ABC123\n---\n本文\n")
        cursor = wired.textCursor()
        cursor.setPosition(0)
        wired.setTextCursor(cursor)

        wired.insertFromMimeData(image_mime())
        parsed = frontmatter.split(wired.toPlainText())
        assert parsed.present and parsed.meta.get("id") == "ABC123"
