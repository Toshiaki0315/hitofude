"""外の形式から取り込む（F 群）。

**ざっくり読んで手で直す**前提。元の見た目は再現しない（TASKS.md の F 群）。

PDF は **PySide6 同梱の QtPdf** で読む。依存が増えないのが決め手で、
py2app の除外にも入っていない（`docs/licenses.md`）。

R3 のとおり `core/` は PySide6 に触れないので、読み取りはここに置く。
**この層は「読む」だけ**で、文字を Markdown に整えるのは
`core/imported.py`（F-1）の仕事。

**読めないことは壊れることではない。** 中身が PDF でなくても、暗号化されて
いても、空を返して呼び出し側に知らせる。取り込みに失敗してアプリが落ちる
のがいちばん困る。
"""

import logging
from pathlib import Path

from hitofude.core import imported

logger = logging.getLogger(__name__)

PDF_SUFFIX = ".pdf"
SUPPORTED_SUFFIXES = (PDF_SUFFIX,)
# ファイル選択に出す絞り込み
FILE_FILTER = "読み込める資料 (*.pdf)"


def pdf_pages(path: Path) -> list[str]:
    """PDF のページごとの文字。読めなければ空。

    `getAllText()` は組版された順で返す。**位置は取れない**ので、段落や
    箇条書きの区別は文字の並びから推し量るしかない（`core/imported.py`）。
    """
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    status = document.load(str(path))
    if status is not QPdfDocument.Error.None_:
        logger.warning("PDF を読めなかった（%s）: %s", status, path)
        return []

    pages = [document.getAllText(number).text() for number in range(document.pageCount())]
    document.close()
    return pages


def to_markdown(path: Path) -> str:
    """資料 1 つを Markdown にする。読めなければ空。

    **題名はファイル名**（`講演資料.pdf` → `# 講演資料`）。中身から題を
    推し量る手もあるが、ファイル名は人が付けたもので当てにできる。
    """
    suffix = path.suffix.lower()
    if suffix == PDF_SUFFIX:
        pages = pdf_pages(path)
    else:
        logger.warning("知らない拡張子: %s", path)
        return ""

    # **本文が無ければ空を返す。** ページはあっても文字が 1 つも無いことが
    # ある（画像を PDF にしたもの。ユーザー報告）。題名だけ返すと、
    # 呼び出し側が「読めた」と誤解して**中身の無いノート**を作ってしまう
    if not any(page.strip() for page in pages):
        logger.warning("文字を取り出せなかった（画像だけの資料か）: %s", path)
        return ""

    return imported.to_markdown(pages, title=path.stem)
