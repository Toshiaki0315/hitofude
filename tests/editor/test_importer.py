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
