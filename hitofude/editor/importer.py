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
from hitofude.core.imported import ImagePicker
from hitofude.editor import pptx_import

logger = logging.getLogger(__name__)

PDF_SUFFIX = ".pdf"
PPTX_SUFFIX = ".pptx"

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".heic", ".tiff", ".tif"})
"""絵から文字を読む（ADR-0027）。**読み手が無ければ読み込めない。**"""

# ファイル選択に出す絞り込み。**IMAGE_SUFFIXES から組み立てる。**
# 手書きの一覧だと、対応を増やしたときにここだけ置いていかれる
# （`.tif` が実際に漏れていた。レビュー 2026-08-25）
FILE_FILTER = f"読み込める資料 (*.pdf *.pptx {' '.join(f'*{s}' for s in sorted(IMAGE_SUFFIXES))})"

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


def pdf_page_images(
    path: Path, directory: Path, pages: list[int] | None = None
) -> list[tuple[int, Path]]:
    """PDF のページを絵にする（ADR-0027）。読めなければ空。

    文字が入っていない PDF（紙を取り込んだもの）を読むのに要る。
    **一時の置き場は呼ぶ側が渡す**（後片づけをそちらに任せる）。

    `pages`（0 始まり）を渡すと**そのページだけ**。文字のあるページまで
    絵にすると、要らない読み取りで待たされる。
    """
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    if document.load(str(path)) is not QPdfDocument.Error.None_:
        logger.warning("PDF を読めなかった: %s", path)
        return []

    found: list[tuple[int, Path]] = []
    wanted = range(document.pageCount()) if pages is None else pages
    for number in wanted:
        size = document.pagePointSize(number)
        height = int(PAGE_WIDTH * size.height() / size.width()) if size.width() else PAGE_WIDTH
        image = document.render(number, QSize(PAGE_WIDTH, height))
        target = directory / f"page-{number + 1}.png"
        if image.save(str(target)):
            found.append((number, target))
    document.close()
    return found


def pdf_images(path: Path) -> dict[int, list[tuple[str, bytes, int, int]]]:
    """ページごとの埋め込み画像（ユーザー要望 2026-08-23）。読めなければ空。

    **QtPdf には取り出す口が無い**（`render` しかない）ので `pypdf` を使う。
    位置は分からない — pypdf はページ単位でしか教えないので、本文の
    どこに挟まっていたかは復元できない。
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as error:  # 壊れた PDF・暗号化
        logger.warning("PDF の画像を読めなかった: %s", error)
        return {}

    found: dict[int, list[tuple[str, bytes, int, int]]] = {}
    for number, page in enumerate(reader.pages):
        try:
            images = [
                (image.name, image.data, image.image.width, image.image.height)
                for image in page.images
            ]
        except Exception as error:  # 1 ページの故障で全部を諦めない
            logger.warning("%d ページ目の画像を読めなかった: %s", number + 1, error)
            continue
        if images:
            found[number] = images
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
    # **ページごとに切り分ける**（ユーザー指摘 2026-08-23）。文書ごとに
    # 見ていたので、1 ページでも文字があると絵のページが丸ごと落ちていた
    blanks = _blank_pages(pages)
    pages = _fill_blank_pages(path, pages, blanks, reader=ocr)
    if not any(page.strip() for page in pages):
        logger.warning("文字を取り出せなかった: %s", path)
        return ""

    # **読み取ったページの絵は貼らない。** そのページの絵はページそのもので、
    # 読み取った文字と二重になる（実測: スキャン 1 ページで 108KB が付いた）
    pages = _attach_images(path, pages, save_image=save_image, skip=blanks)
    return imported.to_markdown(pages, title=path.stem)


MIN_PAGE_CHARS = 20
"""このページには文字が無い、と見なす境目（ADR-0027）。

**0 にしない。** 紙を取り込んだページからは、ゴミのような数文字が
取れることがある（ページ番号や罫線の誤認）。そこで「文字がある」と
判断すると、そのページは読めないまま終わる。

**行き過ぎても害は小さい。** 短い扉ページを読み取りに回しても、0.5 秒
かけて同じ言葉が返るだけ。
"""


def _blank_pages(pages: list[str]) -> set[int]:
    """文字の取れなかったページ（0 始まり）。"""
    return {number for number, page in enumerate(pages) if len(page.strip()) < MIN_PAGE_CHARS}


def _fill_blank_pages(path: Path, pages: list[str], blank: set[int], *, reader) -> list[str]:
    """文字の取れなかったページだけ、絵から読んで埋める（ADR-0027）。

    **読めたページは捨てない。** 読み取りが使えなくても、文字のある
    ページはそのまま残す（読めないページのせいで全部を失わない）。
    """
    blanks = sorted(blank)
    if not blanks or reader is None or not reader.available():
        if blanks:
            logger.info("読み取りが使えないので %d ページは空のまま: %s", len(blanks), path)
        return pages

    logger.info("文字の無い %d ページを読み取りに回す: %s", len(blanks), path)
    filled = list(pages)
    with tempfile.TemporaryDirectory() as workspace:
        # **番号は絵と一緒に受け取る。** 書き出しに失敗したページがあると
        # 数が合わず、`zip` では 1 つずつずれて「5 ページ目の文字が
        # 3 ページ目に入る」になる（読み取った中身が別のページのものに
        # なるので、見ただけでは気づけない）
        for number, image in pdf_page_images(path, Path(workspace), blanks):
            try:
                found = reader.read(image)
            except Exception as error:  # 読み手の事情（道具が無い・モデルが違う）
                logger.warning("読み取れなかった（%d ページ目）: %s", number + 1, error)
                continue
            # **長いほうを残す。** 短くても本物の文字が入っているページを、
            # 読み取りの結果で上書きして失わない（読み取りが外すこともある）
            if len(found.strip()) > len(filled[number].strip()):
                filled[number] = found
    return filled


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


def _attach_images(path: Path, pages: list[str], *, save_image, skip: set[int]) -> list[str]:
    """ページの絵を保管フォルダへ置き、本文の**後ろに**足す。

    **位置は復元できない**ので、そのページの本文の後ろにまとめる。
    `save_image` が無ければ何もしない（書き出しの検査など、置き場が無い
    呼び方がある）。
    """
    if save_image is None:
        return pages

    found = pdf_images(path)
    if not found:
        return pages

    picker = ImagePicker()
    filled = list(pages)
    for number in sorted(found):
        if number in skip:
            continue
        for name, data, width, height in found[number]:
            if not picker.accepts(data, width=width, height=height):
                continue
            markdown = save_image(data, Path(name).suffix or ".png")
            if markdown:  # **壊れたリンクを書かない**（save_attachment と同じ）
                filled[number] = f"{filled[number]}\n\n{markdown}"
    return filled
