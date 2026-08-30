"""探す系の入口の束（spec §5.4 / C-2 / G-1）。

`Cmd+O`（クイックオープン）・`Cmd+Shift+F`（全文検索）・`Cmd+R`
（アウトライン）は、どれも同じパレット部品を使う。`MainWindow` から
切り出した協調オブジェクトで、**挙動は変えない**。ウィンドウの状態には
`self._window` 経由で触る（`export_actions` と同じ「友達」の作り）。
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QInputDialog

from hitofude.core import searchquery, style_check
from hitofude.core.outline import headings
from hitofude.core.search import matching_line
from hitofude.core.textpos import py_to_utf16
from hitofude.ui.commands import commands
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter

# 検索欄の案内（提案 3）。**書き方をここで知らせる。** 入力欄を増やさない
# 代わりに、絞り込みが書けることは案内で伝える
SEARCH_PLACEHOLDER = "本文を検索…（#タグ after:2026-08-01 で絞れます）"
COMMAND_PLACEHOLDER = "命令を探す…"
STYLE_PLACEHOLDER = "文体の指摘…（選ぶとその場所へ飛びます）"
STYLE_CLEAN_NOTICE = "気になる言い回しは見つかりませんでした"

# 日付として読めない `after:` / `before:` を書いたときの案内（案 1）。
# **探すのはやめない**が、書き方が違うことは伝える
DATE_HINT = "日付は after:2026-08-01 の形で書いてください（絞り込みはしていません）"


class SearchActions:
    """探す入口とパレットの結線。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window
        # 飛び先を探すのに要る。**索引には行番号を持たせない**（作りが
        # 変わって作り直しが要る。開いたノートで数え直せば足りる）
        self._search_query = ""
        # 書き方の案内（案 1）。出す先のパレットは開くたびに作り直す
        self._hint = ""
        self._palette: Palette | None = None

    # ------------------------------------------------------------- 入口

    def quick_open(self) -> None:
        """`Cmd+O`。タイトルへのあいまい一致で開く（spec §5.4）。"""
        palette = self._make_palette("ノートを開く…")
        palette.set_provider(self._quick_open_items)
        palette.open_with()

    def save_search(self) -> bool:
        """検索式に名前を付けてサイドバーへ置く（K-4）。保存したら True。

        式 → 名前の順で聞く。名前の既定は式そのもの（短い式なら
        そのまま通せる）。同じ名前は上書き（検索式の更新に使う）。
        """
        window = self._window
        query, accepted = QInputDialog.getText(
            window,
            "検索を保存",
            "検索式（#タグ / after: / before: と言葉）",
            text=self._search_query,
        )
        if not accepted or not query.strip():
            return False
        name, accepted = QInputDialog.getText(
            window, "検索を保存", "サイドバーに出す名前", text=query.strip()
        )
        if not accepted or not name.strip():
            return False

        from hitofude.config import SavedSearch

        entry = SavedSearch(name=name.strip(), query=query.strip())
        kept = [found for found in window._config.saved_searches if found.name != entry.name]
        window._config.saved_searches = [*kept, entry]
        window.reload_saved_searches()
        window.notify(f"検索「{entry.name}」を保存しました")
        return True

    def full_text_search(self) -> None:
        """`Cmd+Shift+F`。本文を検索する（spec §5.4）。

        **選んだら、その箇所へ飛ぶ**（G-1）。抜粋を見て選んだのに先頭が
        開くと、`Cmd+F` で探し直しになる。
        """
        window = self._window
        palette = Palette(
            window, placeholder=SEARCH_PLACEHOLDER, theme=window._theme_watcher.colors
        )
        self._palette = palette
        palette.set_provider(self._search_items)
        palette.chosen.connect(self._on_search_chosen)
        palette.finished.connect(palette.deleteLater)
        palette.open_with()

    def command_palette(self) -> Palette:
        """`Cmd+Shift+P`。命令を名前で探して動かす（U-3）。

        **ノートを開く道具と同じ `Palette`** を使う。入口が増えても操作を
        覚え直さずに済む（アウトラインのパレットと同じ考え方）。

        並べるのは**メニューバーから集めたもの**（`ui/commands`）。別に
        一覧を持つと、メニューに足したのにここへ出ないが起きる。
        """
        # **1 行ずつ**（U-3）。ノートを探すパレットと見分けが付くように。
        # 受け手は命令の実行だけ。既定のノートを開く受け手が混ざると、
        # 選ぶたびに絞り込みがルートへ戻る（レビュー指摘 2026-08-31）
        palette = self._make_palette(
            COMMAND_PLACEHOLDER, compact=True, chosen=self._on_command_chosen
        )
        palette.set_provider(self._command_items)
        palette.open_with()
        return palette

    def _command_items(self, query: str) -> list[PaletteItem]:
        found = [
            PaletteItem(
                title=command.label,
                subtitle=f"{command.path}　{command.shortcut}".strip(),
                path=Path(),
                payload=command.action,
            )
            for command in commands(self._window.menuBar())
        ]
        return fuzzy_filter(query, found)

    def _on_command_chosen(self, item: PaletteItem) -> None:
        action = item.payload
        if action is not None:
            action.trigger()

    def open_outline(self) -> None:
        """`Cmd+R`。このノートの見出しへ飛ぶ（C-2）。

        ノート横断のクイックオープンと同じ道具を使う。入口が増えても
        操作を覚え直さずに済む。
        """
        palette = self._make_palette("見出しへ飛ぶ…")
        palette.set_provider(self._outline_items)
        palette.open_with()

    def check_style(self) -> Palette | None:
        """`文体を見る`。日本語の言い回しを指摘する（U-4）。

        **まずパレットで出す。** 本文に波線を引くのは打鍵ごとの経路に
        入る（§6.6 の 16ms）ので、「見たいときに見る」形から始める。
        出す道具はアウトラインへ飛ぶのと同じ `Palette`。

        **空のパレットは出さない。** 何も無いことが分かればよい。
        """
        window = self._window
        if window._note is None:
            return None
        text = window._editor.toPlainText()
        found = style_check.check(text)
        if not found:
            window.notify(STYLE_CLEAN_NOTICE)
            return None

        document = window._editor.document()
        items = [
            PaletteItem(
                title=text[item.start : item.end].strip() or "（空白）",
                subtitle=item.message,
                path=window._note.path,
                line=document.findBlock(py_to_utf16(text, item.start)).blockNumber(),
            )
            for item in found
        ]
        palette = self._make_palette(STYLE_PLACEHOLDER, compact=True)
        palette.set_provider(lambda query: fuzzy_filter(query, items))
        palette.open_with()
        return palette

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

    def _make_palette(
        self,
        placeholder: str,
        *,
        compact: bool = False,
        chosen: Callable[[PaletteItem], None] | None = None,
    ) -> Palette:
        """共通の組み立て。`chosen` 省略時は**ノートを開く**受け手を繋ぐ。

        受け手は 1 つだけ。ここで繋いだ上に呼び出し側でも `chosen` を
        繋ぐと両方が走る（コマンドパレットで絞り込みが飛んだ）。
        ノート以外を並べるパレットは自分の受け手をここへ渡すこと。
        """
        window = self._window
        palette = Palette(
            window,
            placeholder=placeholder,
            theme=window._theme_watcher.colors,
            compact=compact,
        )
        palette.chosen.connect(chosen if chosen is not None else self._on_palette_chosen)
        # 開くたびに作り直す。前回の入力と結果が残っていると誤操作の元になる
        palette.finished.connect(palette.deleteLater)
        return palette

    def _quick_open_items(self, query: str) -> list[PaletteItem]:
        items = [
            PaletteItem(title=row.title, subtitle=row.preview, path=row.path)
            for row in self._window._db.notes()
        ]
        return fuzzy_filter(query, items)

    def search_placeholder(self) -> str:
        """検索欄の案内。**書き方を知らせる**（説明が無いと誰も使わない）。"""
        return SEARCH_PLACEHOLDER

    def last_hint(self) -> str:
        """直前の検索で出した案内。空なら出していない。"""
        return self._hint

    def _search_items(self, query: str) -> list[PaletteItem]:
        parsed = searchquery.parse(query)
        self._hint = DATE_HINT if parsed.unreadable_dates else ""
        if self._palette is not None:
            self._palette.set_hint(self._hint)
        # 飛び先（G-1）は**言葉のほう**で探す。`#仕事` は本文に無いので、
        # そのまま渡すと一致する行が見つからず先頭が開く
        self._search_query = parsed.text
        return [
            PaletteItem(title=hit.title, subtitle=hit.snippet, path=hit.path)
            for hit in self._window._db.search(
                parsed.text, tags=parsed.tags, after=parsed.after, before=parsed.before
            )
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
