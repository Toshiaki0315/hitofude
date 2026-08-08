"""HTML / PDF へのエクスポート（spec §9 Phase 6, R2）。

**`QTextDocument.setMarkdown()` を使ってよいのはここだけ。**

編集モデルに使ってはいけない理由（§3.3）は往復変換でソースが壊れることだが、
エクスポートは一方通行で、変換結果をファイルへ書き戻さない。壊れようがない。
逆に言えば、**この結果を編集中の文書へ戻してはいけない**。

`tests/test_architecture.py` はこのファイルだけを例外として許可している。
"""

from pathlib import Path

from PySide6.QtGui import QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from hitofude.core import frontmatter
from hitofude.theme import LIGHT, ThemeColors

PDF_MARGIN_MM = 18.0


def to_document(text: str, *, theme: ThemeColors = LIGHT, base_point_size: float = 15.0):
    """Markdown を描画済みの `QTextDocument` にする。

    front matter は本文ではないので落とす。`id` や `modified` が
    書き出した PDF の先頭に出ても意味がない。
    """
    document = QTextDocument()
    document.setDefaultStyleSheet(_stylesheet(theme))
    document.setMarkdown(frontmatter.split(text).body)  # ← R2 の唯一の例外
    document.setDefaultFont(_font(base_point_size))
    return document


def to_html(text: str, *, title: str = "", theme: ThemeColors = LIGHT) -> str:
    """完結した HTML 文字列にする。外部リソースを参照しない。"""
    body = to_document(text, theme=theme).toHtml()
    heading = f"<title>{_escape(title)}</title>" if title else ""
    return (
        "<!doctype html>\n"
        f'<html lang="ja"><head><meta charset="utf-8">{heading}'
        f"<style>{_stylesheet(theme)}</style></head>\n"
        f"<body>{body}</body></html>\n"
    )


def write_html(path: Path, text: str, *, title: str = "", theme: ThemeColors = LIGHT) -> Path:
    path.write_text(to_html(text, title=title, theme=theme), encoding="utf-8", newline="\n")
    return path


def write_pdf(
    path: Path, text: str, *, theme: ThemeColors = LIGHT, base_point_size: float = 15.0
) -> Path:
    """`QPrinter` で PDF を書き出す（spec §9 Phase 6）。"""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageMargins(_margins(), printer.pageLayout().units())

    document = to_document(text, theme=theme, base_point_size=base_point_size)
    document.print_(printer)
    return path


def _margins():
    from PySide6.QtCore import QMarginsF

    return QMarginsF(PDF_MARGIN_MM, PDF_MARGIN_MM, PDF_MARGIN_MM, PDF_MARGIN_MM)


def _font(point_size: float):
    from PySide6.QtGui import QFont

    font = QFont("Hiragino Sans")
    font.setPointSizeF(point_size)
    return font


def _stylesheet(theme: ThemeColors) -> str:
    return (
        f"body {{ color: {theme.foreground}; background: {theme.background}; "
        "line-height: 1.7; }"
        f"code, pre {{ background: {theme.code_background}; color: {theme.code_foreground}; }}"
        f"blockquote {{ color: {theme.quote_foreground}; "
        f"border-left: 3px solid {theme.quote_bar}; padding-left: 12px; }}"
        f"a {{ color: {theme.accent}; }}"
    )


def _escape(text: str) -> str:
    from html import escape

    return escape(text)
