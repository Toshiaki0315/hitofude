"""エクスポートのテスト（タスク 6-3 / spec §9 Phase 6, R2）。"""

from pathlib import Path

import pytest

from hitofude.editor.exporter import to_html, write_html, write_pdf

pytestmark = pytest.mark.gui

SOURCE = """---
id: ABC123
pinned: false
---

# 会議メモ

これは**強調**で、これは`コード`。

- 項目 1
- 項目 2

> 引用

```python
x = 1
```

[リンク](https://example.com)
"""


class TestHtml:
    def test_完結したHTMLになる(self, qapp) -> None:
        html = to_html(SOURCE, title="会議メモ")
        assert html.startswith("<!doctype html>")
        assert "</html>" in html

    def test_見出しが変換される(self, qapp) -> None:
        assert "会議メモ" in to_html(SOURCE)

    def test_強調が変換される(self, qapp) -> None:
        html = to_html(SOURCE)
        assert "font-weight:700" in html or "<b" in html or "<strong" in html

    def test_front_matterは出さない(self, qapp) -> None:
        """`id` や `modified` が書き出した文書の先頭に出ても意味がない。"""
        assert "ABC123" not in to_html(SOURCE)

    def test_タイトルを埋められる(self, qapp) -> None:
        assert "<title>会議メモ</title>" in to_html(SOURCE, title="会議メモ")

    def test_タイトルのHTMLはエスケープする(self, qapp) -> None:
        assert "<title>&lt;script&gt;</title>" in to_html(SOURCE, title="<script>")

    def test_外部リソースを参照しない(self, qapp) -> None:
        """配布した HTML が単体で開けること。"""
        html = to_html(SOURCE)
        assert "<link" not in html
        assert "<script" not in html

    def test_ファイルに書ける(self, qapp, tmp_path: Path) -> None:
        target = write_html(tmp_path / "out.html", SOURCE, title="会議メモ")
        assert target.is_file()
        assert "会議メモ" in target.read_text(encoding="utf-8")

    def test_空でも壊れない(self, qapp) -> None:
        assert to_html("").startswith("<!doctype html>")


class TestPdf:
    def test_PDFが書ける(self, qapp, tmp_path: Path) -> None:
        target = write_pdf(tmp_path / "out.pdf", SOURCE)
        assert target.is_file()
        assert target.stat().st_size > 0

    def test_PDFの署名で始まる(self, qapp, tmp_path: Path) -> None:
        target = write_pdf(tmp_path / "out.pdf", SOURCE)
        assert target.read_bytes().startswith(b"%PDF-")

    def test_空でも壊れない(self, qapp, tmp_path: Path) -> None:
        assert write_pdf(tmp_path / "empty.pdf", "").is_file()


class TestSourceUntouched:
    """R1 / R2: エクスポートは一方通行。ソースへは戻さない。"""

    def test_元の文字列を変えない(self, qapp) -> None:
        before = SOURCE
        to_html(SOURCE)

        assert before == SOURCE

    def test_マーカーは変換先にだけ影響する(self, qapp, tmp_path: Path) -> None:
        source = tmp_path / "note.md"
        source.write_text(SOURCE, encoding="utf-8")
        write_html(tmp_path / "out.html", source.read_text(encoding="utf-8"))
        assert source.read_text(encoding="utf-8") == SOURCE
