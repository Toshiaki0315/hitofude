"""探す系の入口の束（spec §5.4 / C-2 / G-1）。

`Cmd+O`（クイックオープン）・`Cmd+Shift+F`（全文検索）・`Cmd+R`
（アウトライン）は、どれも同じパレット部品を使う。`MainWindow` から
切り出した協調オブジェクトで、**挙動は変えない**。ウィンドウの状態には
`self._window` 経由で触る（`export_actions` と同じ「友達」の作り）。
"""

from pathlib import Path

from hitofude.core.outline import headings
from hitofude.core.search import matching_line
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter


class SearchActions:
    """探す入口とパレットの結線。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window
        # 飛び先を探すのに要る。**索引には行番号を持たせない**（作りが
        # 変わって作り直しが要る。開いたノートで数え直せば足りる）
        self._search_query = ""

    # ------------------------------------------------------------- 入口

    def quick_open(self) -> None:
        """`Cmd+O`。タイトルへのあいまい一致で開く（spec §5.4）。"""
        palette = self._make_palette("ノートを開く…")
        palette.set_provider(self._quick_open_items)
        palette.open_with()

    def full_text_search(self) -> None:
        """`Cmd+Shift+F`。本文を検索する（spec §5.4）。

        **選んだら、その箇所へ飛ぶ**（G-1）。抜粋を見て選んだのに先頭が
        開くと、`Cmd+F` で探し直しになる。
        """
        window = self._window
        palette = Palette(window, placeholder="本文を検索…", theme=window._theme_watcher.colors)
        palette.set_provider(self._search_items)
        palette.chosen.connect(self._on_search_chosen)
        palette.finished.connect(palette.deleteLater)
        palette.open_with()

    def open_outline(self) -> None:
        """`Cmd+R`。このノートの見出しへ飛ぶ（C-2）。

        ノート横断のクイックオープンと同じ道具を使う。入口が増えても
        操作を覚え直さずに済む。
        """
        palette = self._make_palette("見出しへ飛ぶ…")
        palette.set_provider(self._outline_items)
        palette.open_with()

    def jump_to_line(self, line: int) -> None:
        """その行の先頭へカーソルを移す（C-2）。無い行番号なら何もしない。"""
        editor = self._window._editor
        block = editor.document().findBlockByNumber(line)
        if not block.isValid():
            return
        cursor = editor.textCursor()
        cursor.setPosition(block.position())
        editor.setTextCursor(cursor)
        editor.centerCursor()
        editor.setFocus()

    # ------------------------------------------------------------- パレット

    def _make_palette(self, placeholder: str) -> Palette:
        window = self._window
        palette = Palette(window, placeholder=placeholder, theme=window._theme_watcher.colors)
        palette.chosen.connect(self._on_palette_chosen)
        # 開くたびに作り直す。前回の入力と結果が残っていると誤操作の元になる
        palette.finished.connect(palette.deleteLater)
        return palette

    def _quick_open_items(self, query: str) -> list[PaletteItem]:
        items = [
            PaletteItem(title=row.title, subtitle=row.preview, path=row.path)
            for row in self._window._db.notes()
        ]
        return fuzzy_filter(query, items)

    def _search_items(self, query: str) -> list[PaletteItem]:
        self._search_query = query
        return [
            PaletteItem(title=hit.title, subtitle=hit.snippet, path=hit.path)
            for hit in self._window._db.search(query)
        ]

    def _outline_items(self, query: str) -> list[PaletteItem]:
        window = self._window
        items = [
            PaletteItem(
                title=found.text or "（無題の見出し）",
                # 字下げで階層を見せる。深さを数字で出しても読み取りにくい
                subtitle="　" * (found.level - 1) + "#" * found.level,
                path=window._note.path if window._note else Path(),
                line=found.line,
            )
            for found in headings(window._editor.toPlainText())
        ]
        return fuzzy_filter(query, items)

    def _on_search_chosen(self, item: PaletteItem) -> None:
        """検索の結果を開いて、一致した行へキャレットを置く（G-1）。

        **見つからなくても開く。** 飛べないだけで、開けないより開くほうがよい。
        """
        window = self._window
        window.open_and_select(window._vault.root / item.path)

        line = matching_line(window._editor.toPlainText(), self._search_query)
        if line is not None:
            self.jump_to_line(line)

    def _on_palette_chosen(self, item: PaletteItem) -> None:
        if item.line is not None:
            self.jump_to_line(item.line)
            return
        window = self._window
        window.open_and_select(window._vault.root / item.path)
