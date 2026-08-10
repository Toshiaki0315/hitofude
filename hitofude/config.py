"""設定の読み書き（spec §4）。

`QSettings` を薄く包む。macOS では `~/Library/Preferences/` の plist に
自動保存される。

**設定ファイルは手で編集されうる**（そもそもプレーンテキストを扱うアプリを
使う人はそうする）。壊れた値が入っていても起動できなくなってはいけないので、
読み出しは必ず既定値へフォールバックする。
"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from hitofude.core.paths import relative_inside
from hitofude.storage.index_db import SortOrder
from hitofude.theme import ThemeMode

DEFAULT_VAULT_NAME = "HitofudeNotes"
DEFAULT_FONT_FAMILY = "Hiragino Sans"
# `SF Mono` は macOS がアプリに公開していないので既定にできない（§5.2）
DEFAULT_MONO_FAMILY = "Menlo"
DEFAULT_POINT_SIZE = 15.0
DEFAULT_TRASH_DAYS = 30
# タブ幅（文字数）。Markdown の世界では 4 が標準。Qt の既定は 80px 固定で、
# 本文フォントだと 12 文字ぶんもあった（実測。ユーザーの違和感の元）
DEFAULT_TAB_WIDTH = 4
MIN_TAB_WIDTH = 1
MAX_TAB_WIDTH = 8

# spec §5.1: サイドバー 180px / ノートリスト 280px / エディタ（可変）
DEFAULT_SPLITTER_SIZES = [180, 280, 640]

MIN_POINT_SIZE = 8.0
MAX_POINT_SIZE = 72.0

_VAULT = "vault/path"
_THEME = "theme/mode"
_FONT_FAMILY = "font/family"
_FONT_SIZE = "font/size"
_MONO_FAMILY = "font/mono"
_TRASH_DAYS = "trash/days"
_SPLITTER = "layout/splitter"
_SIDEBAR = "layout/sidebar_visible"
_NOTE_LIST = "layout/note_list_visible"
_TOOLBAR = "layout/toolbar_visible"
_TAB_WIDTH = "editor/tab_width"
_SORT_ORDER = "list/sort_order"
_GEOMETRY = "layout/geometry"
_LAST_NOTE = "session/last_note"


class Config:
    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings if settings is not None else QSettings()

    # ------------------------------------------------------------------ vault

    @property
    def vault_path(self) -> Path:
        stored = self.settings.value(_VAULT, "", type=str)
        if stored:
            return Path(stored)
        return Path.home() / "Documents" / DEFAULT_VAULT_NAME

    @vault_path.setter
    def vault_path(self, value: Path) -> None:
        self.settings.setValue(_VAULT, str(value))

    @property
    def has_vault(self) -> bool:
        """ユーザーが保管フォルダを選んだことがあるか。初回起動の判定に使う。"""
        return bool(self.settings.value(_VAULT, "", type=str))

    # ------------------------------------------------------------------ 見た目

    @property
    def theme_mode(self) -> ThemeMode:
        stored = self.settings.value(_THEME, ThemeMode.SYSTEM.value, type=str)
        try:
            return ThemeMode(stored)
        except ValueError:
            return ThemeMode.SYSTEM

    @theme_mode.setter
    def theme_mode(self, value: ThemeMode) -> None:
        self.settings.setValue(_THEME, value.value)

    @property
    def font_family(self) -> str:
        return self.settings.value(_FONT_FAMILY, DEFAULT_FONT_FAMILY, type=str)

    @font_family.setter
    def font_family(self, value: str) -> None:
        self.settings.setValue(_FONT_FAMILY, value)

    @property
    def font_point_size(self) -> float:
        size = self.settings.value(_FONT_SIZE, DEFAULT_POINT_SIZE, type=float)
        if not MIN_POINT_SIZE <= size <= MAX_POINT_SIZE:
            return DEFAULT_POINT_SIZE
        return size

    @font_point_size.setter
    def font_point_size(self, value: float) -> None:
        self.settings.setValue(_FONT_SIZE, float(value))

    @property
    def mono_family(self) -> str:
        return self.settings.value(_MONO_FAMILY, DEFAULT_MONO_FAMILY, type=str)

    @mono_family.setter
    def mono_family(self, value: str) -> None:
        self.settings.setValue(_MONO_FAMILY, value)

    # ------------------------------------------------------------------ ゴミ箱

    @property
    def trash_days(self) -> int:
        days = self.settings.value(_TRASH_DAYS, DEFAULT_TRASH_DAYS, type=int)
        return days if days > 0 else DEFAULT_TRASH_DAYS

    @trash_days.setter
    def trash_days(self, value: int) -> None:
        self.settings.setValue(_TRASH_DAYS, int(value))

    # ---------------------------------------------------------------- レイアウト

    @property
    def splitter_sizes(self) -> list[int]:
        stored = self.settings.value(_SPLITTER)
        if not isinstance(stored, list) or len(stored) < 2:
            return list(DEFAULT_SPLITTER_SIZES)
        try:
            return [int(value) for value in stored]
        except (TypeError, ValueError):
            return list(DEFAULT_SPLITTER_SIZES)

    @splitter_sizes.setter
    def splitter_sizes(self, value: list[int]) -> None:
        self.settings.setValue(_SPLITTER, [int(size) for size in value])

    @property
    def sidebar_visible(self) -> bool:
        return self.settings.value(_SIDEBAR, True, type=bool)

    @sidebar_visible.setter
    def sidebar_visible(self, value: bool) -> None:
        self.settings.setValue(_SIDEBAR, bool(value))

    @property
    def note_list_visible(self) -> bool:
        return self.settings.value(_NOTE_LIST, True, type=bool)

    @note_list_visible.setter
    def note_list_visible(self, value: bool) -> None:
        self.settings.setValue(_NOTE_LIST, bool(value))

    @property
    def sort_order(self) -> SortOrder:
        """一覧の並び順（C-3）。知らない値は既定へ戻す。"""
        stored = self.settings.value(_SORT_ORDER, SortOrder.MODIFIED.value, type=str)
        try:
            return SortOrder(stored)
        except ValueError:
            return SortOrder.MODIFIED

    @sort_order.setter
    def sort_order(self, value: SortOrder) -> None:
        self.settings.setValue(_SORT_ORDER, value.value)

    @property
    def tab_width(self) -> int:
        """タブを何文字ぶんの幅で見せるか。

        範囲の外や壊れた値は既定へ戻す。設定ファイルは手で編集できるので、
        変な値が入っていても**アプリが起動しなくなってはいけない**。
        """
        try:
            width = int(self.settings.value(_TAB_WIDTH, DEFAULT_TAB_WIDTH))
        except (TypeError, ValueError):
            return DEFAULT_TAB_WIDTH
        if not MIN_TAB_WIDTH <= width <= MAX_TAB_WIDTH:
            return DEFAULT_TAB_WIDTH
        return width

    @tab_width.setter
    def tab_width(self, value: int) -> None:
        self.settings.setValue(_TAB_WIDTH, int(value))

    @property
    def toolbar_visible(self) -> bool:
        """書式ツールバー（B-1）。既定は出す。"""
        return self.settings.value(_TOOLBAR, True, type=bool)

    @toolbar_visible.setter
    def toolbar_visible(self, value: bool) -> None:
        self.settings.setValue(_TOOLBAR, bool(value))

    @property
    def window_geometry(self) -> QByteArray | None:
        stored = self.settings.value(_GEOMETRY)
        if isinstance(stored, QByteArray) and not stored.isEmpty():
            return stored
        if isinstance(stored, bytes | bytearray) and stored:
            return QByteArray(bytes(stored))
        return None

    @window_geometry.setter
    def window_geometry(self, value: QByteArray | bytes) -> None:
        self.settings.setValue(_GEOMETRY, QByteArray(bytes(value)))

    @property
    def last_note(self) -> Path | None:
        """最後に開いていたノート。vault からの**相対パス**。

        絶対パスで覚えると、保管フォルダを移したときに前の場所を指したままに
        なる。vault の外を指す値は捨てる（設定ファイルは手で編集できるので、
        `../` を書かれても vault の外は開かない）。
        """
        stored = self.settings.value(_LAST_NOTE)
        if not isinstance(stored, str) or not stored:
            return None
        return relative_inside(self.vault_path, stored)

    @last_note.setter
    def last_note(self, value: Path | None) -> None:
        relative = relative_inside(self.vault_path, value) if value is not None else None
        if relative is None:
            self.settings.remove(_LAST_NOTE)
        else:
            self.settings.setValue(_LAST_NOTE, str(relative))

    def sync(self) -> None:
        """ディスクへ書き出す。終了時に呼ぶ。"""
        self.settings.sync()
