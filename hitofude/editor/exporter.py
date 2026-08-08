"""HTML / PDF へのエクスポート（spec §9 Phase 6, R2）。

**`QTextDocument.setMarkdown()` を使ってよいのはここだけ。**

編集モデルに使ってはいけない理由（§3.3）は往復変換でソースが壊れることだが、
エクスポートは一方通行で、変換結果をファイルへ書き戻さない。壊れようがない。
逆に言えば、**この結果を編集中の文書へ戻してはいけない**。

`tests/test_architecture.py` はこのファイルだけを例外として許可している。
"""

import base64
import logging
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from hitofude.core import frontmatter
from hitofude.theme import LIGHT, ThemeColors

PDF_MARGIN_MM = 18.0

logger = logging.getLogger(__name__)

# HTML の `<img src="...">`。書き出し先から解決できない相対パスを埋め込みに置き換える
_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)
# 代替テキストが空の画像。`setMarkdown()` は `<img>` ごと落とす（実測）
_EMPTY_ALT_RE = re.compile(r"!\[\]\(")


def _fill_empty_alt(body: str) -> str:
    """`![](...)` の代替テキストを空白 1 つで埋める。

    **`setMarkdown()` は代替テキストが空の画像を `<img>` ごと落とす**（実測）。
    貼り付けた画像は `![](attachments/...)` の形なので、そのままでは
    書き出した PDF / HTML から画像だけ黙って消える。

    書き換えるのは**書き出す文字列だけ**で、ソースには戻さない（R1・R2）。
    コードブロックの中の `![](...)` も一緒に変わるが、そこまで見分ける価値は
    無いと判断した。失うのは表示上の空白 1 つで、消えるのは画像そのもの。
    """
    return _EMPTY_ALT_RE.sub("![ ](", body)


def _resolve(base_path: Path | None, source: str) -> Path | None:
    """本文の画像パスを実ファイルへ解決する。**vault の外は返さない。**

    本文は手で編集できるので、`../` を書けば任意のファイルを指せる。
    書き出しに埋め込むということは外へ持ち出すことなので、
    保管フォルダの外は読みに行かない。
    """
    if base_path is None or source.startswith(("http:", "https:", "data:")):
        return None

    candidate = Path(unquote(source.removeprefix("file://")))
    if candidate.is_absolute():
        return None

    base = base_path.resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base) or not resolved.is_file():
        return None
    return resolved


def _as_data_uri(path: Path) -> str | None:
    """画像を `data:` URI にする。読めなければ None。"""
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        logger.warning("画像を読めなかった: %s", path)
        return None
    return f"data:{kind};base64,{payload}"


def _embed_images(html: str, base_path: Path | None) -> str:
    """`<img src>` を `data:` URI へ置き換える。

    `to_html()` は「外部リソースを参照しない」ことを約束している。
    相対パスのまま出すと、書き出した HTML を移した瞬間に画像が消える。
    """

    def swap(match: re.Match[str]) -> str:
        resolved = _resolve(base_path, match.group(2))
        if resolved is None:
            return match.group(0)
        uri = _as_data_uri(resolved)
        return match.group(0) if uri is None else f"{match.group(1)}{uri}{match.group(3)}"

    return _IMG_SRC_RE.sub(swap, html)


def to_document(
    text: str,
    *,
    theme: ThemeColors = LIGHT,
    base_point_size: float = 15.0,
    base_path: Path | None = None,
):
    """Markdown を描画済みの `QTextDocument` にする。

    front matter は本文ではないので落とす。`id` や `modified` が
    書き出した PDF の先頭に出ても意味がない。

    `base_path` を渡すと、本文の相対パスの画像を解決できるようになる
    （貼り付けた画像は vault からの相対パスで書かれている）。
    """
    document = QTextDocument()
    document.setDefaultStyleSheet(_stylesheet(theme))
    if base_path is not None:
        # 末尾の `/` が要る。無いと最後の要素がファイル名として捨てられる
        document.setBaseUrl(QUrl.fromLocalFile(f"{base_path}/"))
    document.setMarkdown(_fill_empty_alt(frontmatter.split(text).body))  # ← R2 の唯一の例外
    document.setDefaultFont(_font(base_point_size))
    return document


def to_html(
    text: str, *, title: str = "", theme: ThemeColors = LIGHT, base_path: Path | None = None
) -> str:
    """完結した HTML 文字列にする。外部リソースを参照しない。"""
    body = _embed_images(to_document(text, theme=theme, base_path=base_path).toHtml(), base_path)
    heading = f"<title>{_escape(title)}</title>" if title else ""
    return (
        "<!doctype html>\n"
        f'<html lang="ja"><head><meta charset="utf-8">{heading}'
        f"<style>{_stylesheet(theme)}</style></head>\n"
        f"<body>{body}</body></html>\n"
    )


def write_html(
    path: Path,
    text: str,
    *,
    title: str = "",
    theme: ThemeColors = LIGHT,
    base_path: Path | None = None,
) -> Path:
    path.write_text(
        to_html(text, title=title, theme=theme, base_path=base_path),
        encoding="utf-8",
        newline="\n",
    )
    return path


def write_markdown(path: Path, text: str, *, keep_front_matter: bool = False) -> Path:
    """Markdown のまま書き出す。

    HTML / PDF と違い**変換を挟まない**。マーカーはソースのまま出る。
    Markdown は変換先ではなく元の形式なので、ここで手を加える理由がない（R1）。

    front matter は既定で落とす。`id` や `modified` はこのアプリの管理情報で、
    共有相手には意味がない。HTML / PDF と同じ扱い。vault のファイルそのものが
    欲しいときは Finder でコピーすればよい。
    """
    body = text if keep_front_matter else frontmatter.split(text).body
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        # 行末に改行が無い `.md` は他のツールで扱いにくい
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8", newline="\n")
    return path


def write_pdf(
    path: Path,
    text: str,
    *,
    theme: ThemeColors = LIGHT,
    base_point_size: float = 15.0,
    base_path: Path | None = None,
) -> Path:
    """`QPrinter` で PDF を書き出す（spec §9 Phase 6）。"""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageMargins(_margins(), printer.pageLayout().units())

    document = to_document(text, theme=theme, base_point_size=base_point_size, base_path=base_path)
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
