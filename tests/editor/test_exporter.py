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
