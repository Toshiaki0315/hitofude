"""パレットに一言の案内を出す（案 1）。

`after:きのう` のように日付として読めない書き方をしたとき、そのまま
探すと 0 件になり、**書き方が違うのか本当に無いのかが分からない**
（ユーザー指摘）。書き方だけ知らせる。
"""

import pytest

from hitofude.ui.quick_open import Palette

pytestmark = pytest.mark.gui


@pytest.fixture
def palette(qtbot) -> Palette:
    widget = Palette(placeholder="本文を検索…")
    qtbot.addWidget(widget)
    widget.set_provider(lambda _query: [])
    return widget


class TestHintWidget:
    def test_既定では出ていない(self, palette) -> None:
        """**要らないときに場所を取らない。** 一覧が狭くなる。"""
        palette.open_with("")
        assert palette.hint_visible() is False

    def test_出せる(self, palette) -> None:
        palette.set_hint("日付は after:2026-08-01 の形で書いてください")
        assert palette.hint_visible() is True
        assert "after:2026-08-01" in palette.hint_text()

    def test_空にすると消える(self, palette) -> None:
        palette.set_hint("なにか")
        palette.set_hint("")
        assert palette.hint_visible() is False

    def test_打ち直すと消える(self, palette) -> None:
        """**前の案内を残さない。** 直したのに出たままだと直っていないように見える。"""
        palette.open_with("")
        palette.set_hint("なにか")
        palette._refresh("予算")
        assert palette.hint_visible() is False


class TestInSearch:
    def test_読めない日付で案内が出る(self, window) -> None:
        window._search._search_items("after:きのう")
        assert "after:2026-08-01" in window._search.last_hint()

    def test_読める日付では出ない(self, window) -> None:
        window._search._search_items("after:2026-08-01")
        assert window._search.last_hint() == ""

    def test_ふつうの検索では出ない(self, window) -> None:
        window._search._search_items("予算")
        assert window._search.last_hint() == ""

    def test_探すのはやめない(self, window) -> None:
        """案内は出すが、打った文字は探す（そう書いたものが見つかることもある）。"""
        note = window.vault.create("メモ", "# メモ\n\nafter:きのう と書いた\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()

        items = window._search._search_items("after:きのう")
        assert [item.title for item in items] == ["メモ"]
