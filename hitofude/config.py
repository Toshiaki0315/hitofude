"""設定の読み書き（spec §4）。

`QSettings` を薄く包む。macOS では `~/Library/Preferences/` の plist に
自動保存される。

**設定ファイルは手で編集されうる**（そもそもプレーンテキストを扱うアプリを
使う人はそうする）。壊れた値が入っていても起動できなくなってはいけないので、
読み出しは必ず既定値へフォールバックする。
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from hitofude.core import graph, llm, ocr
from hitofude.core.paths import relative_inside
from hitofude.storage.index_db import SortOrder
from hitofude.theme import ThemeMode


@dataclass(frozen=True, slots=True)
class SavedSearch:
    """保存した検索（K-4）。名前を付けた検索式をサイドバーに置く。"""

    name: str
    query: str


class LineSpacing(Enum):
    """一覧とサイドバーの行間（ユーザー要望）。値は QSettings に保存する文字列。

    **px では持たない。** 行間の効き方は文字サイズと連れ立って変わるので、
    生の数値を設定に出すと「文字を大きくしたら詰まって見えるから、また
    px を直す」になる。名前で選ばせて、実際の余白は字送りから決める。
    """

    TIGHT = "tight"
    NORMAL = "normal"
    RELAXED = "relaxed"


class ContentWidth(Enum):
    """本文の横幅（I-3 / ADR-0018）。値は QSettings に保存する文字列。

    行間（`LineSpacing`）と同じく **px では持たない**。名前で選ばせて、
    実際の px は対応表（`CONTENT_WIDTH_PIXELS`）が決める。
    """

    STANDARD = "standard"
    WIDE = "wide"
    FULL = "full"


# 0 は「制限なし = 窓幅いっぱい」。使う側（editor）の約束
CONTENT_WIDTH_PIXELS = {
    ContentWidth.STANDARD: 720,  # spec §5.1 の既定
    ContentWidth.WIDE: 880,
    ContentWidth.FULL: 0,
}

DEFAULT_VAULT_NAME = "HitofudeNotes"
DEFAULT_FONT_FAMILY = "Hiragino Sans"
# `SF Mono` は macOS がアプリに公開していないので既定にできない（§5.2）
DEFAULT_MONO_FAMILY = "Menlo"
DEFAULT_POINT_SIZE = 15.0
DEFAULT_TRASH_DAYS = 30
# タブ幅（文字数）。Markdown の世界では 4 が標準。Qt の既定は 80px 固定で、
# 本文フォントだと 12 文字ぶんもあった（実測。ユーザーの違和感の元）
MIN_GRAPH_DEPTH = 1
MAX_GRAPH_DEPTH = 3
"""図の深さの幅。**3 で一気に増える**（点の数の 2 乗で効く。TASKS.md の M-2）。"""

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
_BACKLINKS = "layout/backlinks_expanded"
_OUTLINE = "layout/outline_visible"
_ASSISTANT = "layout/assistant_visible"
_LLM_MODEL = "llm/model"
_LLM_PORT = "llm/port"
_LLM_CONTEXT = "llm/context"
_OCR_ENGINE = "ocr/engine"
_GRAPH_DEPTH = "graph/depth"
_TAB_WIDTH = "editor/tab_width"
_SORT_ORDER = "list/sort_order"
_GEOMETRY = "layout/geometry"
_LAST_NOTE = "session/last_note"
_LINE_SPACING = "layout/line_spacing"
_CONTENT_WIDTH = "editor/content_width"
_SAVED_SEARCHES = "sidebar/saved_searches"


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
    def line_spacing(self) -> LineSpacing:
        """行間。壊れた値は既定（ふつう）へ戻す。"""
        raw = self.settings.value(_LINE_SPACING, LineSpacing.NORMAL.value, type=str)
        try:
            return LineSpacing(raw)
        except ValueError:
            return LineSpacing.NORMAL

    @line_spacing.setter
    def line_spacing(self, value: LineSpacing) -> None:
        self.settings.setValue(_LINE_SPACING, value.value)

    @property
    def content_width(self) -> ContentWidth:
        """本文の横幅。壊れた値は既定（標準）へ戻す。"""
        raw = self.settings.value(_CONTENT_WIDTH, ContentWidth.STANDARD.value, type=str)
        try:
            return ContentWidth(raw)
        except ValueError:
            return ContentWidth.STANDARD

    @content_width.setter
    def content_width(self, value: ContentWidth) -> None:
        self.settings.setValue(_CONTENT_WIDTH, value.value)

    @property
    def saved_searches(self) -> list[SavedSearch]:
        """保存した検索（K-4）。壊れた値は空へ戻す。"""
        raw = self.settings.value(_SAVED_SEARCHES, "[]", type=str)
        try:
            entries = json.loads(raw)
            return [
                SavedSearch(name=str(entry["name"]), query=str(entry["query"]))
                for entry in entries
                if isinstance(entry, dict) and entry.get("name") and "query" in entry
            ]
        except (ValueError, TypeError, KeyError):
            return []

    @saved_searches.setter
    def saved_searches(self, value: list[SavedSearch]) -> None:
        payload = [{"name": entry.name, "query": entry.query} for entry in value]
        self.settings.setValue(_SAVED_SEARCHES, json.dumps(payload, ensure_ascii=False))

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
    def outline_visible(self) -> bool:
        """アウトラインの欄を出すか（提案 5）。**既定は出さない。**

        画面を勝手に狭くしない。要る人が `Cmd+5` で開く。
        """
        return self.settings.value(_OUTLINE, False, type=bool)

    @outline_visible.setter
    def outline_visible(self, value: bool) -> None:
        self.settings.setValue(_OUTLINE, bool(value))

    @property
    def assistant_visible(self) -> bool:
        """ローカルLLM の欄を出すか（L-1）。**既定は出さない。**

        画面を勝手に狭くしない。要る人が `Cmd+6` で開く（アウトラインと同じ）。
        """
        return self.settings.value(_ASSISTANT, False, type=bool)

    @assistant_visible.setter
    def assistant_visible(self, value: bool) -> None:
        self.settings.setValue(_ASSISTANT, bool(value))

    # ------------------------------------------------------- ローカルLLM

    @property
    def llm_model(self) -> str:
        """読ませるモデル（ADR-0025 追記）。**空なら既定へ戻す。**

        空のまま保存できると、押しても何も起きないアプリになる。
        """
        found = str(self.settings.value(_LLM_MODEL, llm.DEFAULT_MODEL)).strip()
        return found or llm.DEFAULT_MODEL

    @llm_model.setter
    def llm_model(self, value: str) -> None:
        self.settings.setValue(_LLM_MODEL, value.strip() or llm.DEFAULT_MODEL)

    @property
    def llm_port(self) -> int:
        """Ollama のポート（ADR-0025 追記）。

        **相手は `127.0.0.1` に固定**で、設定に出すのはポートだけ。
        `OLLAMA_HOST` で別のポートにしている人がいるので、そこだけ開ける。
        外の機械を指せるようにはしない（ノートが外に出ない、が前提）。
        """
        found = self.settings.value(_LLM_PORT, llm.DEFAULT_PORT, type=int)
        return found if 1 <= found <= 65535 else llm.DEFAULT_PORT

    @llm_port.setter
    def llm_port(self, value: int) -> None:
        self.settings.setValue(_LLM_PORT, int(value))

    @property
    def llm_context(self) -> int:
        """一度に渡せる長さ（トークン）。

        短すぎれば指示すら入らず、長すぎればメモリを食い潰す。
        知らない値は既定へ戻す（設定ファイルは手で編集できる）。
        """
        found = self.settings.value(_LLM_CONTEXT, llm.CONTEXT_TOKENS, type=int)
        return found if found in llm.CONTEXT_CHOICES else llm.CONTEXT_TOKENS

    @llm_context.setter
    def llm_context(self, value: int) -> None:
        self.settings.setValue(_LLM_CONTEXT, int(value))

    @property
    def ocr_engine(self) -> ocr.Engine:
        """画像を文字にする読み手（ADR-0027）。**既定は macOS**（速くて正確）。

        知らない値は既定へ戻す（設定ファイルは手で編集できる）。
        """
        found = str(self.settings.value(_OCR_ENGINE, ocr.DEFAULT_ENGINE.value))
        try:
            return ocr.Engine(found)
        except ValueError:
            return ocr.DEFAULT_ENGINE

    @ocr_engine.setter
    def ocr_engine(self, value: ocr.Engine) -> None:
        self.settings.setValue(_OCR_ENGINE, ocr.Engine(value).value)

    @property
    def graph_depth(self) -> int:
        """リンクの図で何段先まで辿るか（M-2）。

        **毎回選び直させない。** 範囲の外は既定へ戻す（設定ファイルは手で
        編集できるので、変な値でアプリが壊れてはいけない）。
        """
        found = self.settings.value(_GRAPH_DEPTH, graph.DEFAULT_DEPTH, type=int)
        return found if MIN_GRAPH_DEPTH <= found <= MAX_GRAPH_DEPTH else graph.DEFAULT_DEPTH

    @graph_depth.setter
    def graph_depth(self, value: int) -> None:
        self.settings.setValue(_GRAPH_DEPTH, max(MIN_GRAPH_DEPTH, min(MAX_GRAPH_DEPTH, int(value))))

    @property
    def toolbar_visible(self) -> bool:
        """書式ツールバー（B-1）。既定は出す。"""
        return self.settings.value(_TOOLBAR, True, type=bool)

    @toolbar_visible.setter
    def toolbar_visible(self, value: bool) -> None:
        self.settings.setValue(_TOOLBAR, bool(value))

    @property
    def backlinks_expanded(self) -> bool:
        """バックリンクの帯を開いておくか（E-6）。**既定は畳む。**

        帯は本文の下に居続けるので、開きっぱなしは場所を取る。件数だけ
        見えていれば「繋がりがある」ことは伝わる。
        """
        return self.settings.value(_BACKLINKS, False, type=bool)

    @backlinks_expanded.setter
    def backlinks_expanded(self, value: bool) -> None:
        self.settings.setValue(_BACKLINKS, bool(value))

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
