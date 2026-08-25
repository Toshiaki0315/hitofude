"""エクスポートのテスト（タスク 6-3 / spec §9 Phase 6, R2）。"""

from pathlib import Path

import pytest

from hitofude.editor.exporter import to_html, write_html, write_markdown, write_pdf

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


class TestPrint:
    """印刷（C-9）。

    **書き出しと同じ `QTextDocument` を通す。** 経路を分けると、印刷だけ
    画像が出ない・数式が違う、といった食い違いが後から生える。
    ここはプリンタを PDF に向けて、書き出しと同じものが出ることを見る。
    """

    def _to_pdf(self, path: Path):
        from PySide6.QtPrintSupport import QPrinter

        from hitofude.editor.exporter import new_printer

        printer = new_printer()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path))
        return printer

    def test_用紙はA4(self, qapp) -> None:
        from PySide6.QtGui import QPageSize

        from hitofude.editor.exporter import new_printer

        assert new_printer().pageLayout().pageSize().id() == QPageSize.PageSizeId.A4

    def test_余白が付いている(self, qapp) -> None:
        """余白ゼロで刷ると端が切れる。書き出しと同じ 18mm。"""
        from hitofude.editor.exporter import PDF_MARGIN_MM, new_printer

        margins = new_printer().pageLayout().margins()
        assert margins.left() == pytest.approx(PDF_MARGIN_MM)

    def test_プリンタへ流せる(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import print_document

        target = tmp_path / "printed.pdf"
        print_document(self._to_pdf(target), SOURCE)
        assert target.read_bytes().startswith(b"%PDF-")

    def test_書き出しと同じ大きさになる(self, qapp, tmp_path: Path) -> None:
        """同じ道を通っている証拠。片方だけ中身が欠ければ大きさがずれる。"""
        from hitofude.editor.exporter import print_document

        printed = tmp_path / "printed.pdf"
        print_document(self._to_pdf(printed), SOURCE)
        written = write_pdf(tmp_path / "written.pdf", SOURCE)
        assert printed.stat().st_size == pytest.approx(written.stat().st_size, rel=0.02)

    def test_空でも壊れない(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import print_document

        target = tmp_path / "empty.pdf"
        print_document(self._to_pdf(target), "")
        assert target.is_file()

    def test_元の文字列を変えない(self, qapp, tmp_path: Path) -> None:
        """R1: 印刷も一方通行。"""
        from hitofude.editor.exporter import print_document

        text = SOURCE
        print_document(self._to_pdf(tmp_path / "out.pdf"), text)
        assert text == SOURCE


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


class TestMarkdown:
    """Markdown での書き出し（ユーザー要望）。"""

    def test_ファイルに書ける(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import write_markdown

        target = write_markdown(tmp_path / "out.md", SOURCE)
        assert target.is_file()

    def test_マーカーがそのまま残る(self, qapp, tmp_path: Path) -> None:
        """R1: Markdown 書き出しは変換ではない。ソースがそのまま出る。"""
        from hitofude.editor.exporter import write_markdown

        target = write_markdown(tmp_path / "out.md", SOURCE)
        written = target.read_text(encoding="utf-8")
        assert "**強調**" in written
        assert "`コード`" in written
        assert "[リンク](https://example.com)" in written
        assert "```python" in written

    def test_front_matterは出さない(self, qapp, tmp_path: Path) -> None:
        """HTML / PDF と同じ扱い。`id` や `modified` は共有相手に不要。"""
        from hitofude.editor.exporter import write_markdown

        written = write_markdown(tmp_path / "out.md", SOURCE).read_text(encoding="utf-8")
        assert "ABC123" not in written
        assert not written.startswith("---")

    def test_front_matterを残すこともできる(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import write_markdown

        target = write_markdown(tmp_path / "out.md", SOURCE, keep_front_matter=True)
        assert "ABC123" in target.read_text(encoding="utf-8")

    def test_改行はLFで書く(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import write_markdown

        target = write_markdown(tmp_path / "out.md", "一行目\r\n二行目\r\n")
        assert b"\r\n" not in target.read_bytes()

    def test_末尾に改行を付ける(self, qapp, tmp_path: Path) -> None:
        """行末に改行が無い .md は他のツールで扱いにくい。"""
        from hitofude.editor.exporter import write_markdown

        target = write_markdown(tmp_path / "out.md", "改行なし")
        assert target.read_text(encoding="utf-8").endswith("\n")

    def test_空でも壊れない(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import write_markdown

        assert write_markdown(tmp_path / "empty.md", "").is_file()

    def test_書き出しても元のノートは変わらない(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import write_markdown

        source = tmp_path / "note.md"
        source.write_text(SOURCE, encoding="utf-8")
        write_markdown(tmp_path / "out.md", source.read_text(encoding="utf-8"))
        assert source.read_text(encoding="utf-8") == SOURCE


class TestImages:
    """本文の画像は vault からの相対パスで書かれている（タスク A-2）。

    書き出し先から見て解決できないと、貼った画像が黙って抜け落ちる。
    """

    def _note_with_image(self, tmp_path: Path) -> tuple[Path, str]:
        from PySide6.QtCore import QBuffer, QByteArray
        from PySide6.QtGui import QColor, QImage

        attachments = tmp_path / "attachments"
        attachments.mkdir()
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        storage = QByteArray()
        buffer = QBuffer(storage)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        (attachments / "写真.png").write_bytes(bytes(storage))
        return tmp_path, "# 見出し\n\n![](attachments/写真.png)\n"

    def test_HTMLに画像が埋まる(self, qapp, tmp_path: Path) -> None:
        """「外部リソースを参照しない」を保つため data URI にする。"""
        base, text = self._note_with_image(tmp_path)
        target = write_html(tmp_path / "out.html", text, base_path=base)
        assert "data:image/png;base64," in target.read_text(encoding="utf-8")

    def test_HTMLがファイルを参照しない(self, qapp, tmp_path: Path) -> None:
        base, text = self._note_with_image(tmp_path)
        written = write_html(tmp_path / "out.html", text, base_path=base).read_text(
            encoding="utf-8"
        )
        assert "attachments/" not in written

    def test_画像が無くても書き出せる(self, qapp, tmp_path: Path) -> None:
        """壊れたリンクで書き出しごと失敗させない。"""
        target = write_html(
            tmp_path / "out.html", "![](attachments/居ない.png)\n", base_path=tmp_path
        )
        assert target.is_file()

    def test_vaultの外は読みに行かない(self, qapp, tmp_path: Path) -> None:
        """本文は手で編集できる。`../` で任意のファイルを埋め込ませない。"""
        secret = tmp_path.parent / "秘密.png"
        secret.write_bytes(b"\x89PNG himitsu")
        written = write_html(
            tmp_path / "out.html", "![](../秘密.png)\n", base_path=tmp_path
        ).read_text(encoding="utf-8")
        assert "base64" not in written

    def test_PDFに画像が入る(self, qapp, tmp_path: Path) -> None:
        base, text = self._note_with_image(tmp_path)
        without = write_pdf(tmp_path / "a.pdf", "# 見出し\n\n本文\n", base_path=base)
        with_image = write_pdf(tmp_path / "b.pdf", text, base_path=base)
        assert with_image.stat().st_size > without.stat().st_size

    def test_Markdownは相対パスのまま(self, qapp, tmp_path: Path) -> None:
        """R1: Markdown 書き出しは変換ではない。"""
        _, text = self._note_with_image(tmp_path)
        written = write_markdown(tmp_path / "out.md", text).read_text(encoding="utf-8")
        assert "![](attachments/写真.png)" in written

    def test_base_pathを渡さなくても書ける(self, qapp, tmp_path: Path) -> None:
        """既存の呼び出しを壊さない。"""
        assert write_html(tmp_path / "out.html", "# 見出し\n").is_file()


class TestImageSafety:
    """本文は手で編集できる。保管フォルダの外を書き出しに埋め込ませない。

    `image_cache` 側には同じ守りの試験があるのに、書き出し側だけ
    抜けていた（監査で判明）。守りが片側だけ検証されている状態を残さない。
    """

    def test_絶対パスは埋め込まない(self, qapp, tmp_path: Path) -> None:
        secret = tmp_path.parent / "秘密.png"
        secret.write_bytes(b"\x89PNG himitsu")
        written = write_html(
            tmp_path / "out.html", f"![]({secret})\n", base_path=tmp_path
        ).read_text(encoding="utf-8")
        assert "base64" not in written

    def test_file_スキームの絶対パスも埋め込まない(self, qapp, tmp_path: Path) -> None:
        secret = tmp_path.parent / "秘密2.png"
        secret.write_bytes(b"\x89PNG himitsu")
        written = write_html(
            tmp_path / "out.html", f"![](file://{secret})\n", base_path=tmp_path
        ).read_text(encoding="utf-8")
        assert "base64" not in written

    def test_httpは取りに行かない(self, qapp, tmp_path: Path) -> None:
        """書き出しのたびに通信しない。"""
        written = write_html(
            tmp_path / "out.html", "![](https://example.com/a.png)\n", base_path=tmp_path
        ).read_text(encoding="utf-8")
        assert "base64" not in written

    def test_読めない画像でも書き出せる(self, qapp, tmp_path: Path, monkeypatch) -> None:
        """権限が無いなどで読めなくても、書き出しごと失敗させない。"""
        target = tmp_path / "attachments"
        target.mkdir()
        (target / "a.png").write_bytes(b"\x89PNG")

        def deny(self, *args, **kwargs):
            raise OSError("読めない")

        monkeypatch.setattr(Path, "read_bytes", deny)
        assert write_html(
            tmp_path / "out.html", "![](attachments/a.png)\n", base_path=tmp_path
        ).is_file()

    def test_起点が無ければ埋め込まない(self, qapp, tmp_path: Path) -> None:
        written = write_html(tmp_path / "out.html", "![](a.png)\n").read_text(encoding="utf-8")
        assert "base64" not in written


class TestRendererSwap:
    """B-2: `setMarkdown()` から markdown-it-py へ移したことで通るようになったもの。

    変換そのものは `tests/core/test_html.py` が見る。ここは**書き出した
    ファイルまで届いているか**を見る。途中で落ちても気づけるようにする。
    """

    def test_コードフェンスの言語が書き出しに残る(self, qapp) -> None:
        """B-4（Mermaid）と色分けはこの class を見る。"""
        assert 'class="language-python"' in to_html("```python\nx = 1\n```\n")

    def test_チェックボックスが印になる(self, qapp) -> None:
        html = to_html("- [ ] やること\n- [x] 済み\n")
        assert "☐ やること" in html
        assert "☑ 済み" in html

    def test_表に罫線のスタイルが付く(self, qapp) -> None:
        """罫線が無い表は読めない。Qt でも効く書き方にしてある。"""
        html = to_html("| 左 | 右 |\n| --- | --- |\n| a | b |\n")
        assert "<table>" in html
        assert "border" in html

    def test_本文の生HTMLは実行できる形にしない(self, qapp) -> None:
        """書き出した HTML は他人に渡る。"""
        assert "<script>" not in to_html("<script>alert(1)</script>\n")

    def test_余計な属性で膨らまない(self, qapp) -> None:
        """`setMarkdown()` 経由は 1 行ごとに `style="..."` が付いていた。

        意味づけされた HTML なら後から手を入れられる。
        """
        html = to_html("# 見出し\n\n段落\n")
        assert "<h1>見出し</h1>" in html
        assert "-qt-block-indent" not in html

    def test_PDFも保管フォルダの外は読まない(self, qapp, tmp_path: Path) -> None:
        """**B-2 で得た安全側の変化。**

        以前の PDF は `setBaseUrl()` で相対パスをその場で解決していたので、
        `../` を書けば vault の外の画像も入っていた。HTML と同じ埋め込み経路に
        揃えたため、同じ判定（`core/paths.py`）が PDF にも効くようになった。
        """
        secret = tmp_path.parent / "秘密.png"
        secret.write_bytes(b"\x89PNG" + b"x" * 4000)
        outside = write_pdf(tmp_path / "a.pdf", "![](../秘密.png)\n", base_path=tmp_path)
        plain = write_pdf(tmp_path / "b.pdf", "\n", base_path=tmp_path)
        assert outside.stat().st_size < plain.stat().st_size + 2000


class TestMath:
    """数式（B-5 / ADR-0009）。"""

    def test_HTMLは組まれた式になる(self, qapp) -> None:
        assert "<math" in to_html("$E = mc^2$\n")

    def test_HTMLは外部を参照しない(self, qapp) -> None:
        """MathML なので JavaScript を同梱しない。"""
        html = to_html("$E = mc^2$\n")
        assert "<script" not in html
        assert "cdn" not in html.lower()

    def test_PDFは記法のまま出す(self, qapp, tmp_path: Path) -> None:
        """**Qt は MathML を解さない。** そのまま渡すと `E=mc2` になる（実測）。"""
        from hitofude.editor.exporter import _to_document
        from hitofude.theme import LIGHT

        document = _to_document("$E = mc^2$\n", theme=LIGHT, base_point_size=11.0, base_path=None)
        assert "$E = mc^2$" in document.toPlainText()

    def test_PDFで分数が潰れない(self, qapp) -> None:
        """`\\frac{a}{b}` が `ab` になっていた（実測）。"""
        from hitofude.editor.exporter import _to_document
        from hitofude.theme import LIGHT

        document = _to_document(
            "$$\n\\frac{a}{b}\n$$\n", theme=LIGHT, base_point_size=11.0, base_path=None
        )
        assert "\\frac{a}{b}" in document.toPlainText()


class TestMermaid:
    """Mermaid の図（B-4）。

    図を描くのはブラウザ側の JavaScript。**同梱する**ので、渡した相手が
    オフラインでも出る（`to_html` の「外部リソースを参照しない」を守る）。
    """

    DIAGRAM = "```mermaid\ngraph TD\n  A --> B\n```\n"

    def test_図があれば描画用のJSを埋める(self, qapp) -> None:
        html = to_html(self.DIAGRAM)
        assert "mermaid.initialize" in html

    def test_外部を参照しない(self, qapp) -> None:
        html = to_html(self.DIAGRAM)
        assert "<script src=" not in html
        assert "cdn." not in html

    def test_図が無ければ埋めない(self, qapp) -> None:
        """図の無いノートまで 3.4MB 太らせない。"""
        html = to_html("# 見出し\n\n```python\nx = 1\n```\n")
        assert "mermaid.initialize" not in html

    def test_図の無い書き出しは小さいまま(self, qapp) -> None:
        assert len(to_html("# 見出し\n")) < 100_000

    def test_テーマに合わせる(self, qapp) -> None:
        from hitofude.theme import DARK, LIGHT

        assert to_html(self.DIAGRAM, theme=DARK) != to_html(self.DIAGRAM, theme=LIGHT)

    def test_PDFにはJSを埋めない(self, qapp) -> None:
        """`QPrinter` では JavaScript が動かない。埋めても無駄に太るだけ。"""
        from hitofude.editor.exporter import _to_document
        from hitofude.theme import LIGHT

        document = _to_document(self.DIAGRAM, theme=LIGHT, base_point_size=11.0, base_path=None)
        assert "mermaid.initialize" not in document.toPlainText()

    def test_PDFには図の元が残る(self, qapp) -> None:
        """図にできない代わりに、書いたものは失わない。"""
        from hitofude.editor.exporter import _to_document
        from hitofude.theme import LIGHT

        document = _to_document(self.DIAGRAM, theme=LIGHT, base_point_size=11.0, base_path=None)
        assert "graph TD" in document.toPlainText()

    def test_図に背景を敷かない(self, qapp) -> None:
        """`<pre>` なのでコードの背景を引き継ぐ。絵に灰色の板が見える。"""
        assert ".mermaid { background: none" in to_html(self.DIAGRAM)

    def test_ライセンス表記も一緒に埋める(self, qapp) -> None:
        """**MIT の条件**。複製物には著作権表示と許諾表示を含める。

        書き出した HTML は人に渡るので、それ自体が mermaid の複製物になる。
        `mermaid.min.js` には mermaid 自身の表記が入っていない（実測）ので、
        こちらで添える。
        """
        html = to_html(self.DIAGRAM)
        assert "Knut Sveidqvist" in html
        assert "MIT License" in html

    def test_出どころとバージョンも書く(self, qapp) -> None:
        """あとから追跡できるように。"""
        html = to_html(self.DIAGRAM)
        assert "mermaid" in html
        assert "github.com/mermaid-js/mermaid" in html

    def test_図が無ければ表記も要らない(self, qapp) -> None:
        assert "Knut Sveidqvist" not in to_html("# 見出し\n")


class TestPreviewFile:
    """ブラウザで確認するための一時ファイル（E-2）。

    書き出さずに見たいだけなので、保管フォルダは汚さない。同じ場所へ
    上書きするので、見るたびにファイルが増えることもない。
    """

    def test_書き出せる(self, qapp) -> None:
        from hitofude.editor.exporter import write_preview

        target = write_preview("# 見出し\n")
        assert target.is_file()

    def test_中身は書き出しと同じ(self, qapp) -> None:
        from hitofude.editor.exporter import write_preview

        target = write_preview("# 見出し\n")
        assert "<h1>見出し</h1>" in target.read_text(encoding="utf-8")

    def test_保管フォルダを汚さない(self, qapp, tmp_path: Path) -> None:
        from hitofude.editor.exporter import write_preview

        target = write_preview("# 見出し\n", base_path=tmp_path)
        assert tmp_path not in target.parents

    def test_同じ場所へ上書きする(self, qapp) -> None:
        """見るたびにファイルが増えない。"""
        from hitofude.editor.exporter import write_preview

        assert write_preview("# 一\n") == write_preview("# 二\n")

    def test_図も入る(self, qapp) -> None:
        from hitofude.editor.exporter import write_preview

        target = write_preview("```mermaid\ngraph TD\n  A --> B\n```\n")
        assert "mermaid.initialize" in target.read_text(encoding="utf-8")


class TestClipboardHtml:
    """HTML をクリップボードへ（E-3）。"""

    def test_書式付きで入る(self, qapp) -> None:
        from PySide6.QtWidgets import QApplication

        from hitofude.editor.exporter import copy_html

        copy_html("# 見出し\n\n**強調**\n")
        data = QApplication.clipboard().mimeData()
        assert data.hasHtml()
        assert "<strong>強調</strong>" in data.html()

    def test_素の文字も入れる(self, qapp) -> None:
        """書式を受け取れない相手（素のテキスト欄）にも貼れるように。"""
        from PySide6.QtWidgets import QApplication

        from hitofude.editor.exporter import copy_html

        copy_html("# 見出し\n\n**強調**\n")
        assert "強調" in QApplication.clipboard().mimeData().text()

    def test_記号は素の文字から外す(self, qapp) -> None:
        from PySide6.QtWidgets import QApplication

        from hitofude.editor.exporter import copy_html

        copy_html("**強調**\n")
        assert "**" not in QApplication.clipboard().mimeData().text()

    def test_画像は埋め込む(self, qapp, tmp_path: Path) -> None:
        """貼り付け先で絵が出ないと意味がない。"""
        from PySide6.QtGui import QImage

        from hitofude.editor.exporter import copy_html

        (tmp_path / "attachments").mkdir()
        image = QImage(4, 4, QImage.Format.Format_RGB32)
        image.save(str(tmp_path / "attachments" / "a.png"))
        copy_html("![](attachments/a.png)\n", base_path=tmp_path)

        from PySide6.QtWidgets import QApplication

        assert "data:image/png;base64," in QApplication.clipboard().mimeData().html()


class TestDarkCode:
    """暗いテーマでの書き出しはコードの色分けも暗い配色にする（B-6）。

    `_rendered_body` が `dark` を受け取るだけで `render` に渡しておらず、
    docstring の警告どおり「黒地に黒い字」になりうる状態だった
    （コードレビュー 2026-08-25）。
    """

    CODE = "# 見本\n\n```python\ndef f():\n    return 1\n```\n"

    def test_HTMLの色分けがテーマで変わる(self, qapp) -> None:
        from hitofude.theme import DARK, LIGHT

        light = to_html(self.CODE, theme=LIGHT)
        dark = to_html(self.CODE, theme=DARK)
        assert light != dark

    def test_暗い配色の色が入る(self, qapp) -> None:
        from hitofude.theme import DARK

        # github-dark の予約語の色。明るい配色（default）には出ない
        assert "#FF7B72" in to_html(self.CODE, theme=DARK).upper()
