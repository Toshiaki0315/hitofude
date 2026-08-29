"""文体の指摘を画面に出す（U-4）。

**まずパレットで出す。** 本文に波線を引くのは打鍵ごとの経路に入る
（§6.6 の 16ms）ので、まず「見たいときに見る」形から始める。

出す道具はアウトラインへ飛ぶのと同じ `Palette`——入口が増えても
操作を覚え直さずに済む。
"""

import pytest

pytestmark = pytest.mark.gui

PROSE = """# 下書き

これを実行することができます。まず最初に違和感を感じました。

本文の上の表のボタンを押す。
"""


@pytest.fixture
def opened(window):
    note = window._vault.create("下書き", PROSE)
    window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(note.path)
    return window


class TestPalette:
    def test_開ける(self, opened) -> None:
        palette = opened.check_style()
        try:
            assert palette is not None
        finally:
            palette.close()

    def test_指摘が並ぶ(self, opened) -> None:
        palette = opened.check_style()
        try:
            titles = [item.title for item in palette.items]
            assert any("することができ" in title for title in titles)
        finally:
            palette.close()

    def test_言い換えを添える(self, opened) -> None:
        """**どう書けるか**が出る。何が悪いかだけでは動けない。"""
        palette = opened.check_style()
        try:
            found = next(item for item in palette.items if "することができ" in item.title)
            assert "できます" in found.subtitle
        finally:
            palette.close()

    def test_1行ずつ出す(self, opened) -> None:
        """コマンドパレットと同じ形（短い指摘に 2 行は要らない）。"""
        palette = opened.check_style()
        try:
            assert palette.compact is True
        finally:
            palette.close()

    def test_選ぶとその場所へ飛ぶ(self, opened) -> None:
        palette = opened.check_style()
        try:
            found = next(item for item in palette.items if "することができ" in item.title)
            palette.chosen.emit(found)
            cursor = opened.editor.textCursor()
            assert cursor.block().text().startswith("これを実行")
        finally:
            palette.close()


class TestQuiet:
    def test_指摘が無ければ知らせる(self, window) -> None:
        """**空のパレットを出さない。** 何も無いことが分かればよい。"""
        note = window._vault.create("素直な文", "# 素直な文\n\nこれを実行できます。\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_and_select(note.path)
        assert window.check_style() is None
        assert "見つかりません" in window.notice()

    def test_開いていなければ何もしない(self, window) -> None:
        window._note = None
        assert window.check_style() is None
