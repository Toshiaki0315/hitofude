"""コマンドパレットを窓に繋ぐ（U-3）。

**ノートを開く道具と同じ `Palette` を使う。** 入口が増えても操作を
覚え直さずに済む（アウトラインのパレットと同じ考え方）。
"""

import pytest

pytestmark = pytest.mark.gui


class TestOpen:
    def test_開ける(self, window, qtbot) -> None:
        palette = window.command_palette()
        try:
            assert palette is not None
            assert palette.isVisible()
        finally:
            palette.close()

    def test_命令が並ぶ(self, window) -> None:
        palette = window.command_palette()
        try:
            labels = [item.title for item in palette.items]
            assert "新規ノート" in labels
        finally:
            palette.close()

    def test_どこの項目か出る(self, window) -> None:
        palette = window.command_palette()
        try:
            found = next(item for item in palette.items if item.title == "新規ノート")
            assert "ファイル" in found.subtitle
        finally:
            palette.close()

    def test_絞り込める(self, window) -> None:
        palette = window.command_palette()
        try:
            palette.open_with("新規")
            labels = [item.title for item in palette.items]
            assert labels and all("新" in label or "規" in label for label in labels)
        finally:
            palette.close()


class TestRun:
    def test_選ぶと動く(self, window, qtbot) -> None:
        """**選んで終わりではない。** 実際にその命令が走る。"""
        palette = window.command_palette()
        try:
            before = window.reference.isHidden()
            # **絞ってから選ぶ。** 空の入力では上位 50 件しか並ばない
            palette.open_with("横に開く")
            found = next(item for item in palette.items if item.title == "横に開く欄")
            palette.chosen.emit(found)
            assert window.reference.isHidden() is not before
        finally:
            palette.close()

    def test_選んでも絞り込みを動かさない(self, window, qtbot) -> None:
        """**命令を選ぶたびに一覧がルートへ戻っていた**（レビュー指摘 2026-08-31）。

        `_make_palette` が繋ぐノートを開く受け手にも `chosen` が届き、
        `path=Path()` を vault ルートとして開こうとして絞り込みが
        リセットされていた。タグで絞ったまま命令だけ走ること。
        """
        from hitofude.ui.sidebar import Filter, FilterKind

        window._editor.setPlainText("# 仕事メモ\n\n#仕事\n")
        window.set_filter(Filter(FilterKind.TAG, tag="仕事"))
        palette = window.command_palette()
        try:
            palette.open_with("横に開く")
            found = next(item for item in palette.items if item.title == "横に開く欄")
            palette.chosen.emit(found)
            assert window.filter == Filter(FilterKind.TAG, tag="仕事")
        finally:
            palette.close()


class TestCompact:
    """命令のほうは **1 行ずつ**にする（ユーザー指摘 2026-08-29）。

    ノートを探すパレットと同じ 2 行表示だと、開いた瞬間にどちらの
    ダイアログか分からない。命令は題名も短いので 1 行で足りる。
    """

    def rows(self, palette) -> list:
        view = palette._results
        delegate = view.itemDelegate()
        return [
            delegate.sizeHint(palette._option_for_test(row), view.model().index(row, 0)).height()
            for row in range(min(3, view.count()))
        ]

    def test_命令は1行(self, window) -> None:
        palette = window.command_palette()
        try:
            palette.open_with("新規")
            assert palette.compact is True
        finally:
            palette.close()

    def test_ノートは今までどおり2行(self, window) -> None:
        """**直しすぎない。** ノートは副題（本文の抜粋）が要るので 2 行のまま。

        共通の作り口（`_make_palette`）の既定を見る——命令のパレットだけが
        1 行を頼む形になっていること。
        """
        palette = window._search._make_palette("ノートを探す…")
        try:
            assert palette.compact is False
        finally:
            palette.close()

    def test_1行のほうが低い(self, window) -> None:
        """見た目の違いを高さで確かめる（同じ中身で比べる）。"""
        from pathlib import Path

        from hitofude.ui.quick_open import Palette, PaletteItem

        item = PaletteItem(title="新規ノート", subtitle="ファイル Ctrl+N", path=Path())
        tall = Palette(window, theme=window._theme_watcher.colors)
        flat = Palette(window, theme=window._theme_watcher.colors, compact=True)
        try:
            for palette in (tall, flat):
                palette.set_provider(lambda _q, found=[item]: found)
                palette.open_with()
            assert flat.row_height(0) < tall.row_height(0)
        finally:
            tall.close()
            flat.close()

    def test_題も道筋も出る(self, window) -> None:
        """**縮めても情報は落とさない。** どこの項目かは要る。"""
        from pathlib import Path

        from hitofude.ui.quick_open import Palette, PaletteItem

        item = PaletteItem(title="新規ノート", subtitle="ファイル Ctrl+N", path=Path())
        palette = Palette(window, theme=window._theme_watcher.colors, compact=True)
        try:
            palette.set_provider(lambda _q, found=[item]: found)
            palette.open_with()
            text = palette.row_text(0)
            assert "新規ノート" in text
            assert "ファイル" in text
        finally:
            palette.close()

    def test_横に溢れない(self, window) -> None:
        """1 行にすると長い項目が横へ伸びる（実測: 溢れ 18px）。

        **横スクロールバーを出さない。** 命令を選ぶだけの窓で横に
        スクロールさせる意味が無く、2 行のときは出ていなかった。
        """
        palette = window.command_palette()
        try:
            palette.resize(560, 380)
            assert palette._results.horizontalScrollBar().maximum() == 0
        finally:
            palette.close()
