"""貼り付け元から添付を取り出す部分（`editor/editor_widget.py` から分離）。

エディタを通した経路は `test_paste_image.py` が見る。ここは**取り出しだけ**を
直に確かめる。エディタの状態を要らない変換なので、単体で試せる。
"""

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QColor, QImage

from hitofude.editor.attachments import encode_image, extract, looks_like_attachment

pytestmark = pytest.mark.gui


def image_mime() -> QMimeData:
    mime = QMimeData()
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    mime.setImageData(image)
    return mime


def url_mime(*paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


class TestLooksLikeAttachment:
    def test_画像はそう答える(self, qapp) -> None:
        assert looks_like_attachment(image_mime()) is True

    def test_画像ファイルもそう答える(self, qapp, tmp_path) -> None:
        assert looks_like_attachment(url_mime(tmp_path / "a.png")) is True

    def test_存在しなくてもそう答える(self, qapp, tmp_path) -> None:
        """読めるかは見ない。読めなかったときに `file://…` を本文へ落とさない。"""
        assert looks_like_attachment(url_mime(tmp_path / "居ない.png")) is True

    def test_画像でないファイルは違う(self, qapp, tmp_path) -> None:
        assert looks_like_attachment(url_mime(tmp_path / "資料.pdf")) is False

    def test_遠くのURLは違う(self, qapp) -> None:
        """`http://…/a.png` を落とされても取りに行かない。"""
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/a.png")])
        assert looks_like_attachment(mime) is False

    def test_ただの文字は違う(self, qapp) -> None:
        mime = QMimeData()
        mime.setText("ただの文字")
        assert looks_like_attachment(mime) is False


class TestExtract:
    def test_クリップボードの画像はpngで返る(self, qapp) -> None:
        found = extract(image_mime())
        assert len(found) == 1
        assert found[0][0].startswith(b"\x89PNG")
        assert found[0][1] == ".png"

    def test_ファイルは中身と拡張子で返る(self, qapp, tmp_path, write_png) -> None:
        source = write_png(tmp_path / "写真.jpg")
        data, suffix = extract(url_mime(source))[0]
        assert data == source.read_bytes()
        assert suffix == ".jpg"

    def test_読めないファイルは落とす(self, qapp, tmp_path) -> None:
        assert extract(url_mime(tmp_path / "居ない.png")) == []

    def test_読める分だけ返す(self, qapp, tmp_path, write_png) -> None:
        good = write_png(tmp_path / "ある.png")
        assert len(extract(url_mime(good, tmp_path / "無い.png"))) == 1

    def test_画像以外は返さない(self, qapp, tmp_path) -> None:
        (tmp_path / "資料.pdf").write_bytes(b"%PDF")
        assert extract(url_mime(tmp_path / "資料.pdf")) == []

    def test_文字だけなら空(self, qapp) -> None:
        mime = QMimeData()
        mime.setText("ただの文字")
        assert extract(mime) == []


class TestEncodeImage:
    def test_PNGになる(self, qapp) -> None:
        image = QImage(4, 4, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        assert encode_image(image).startswith(b"\x89PNG")

    def test_空の画像は空で返る(self, qapp) -> None:
        """壊れた貼り付けで本文へ空のリンクを書かない。"""
        assert encode_image(QImage()) == b""

    def test_画像でないものを渡しても落ちない(self, qapp) -> None:
        assert encode_image(None) == b""
