"""HTML / PDF へのエクスポート（spec §9 Phase 6 / ADR-0007）。

**`QTextDocument.setMarkdown()` は使わない。** 変換は `core/html.py` が
markdown-it-py で行い、ここはその HTML を「ページに組む」「画像を埋める」
「PDF に流す」だけを受け持つ。

以前はここが R2 の唯一の例外だった。今は**アプリのどこからも
`setMarkdown()` を呼ばない**（`tests/test_architecture.py` が見ている）。
理由は R2 の趣旨（往復変換の禁止）ではなく、あちらが記法を落とすため。
実測は ADR-0007。
"""

import base64
import logging
import mimetypes
import re
from pathlib import Path

from PySide6.QtGui import QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from hitofude.core import frontmatter
from hitofude.core import html as markdown_html
from hitofude.core.paths import resolve_reference
from hitofude.theme import LIGHT, ThemeColors

PDF_MARGIN_MM = 18.0

logger = logging.getLogger(__name__)

# HTML の `<img src="...">`。書き出し先から解決できない相対パスを埋め込みに置き換える
_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)


def _as_data_uri(path: Path) -> str | None:
    """画像を `data:` URI にする。読めなければ None。"""
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        logger.warning("画像を読めなかった: %s", path)
        return None
    return f"data:{kind};base64,{payload}"


def _embed_images(body: str, base_path: Path | None) -> str:
    """`<img src>` を `data:` URI へ置き換える。

    `to_html()` は「外部リソースを参照しない」ことを約束している。
    相対パスのまま出すと、書き出した HTML を移した瞬間に画像が消える。
    """

    def swap(match: re.Match[str]) -> str:
        resolved = resolve_reference(base_path, match.group(2))
        if resolved is None:
            return match.group(0)
        uri = _as_data_uri(resolved)
        return match.group(0) if uri is None else f"{match.group(1)}{uri}{match.group(3)}"

    return _IMG_SRC_RE.sub(swap, body)


def _rendered_body(
    text: str,
    base_path: Path | None,
    *,
    math_as_source: bool = False,
    dark: bool = False,
) -> str:
    """本文の HTML。画像は `data:` URI に置き換える。

    **HTML も PDF もここを通す。** 経路を分けると、片方だけ画像が出る、
    片方だけ vault の外を読む、といった食い違いが起きる。埋め込みに揃えたので
    PDF にも「保管フォルダの外は読まない」が効くようになった。

    唯一違うのが数式（`math_as_source`）。Qt のリッチテキストは MathML を
    解さず、**黙って間違った式**を出す（ADR-0009）。ここだけは分ける。

    `dark` はコードの色分けを暗い配色にする（B-6）。テーマの明暗に合わせないと、
    黒地に黒い字になる。
    """
    return _embed_images(markdown_html.render(text, math_as_source=math_as_source), base_path)


def _to_document(text: str, *, theme: ThemeColors, base_point_size: float, base_path: Path | None):
    """描画済みの `QTextDocument`（PDF 用）。

    Qt のリッチテキストは HTML/CSS の一部しか解さない。表の罫線と余白、
    等幅、打ち消しは効く（実測）。`border-collapse` や `max-width` は
    無視されるが、無視されるだけで壊れない。
    """
    document = QTextDocument()
    document.setDefaultStyleSheet(_stylesheet(theme))
    # 数式は LaTeX のまま。MathML は Qt が解さない（ADR-0009）
    document.setHtml(_rendered_body(text, base_path, math_as_source=True, dark=theme.is_dark))
    document.setDefaultFont(_font(base_point_size))
    return document


def to_html(
    text: str, *, title: str = "", theme: ThemeColors = LIGHT, base_path: Path | None = None
) -> str:
    """完結した HTML 文字列にする。外部リソースを参照しない。"""
    body = _rendered_body(text, base_path, dark=theme.is_dark)
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

    document = _to_document(text, theme=theme, base_point_size=base_point_size, base_path=base_path)
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
    """HTML ページと PDF の両方に使う 1 枚。

    **Qt のリッチテキストは CSS の一部しか解さない。** 効くのは色・背景・
    余白・罫線・フォント（実測）。`max-width` や `border-collapse` や
    `border-radius` は無視されるが、**無視されるだけで壊れない**ので、
    ブラウザ向けと分けずに 1 枚で通す。2 枚に分けると片方だけ直す事故が起きる。
    """
    return (
        f"body {{ color: {theme.foreground}; background: {theme.background}; "
        "font-family: 'Hiragino Sans', sans-serif; line-height: 1.7; "
        "max-width: 42em; margin: 0 auto; padding: 24px; }"
        "h1, h2, h3, h4, h5, h6 { line-height: 1.4; }"
        f"code, pre {{ background: {theme.code_background}; color: {theme.code_foreground}; "
        "font-family: 'Menlo', monospace; }"
        "code { padding: 1px 4px; border-radius: 3px; }"
        "pre { padding: 10px 12px; border-radius: 5px; }"
        "pre code { padding: 0; background: none; }"
        f"blockquote {{ color: {theme.quote_foreground}; "
        f"border-left: 3px solid {theme.quote_bar}; padding-left: 12px; margin-left: 0; }}"
        f"a {{ color: {theme.accent}; }}"
        "table { border-collapse: collapse; }"
        # 罫線と余白は **Qt でも効く**。表が線なしで出ると読めない
        f"th, td {{ border: 1px solid {theme.rule}; padding: 5px 9px; }}"
        f"th {{ background: {theme.code_background}; }}"
        "img { max-width: 100%; }"
        f"hr {{ border: none; border-top: 1px solid {theme.rule}; }}"
        # ---- Qiita 記法（B-3）
        # 囲みは**左の縦線で表す**。全面の背景は Qt では箱にならず
        # （`background` はブロックを塗らない）、色だけ変わって理由が読めない
        f".note {{ border-left: 4px solid {theme.rule}; padding: 2px 12px; margin: 12px 0; }}"
        f".note-info {{ border-left-color: {theme.note_info}; }}"
        f".note-warn {{ border-left-color: {theme.note_warn}; }}"
        f".note-alert {{ border-left-color: {theme.note_alert}; }}"
        # 綴り違い（`:::note warm`）。`.note` の灰色のまま出す。**info の青に
        # しない**（間違えたことに気づく手掛かりが消える。ユーザー報告）
        f".note-unknown {{ border-left-color: {theme.muted_foreground}; }}"
        f".code-name {{ color: {theme.muted_foreground}; font-size: 0.85em; "
        "font-family: 'Menlo', monospace; padding: 2px 4px; }"
        # 区切り線は脚注プラグインが `<hr class="footnotes-sep">` を出すので引かない
        f".footnotes {{ color: {theme.muted_foreground}; font-size: 0.9em; }}"
    )


def _escape(text: str) -> str:
    # 標準ライブラリの `html`。`core.html` は `markdown_html` として import して
    # あるので衝突しないが、紛らわしいので取り違えないこと
    from html import escape

    return escape(text)
