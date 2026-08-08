"""貼り付け元から添付を取り出す（タスク A-2）。

**エディタの状態を要らない変換だけを置く。** どこへ保存するかは
`storage/vault.py`、本文へ挿すのは `editor/editor_widget.py` の仕事。
"""

import logging
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)

# 落とされたファイルを画像として扱う拡張子。ここに無いものは素通しする
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".heic"})
CLIPBOARD_IMAGE_SUFFIX = ".png"


def looks_like_attachment(source) -> bool:
    """添付として扱うつもりの貼り付け元か。**読めるかどうかは見ない。**

    読めなかったときに素通しすると、`file:///...png` という文字列が
    本文へ落ちる。扱うつもりだったなら、失敗しても何も入れない。
    """
    if source.hasImage():
        return True
    return any(_image_path(url) is not None for url in _urls(source))


def extract(source) -> list[tuple[bytes, str]]:
    """取り出せた添付を `(中身, 拡張子)` で返す。読めなければ落とす。"""
    if source.hasImage():
        data = encode_image(source.imageData())
        return [(data, CLIPBOARD_IMAGE_SUFFIX)] if data else []

    found: list[tuple[bytes, str]] = []
    for url in _urls(source):
        path = _image_path(url)
        if path is None:
            continue
        try:
            found.append((path.read_bytes(), path.suffix))
        except OSError:
            logger.warning("落とされたファイルを読めなかった: %s", path)
    return found


def encode_image(image) -> bytes:
    """クリップボードの画像を PNG にする。

    元の形式が分からないので、**可逆な形式に決め打つ**。
    """
    try:
        picture = image if isinstance(image, QImage) else QImage(image)
    except TypeError:
        # 画像を名乗る貼り付けでも中身が画像とは限らない。エディタを落とさない
        logger.warning("画像として読めない貼り付けだった: %r", type(image))
        return b""
    if picture.isNull():
        return b""

    # **`QBuffer(QByteArray())` と書かない。** 一時オブジェクトが即座に
    # 回収され、解放済みの領域を指したまま書き込んで SIGSEGV になる。
    # 受け皿を変数で保持してから渡す
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    picture.save(buffer, "PNG")
    buffer.close()
    return bytes(storage)


def _urls(source):
    return source.urls() if source.hasUrls() else []


def _image_path(url) -> Path | None:
    if not url.isLocalFile():
        return None
    path = Path(url.toLocalFile())
    return path if path.suffix.lower() in IMAGE_SUFFIXES else None
