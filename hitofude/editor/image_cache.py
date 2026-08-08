"""本文に描く画像の読み込みとキャッシュ（タスク A-2）。

**毎回読み直さない。** 3024x1964 の PNG を読んで縮小すると 21ms かかり、
§6.6 の「打鍵 → 画面反映 16ms」を単独で超える。縮小結果を持ち回れば
0.05ms（実測）。ここが無いと本文中の画像表示は成立しない。

保管フォルダの外は読まない。本文は手で編集できるので、`../` や絶対パスで
任意のファイルを開かせない（`editor/exporter.py` と同じ判断）。
"""

from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

# 画面内に同時に見える枚数はせいぜい数枚。行き過ぎない範囲で余裕を持たせる
MAX_ENTRIES = 32


class ImageCache:
    """`(パス, mtime, 表示幅)` を鍵に、縮小済みの `QPixmap` を持ち回る。"""

    MAX_ENTRIES = MAX_ENTRIES

    def __init__(self, base_path: Path | None = None) -> None:
        self._base = Path(base_path) if base_path is not None else None
        self._entries: OrderedDict[tuple[str, int, int], QPixmap] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def set_base_path(self, base_path: Path | None) -> None:
        """保管フォルダが変わったら、抱えていたものは意味を失う。"""
        self._base = Path(base_path) if base_path is not None else None
        self.clear()

    def clear(self) -> None:
        self._entries.clear()

    def resolve(self, url: str) -> Path | None:
        """本文のパスを実ファイルへ解決する。**外は返さない。**

        `http(s)` は取りに行かない。描画のたびに通信するわけにいかない。
        """
        if self._base is None or url.startswith(("http:", "https:", "data:")):
            return None

        candidate = Path(unquote(url))
        if candidate.is_absolute():
            return None

        base = self._base.resolve()
        resolved = (base / candidate).resolve()
        if not resolved.is_relative_to(base) or not resolved.is_file():
            return None
        return resolved

    def pixmap(self, url: str, max_width: int) -> QPixmap | None:
        """表示用に縮小した画像。読めなければ None。"""
        path = self.resolve(url)
        if path is None:
            return None

        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return None

        key = (str(path), stamp, max_width)
        found = self._entries.get(key)
        if found is not None:
            self._entries.move_to_end(key)
            return found

        loaded = QPixmap(str(path))
        if loaded.isNull():
            return None

        # **拡大はしない。** 40px の絵を 720px に引き伸ばしてもぼやけるだけ
        scaled = (
            loaded
            if loaded.width() <= max_width
            else loaded.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        )
        self._entries[key] = scaled
        while len(self._entries) > MAX_ENTRIES:
            self._entries.popitem(last=False)
        return scaled

    def size(self, url: str, max_width: int) -> tuple[int, int] | None:
        """表示したときの大きさ。行の高さを決めるのに使う。

        ハイライタから**ブロックごとに毎回**呼ばれるので、
        `pixmap()` と同じキャッシュに乗せる。
        """
        found = self.pixmap(url, max_width)
        return None if found is None else (found.width(), found.height())
