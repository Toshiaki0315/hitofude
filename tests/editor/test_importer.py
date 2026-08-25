"""外の形式から取り込む（F-2）。

PDF は **PySide6 同梱の QtPdf** で読む（`QPdfDocument.getAllText()`）。
依存が増えないのが決め手で、py2app の除外にも入っていない。

R3 のとおり `core/` は PySide6 に触れないので、読み取りはここ（`editor/`）。
文字を Markdown に整えるのは `core/imported.py`（F-1）の仕事で、
**この層は「読む」だけ**。
"""

from pathlib import Path

import pytest

from hitofude.editor.exporter import write_pdf
from hitofude.editor.importer import pdf_pages, to_markdown

pytestmark = pytest.mark.gui

NOTE = """# 四半期の振り返り

## 売上

本日の議題は **予算** です。数字は前年より伸びていますが、
下期の見通しは慎重に見ています。

- 新規の契約が 12 件
- 解約は 3 件にとどまった
"""


@pytest.fixture
def sample(qapp, tmp_path: Path) -> Path:
    """自分の書き出しで作った PDF。**外の形式を自分で用意できる**。"""
    return write_pdf(tmp_path / "四半期資料.pdf", NOTE)


class TestPdfPages:
    def test_ページが読める(self, sample) -> None:
        assert len(pdf_pages(sample)) >= 1

    def test_本文が入っている(self, sample) -> None:
        assert "四半期の振り返り" in pdf_pages(sample)[0]

    def test_無いファイルは空(self, qapp, tmp_path: Path) -> None:
        assert pdf_pages(tmp_path / "無い.pdf") == []

    def test_PDFでないファイルは空(self, qapp, tmp_path: Path) -> None:
        """**落とさない。** 読めないことと壊れることは違う。"""
        broken = tmp_path / "偽物.pdf"
        broken.write_text("これは PDF ではありません", encoding="utf-8")
        assert pdf_pages(broken) == []

    def test_空のファイルでも壊れない(self, qapp, tmp_path: Path) -> None:
        empty = tmp_path / "空.pdf"
        empty.write_bytes(b"")
        assert pdf_pages(empty) == []


def image_only_pdf(path: Path) -> Path:
    """文字を持たない PDF（画像を貼っただけ）。

    スクリーンショットを PDF に変換したものがこれにあたる。
    **ページはあるが文字が 1 つも無い。**
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPageSize, QPainter, QPdfWriter

    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    painter = QPainter(writer)
    image = QImage(400, 300, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.gray)
    painter.drawImage(0, 0, image)
    painter.end()
    return path


class TestImageOnly:
    """画像だけの PDF（ユーザー報告）。

    **ノートを作ってはいけない。** 題名だけの空のノートができて、
    読めなかったことも伝わらなかった。
    """

    @pytest.fixture
    def image_pdf(self, qapp, tmp_path: Path) -> Path:
        return image_only_pdf(tmp_path / "スクリーンショット.pdf")

    def test_ページはあるが文字が無い(self, image_pdf) -> None:
        pages = pdf_pages(image_pdf)
        assert pages
        assert all(not page.strip() for page in pages)

    def test_Markdownは空になる(self, image_pdf) -> None:
        """**題名だけ返さない。** 呼び出し側が「読めた」と誤解する。"""
        assert to_markdown(image_pdf) == ""


class TestToMarkdown:
    def test_題名はファイル名(self, sample) -> None:
        assert to_markdown(sample).startswith("# 四半期資料\n")

    def test_本文が残る(self, sample) -> None:
        out = to_markdown(sample)
        assert "下期の見通しは慎重に見ています。" in out

    def test_互換文字が直っている(self, sample) -> None:
        """PDF から出る `本⽇`（U+2F47）のまま入れると検索に掛からない。"""
        out = to_markdown(sample)
        assert "本日の議題" in out
        assert "⽇" not in out

    def test_ページ番号は入らない(self, sample) -> None:
        assert not to_markdown(sample).rstrip().endswith("1")

    def test_読めなければ空(self, qapp, tmp_path: Path) -> None:
        assert to_markdown(tmp_path / "無い.pdf") == ""

    def test_知らない拡張子は空(self, qapp, tmp_path: Path) -> None:
        other = tmp_path / "資料.txt"
        other.write_text("本文", encoding="utf-8")
        assert to_markdown(other) == ""


class FakeOcr:
    """読み取ったことにする。**実物は動かさない。**"""

    def __init__(self, text: str = "読み取った文字") -> None:
        self.text = text
        self.seen: list = []

    def available(self) -> bool:
        return True

    def read(self, image) -> str:
        self.seen.append(image)
        return self.text


class TestImages:
    """画像を文字にして取り込む（ADR-0027）。"""

    def image(self, tmp_path, name="写真.png"):
        path = tmp_path / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        return path

    def test_画像も読める(self, tmp_path) -> None:
        from hitofude.editor import importer

        found = importer.to_markdown(self.image(tmp_path), ocr=FakeOcr("会議メモ"))
        assert "会議メモ" in found

    def test_題名はファイル名(self, tmp_path) -> None:
        from hitofude.editor import importer

        found = importer.to_markdown(self.image(tmp_path, "予算表.jpg"), ocr=FakeOcr())
        assert found.startswith("# 予算表")

    def test_読み手が無ければ空(self, tmp_path) -> None:
        """**読めないのに題名だけのノートを作らない**（今までと同じ作法）。"""
        from hitofude.editor import importer

        assert importer.to_markdown(self.image(tmp_path)) == ""

    def test_選べる拡張子に画像がある(self) -> None:
        from hitofude.editor import importer

        assert "*.png" in importer.FILE_FILTER
        assert "*.jpg" in importer.FILE_FILTER

    def test_読める拡張子は全部フィルタに出す(self) -> None:
        """`.tif` は読めるのにダイアログに出てこなかった（レビュー 2026-08-25）。

        対応を増やすときの付け忘れも、この検査が捕まえる。
        """
        from hitofude.editor import importer

        for suffix in importer.IMAGE_SUFFIXES:
            assert f"*{suffix}" in importer.FILE_FILTER, suffix


class TestScannedPdf:
    """文字の無い PDF は絵から読む（ADR-0027）。"""

    def test_文字が取れなければ読み取りに回す(self, tmp_path, monkeypatch) -> None:
        from hitofude.editor import importer

        monkeypatch.setattr(importer, "pdf_pages", lambda _path: ["", "  "])
        monkeypatch.setattr(
            importer,
            "pdf_page_images",
            lambda _path, _dir, pages=None: [(0, tmp_path / "page-1.png")],
        )
        pdf = tmp_path / "スキャン.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        found = importer.to_markdown(pdf, ocr=FakeOcr("読み取った本文"))
        assert "読み取った本文" in found

    def test_文字が取れるなら読み取らない(self, tmp_path, monkeypatch) -> None:
        """**速くて正確なほうを黙って捨てない。**"""
        from hitofude.editor import importer

        monkeypatch.setattr(importer, "pdf_pages", lambda _path: ["ちゃんと文字がある"])
        reader = FakeOcr()
        pdf = tmp_path / "ふつう.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        importer.to_markdown(pdf, ocr=reader)
        assert reader.seen == []


class TestHybridPdf:
    """文字のページと絵のページが混ざった PDF（ユーザー指摘 2026-08-23）。

    **切り分けは文書ごとではなくページごと。** 1 ページでも文字があれば
    読み取りに回らない作りだったので、**絵だけのページが丸ごと落ちていた**
    （実測: 2 ページの PDF で 2 ページ目が消えた）。
    """

    def pdf(self, tmp_path):
        path = tmp_path / "混在.pdf"
        path.write_bytes(b"%PDF-1.4")
        return path

    def test_文字の無いページだけ読み取る(self, tmp_path, monkeypatch) -> None:
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer, "pdf_pages", lambda _p: ["1 ページ目は文字として入っている本文です", ""]
        )
        asked: list[list[int]] = []

        def fake_images(_path, directory, pages=None):
            wanted = list(pages or [])
            asked.append(wanted)
            # 本物は (ページ番号, 絵) を返す（番号でページに結び付けるため）
            return [(number, directory / f"page-{number + 1}.png") for number in wanted]

        monkeypatch.setattr(importer, "pdf_page_images", fake_images)
        found = importer.to_markdown(self.pdf(tmp_path), ocr=FakeOcr("絵から読んだ文字"))
        assert "1 ページ目は文字として入っている本文です" in found
        assert "絵から読んだ文字" in found
        assert asked == [[1]], "文字のあるページまで絵にしている"

    def test_全部に文字があれば読み取らない(self, tmp_path, monkeypatch) -> None:
        from hitofude.editor import importer

        monkeypatch.setattr(importer, "pdf_pages", lambda _p: ["あるページ", "こちらもある"])
        reader = FakeOcr()
        importer.to_markdown(self.pdf(tmp_path), ocr=reader)
        assert reader.seen == []

    def test_読み取りが使えなくても文字は残す(self, tmp_path, monkeypatch) -> None:
        """**読めないページのせいで、読めたページまで捨てない。**"""
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer, "pdf_pages", lambda _p: ["1 ページ目は文字として入っている本文です", ""]
        )
        found = importer.to_markdown(self.pdf(tmp_path))
        assert "1 ページ目は文字として入っている本文です" in found

    def test_短い実文を読み取りで上書きしない(self, tmp_path, monkeypatch) -> None:
        """**読み取りが外すこともある。** 短くても本物の文字が入っている
        ページを、より短い読み取り結果で潰さない。"""
        from hitofude.editor import importer

        monkeypatch.setattr(importer, "pdf_pages", lambda _p: ["第 2 章 予算について"])
        monkeypatch.setattr(
            importer,
            "pdf_page_images",
            lambda _p, directory, pages=None: [(0, directory / "page-1.png")],
        )
        found = importer.to_markdown(self.pdf(tmp_path), ocr=FakeOcr("第2章"))
        assert "第 2 章 予算について" in found

    def test_ごく短いページも読み取りに回す(self, tmp_path, monkeypatch) -> None:
        """スキャンしたページは**ゴミのような数文字**が取れることがある。
        そこで止まると、そのページは読めないまま終わる。"""
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer, "pdf_pages", lambda _p: ["ちゃんとした本文が入っている 1 ページ目です", "3"]
        )
        monkeypatch.setattr(
            importer,
            "pdf_page_images",
            lambda _p, directory, pages=None: [(1, directory / "page-2.png")],
        )
        found = importer.to_markdown(self.pdf(tmp_path), ocr=FakeOcr("絵から読んだ"))
        assert "絵から読んだ" in found


class TestPdfImages:
    """PDF の中の画像を取り込む（ユーザー要望 2026-08-23）。

    **図が消えるのは痛い。** 文字と図が同じページにあると、これまでは
    文字だけが残っていた。PowerPoint の取り込みと同じく `attachments/` へ
    置いて `![](…)` を入れる。

    **位置は復元できない**（pypdf はページ単位でしか教えない）ので、
    そのページの本文の**後ろにまとめて置く**。
    """

    def test_小さい絵は捨てる(self) -> None:
        """ロゴ・罫線の飾り・透明の詰め物まで拾ってしまう。"""
        from hitofude.core.imported import MIN_IMAGE_SIDE, worth_keeping

        assert worth_keeping(width=MIN_IMAGE_SIDE, height=MIN_IMAGE_SIDE) is True
        assert worth_keeping(width=MIN_IMAGE_SIDE - 1, height=500) is False
        assert worth_keeping(width=500, height=MIN_IMAGE_SIDE - 1) is False

    def test_同じ絵は一度だけ(self) -> None:
        """**各ページのロゴを何枚も貼らない。** 同じ中身は 1 回で足りる。"""
        from hitofude.core.imported import ImagePicker

        picker = ImagePicker()
        assert picker.accepts(b"logo", width=400, height=400) is True
        assert picker.accepts(b"logo", width=400, height=400) is False
        assert picker.accepts(b"figure", width=400, height=400) is True

    def test_多すぎる絵は打ち切る(self) -> None:
        """地紋の入った資料は 1 ページに何十枚も持っている。"""
        from hitofude.core.imported import MAX_IMAGES, ImagePicker

        picker = ImagePicker()
        for number in range(MAX_IMAGES):
            assert picker.accepts(str(number).encode(), width=400, height=400) is True
        assert picker.accepts(b"one more", width=400, height=400) is False

    def test_ページの本文の後ろに置く(self, tmp_path, monkeypatch) -> None:
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer,
            "pdf_pages",
            lambda _p: ["1 ページ目の本文です。読み取りに回らない長さにしてあります"],
        )
        monkeypatch.setattr(
            importer, "pdf_images", lambda _p: {0: [("図.jpg", b"binary", 400, 400)]}
        )
        pdf = tmp_path / "図つき.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        found = importer.to_markdown(
            pdf, save_image=lambda _data, _suffix: "![](attachments/図.jpg)"
        )
        assert found.index("1 ページ目の本文です") < found.index("![](attachments/図.jpg)")

    def test_保存できなければ入れない(self, tmp_path, monkeypatch) -> None:
        """**壊れたリンクを書かない**（`save_attachment` の約束と同じ）。"""
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer, "pdf_pages", lambda _p: ["本文が入っているページです。読み取りには回りません"]
        )
        monkeypatch.setattr(
            importer, "pdf_images", lambda _p: {0: [("図.jpg", b"binary", 400, 400)]}
        )
        pdf = tmp_path / "図つき.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        found = importer.to_markdown(pdf, save_image=lambda _data, _suffix: None)
        assert "![](" not in found

    def test_読み取ったページの絵は貼らない(self, tmp_path, monkeypatch) -> None:
        """**紙の写真と読み取った文字が二重になる。** そのページの絵は
        ページそのもの（実測: スキャン 1 ページで 108KB が付いた）。"""
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer,
            "pdf_pages",
            lambda _p: ["", "文字のあるページです。読み取りに回らない長さにしてあります"],
        )
        monkeypatch.setattr(
            importer,
            "pdf_page_images",
            lambda _p, directory, pages=None: [(0, directory / "page-1.png")],
        )
        monkeypatch.setattr(
            importer,
            "pdf_images",
            lambda _p: {
                0: [("紙.jpg", b"scan", 900, 1200)],
                1: [("図.jpg", b"figure", 400, 400)],
            },
        )
        pdf = tmp_path / "混在.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        saved: list[bytes] = []
        importer.to_markdown(
            pdf,
            save_image=lambda data, _suffix: (saved.append(data), "![](x)")[1],
            ocr=FakeOcr("読み取った文字"),
        )
        assert saved == [b"figure"], "読み取ったページの絵まで貼っている"

    def test_置き場が無ければ取り出さない(self, tmp_path, monkeypatch) -> None:
        """`save_image` を渡さない呼び方（書き出しの検査など）では触らない。"""
        from hitofude.editor import importer

        monkeypatch.setattr(
            importer, "pdf_pages", lambda _p: ["本文が入っているページです。読み取りには回りません"]
        )
        asked: list = []
        monkeypatch.setattr(importer, "pdf_images", lambda p: asked.append(p) or {})
        pdf = tmp_path / "図つき.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        importer.to_markdown(pdf)
        assert asked == []


class TestOcrPagePairing:
    """読み取った文字を**別のページに入れない**（回帰）。

    書き出しに失敗したページがあると、`zip` で 1 つずつずれて
    「5 ページ目の文字が 3 ページ目に入り、5 ページ目は空のまま」になる。
    ページ番号はファイル名（`page-N.png`）に入っているので、それを正とする。
    """

    def test_書き出せないページがあってもずれない(self, tmp_path, monkeypatch) -> None:
        from hitofude.editor import importer

        pages = ["", "", "", "", ""]  # 5 ページとも文字なし
        blanks = [0, 2, 4]

        # 3 ページ目（page-3.png）の書き出しに失敗した想定で、
        # 1 ページ目と 5 ページ目の絵だけが返る
        made = []
        for number in (0, 4):  # 3 ページ目（番号 2）は書き出しに失敗した想定
            path = tmp_path / f"page-{number + 1}.png"
            path.write_bytes(b"x")
            made.append((number, path))
        monkeypatch.setattr(importer, "pdf_page_images", lambda *a, **k: made)

        class Reader:
            def available(self) -> bool:
                return True

            def read(self, image) -> str:
                return f"{image.stem} の中身"

        found = importer._fill_blank_pages(
            tmp_path / "見本.pdf", pages, set(blanks), reader=Reader()
        )
        assert found[0] == "page-1 の中身"
        assert found[2] == ""  # 書き出せなかったページは空のまま
        assert found[4] == "page-5 の中身", "5 ページ目の文字が別の場所へ入った"
