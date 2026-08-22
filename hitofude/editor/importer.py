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
import tempfile
from pathlib import Path

from hitofude.core import imported
from hitofude.editor import pptx_import

logger = logging.getLogger(__name__)

PDF_SUFFIX = ".pdf"
PPTX_SUFFIX = ".pptx"

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".heic", ".tiff", ".tif"})
"""絵から文字を読む（ADR-0027）。**読み手が無ければ読み込めない。**"""

# ファイル選択に出す絞り込み
FILE_FILTER = "読み込める資料 (*.pdf *.pptx *.png *.jpg *.jpeg *.heic *.tiff)"

# 絵にするときの横幅。**大きすぎると遅く、小さすぎると読めない。**
# 実測では A4 相当を 1,600px で読めている
PAGE_WIDTH = 1600


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


def pdf_page_images(path: Path, directory: Path) -> list[Path]:
    """PDF の各ページを絵にする（ADR-0027）。読めなければ空。

    文字が入っていない PDF（紙を取り込んだもの）を読むのに要る。
    **一時の置き場は呼ぶ側が渡す**（後片づけをそちらに任せる）。
    """
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    if document.load(str(path)) is not QPdfDocument.Error.None_:
        logger.warning("PDF を読めなかった: %s", path)
        return []

    found: list[Path] = []
    for number in range(document.pageCount()):
        size = document.pagePointSize(number)
        height = int(PAGE_WIDTH * size.height() / size.width()) if size.width() else PAGE_WIDTH
        image = document.render(number, QSize(PAGE_WIDTH, height))
        target = directory / f"page-{number + 1}.png"
        if image.save(str(target)):
            found.append(target)
    document.close()
    return found


def to_markdown(path: Path, *, save_image=None, ocr=None) -> str:
    """資料 1 つを Markdown にする。読めなければ空。

    **題名はファイル名**（`講演資料.pdf` → `# 講演資料`）。中身から題を
    推し量る手もあるが、ファイル名は人が付けたもので当てにできる。

    `save_image` は PowerPoint の画像を保管フォルダへ置く関数
    （`MainWindow.save_attachment`）。PDF では使わない（画像は取らない）。
    """
    suffix = path.suffix.lower()
    if suffix == PPTX_SUFFIX:
        # PowerPoint は構造を持っているので、ページの文字に均さず直に組む
        return pptx_import.to_markdown(path, save_image=save_image)
    if suffix in IMAGE_SUFFIXES:
        return _from_images([path], title=path.stem, reader=ocr)
    if suffix == PDF_SUFFIX:
        pages = pdf_pages(path)
    else:
        logger.warning("知らない拡張子: %s", path)
        return ""

    # **本文が無ければ空を返す。** ページはあっても文字が 1 つも無いことが
    # ある（画像を PDF にしたもの。ユーザー報告）。題名だけ返すと、
    # 呼び出し側が「読めた」と誤解して**中身の無いノート**を作ってしまう
    if not any(page.strip() for page in pages):
        # **絵から読む**（ADR-0027）。紙を取り込んだ PDF はここへ来る。
        # 文字が取れるなら回さない（速くて正確なほうを黙って捨てない）
        logger.info("文字が無いので読み取りに回す: %s", path)
        return _scanned_pdf(path, reader=ocr)

    return imported.to_markdown(pages, title=path.stem)


def _scanned_pdf(path: Path, *, reader) -> str:
    """文字の入っていない PDF を、ページの絵から読む（ADR-0027）。"""
    if reader is None or not reader.available():
        logger.warning("読み取りができないので諦める: %s", path)
        return ""
    with tempfile.TemporaryDirectory() as workspace:
        images = pdf_page_images(path, Path(workspace))
        return _from_images(images, title=path.stem, reader=reader)


def _from_images(images: list[Path], *, title: str, reader) -> str:
    """絵の並びを 1 つの Markdown にする。**読めなければ空。**

    題名だけのノートを作らない（読めたと誤解させる）。
    """
    if reader is None or not reader.available() or not images:
        return ""
    pages: list[str] = []
    for image in images:
        try:
            pages.append(reader.read(image))
        except Exception as error:  # 読み手の事情（道具が無い・モデルが違う）
            logger.warning("読み取れなかった: %s", error)
            return ""
    if not any(page.strip() for page in pages):
        return ""
    return imported.to_markdown(pages, title=title)
