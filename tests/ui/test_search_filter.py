"""検索をタグで絞る（提案 3）。

`Cmd+Shift+F` は全文一致だけだった。**入力欄は増やさず**、`#仕事 予算` と
本文と同じ書き方で絞れるようにする。
"""

import pytest

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def add(window: MainWindow, title: str, body: str) -> None:
    note = window.vault.create(title, f"# {title}\n\n{body}\n")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()


@pytest.fixture
def filled(window: MainWindow) -> MainWindow:
    add(window, "仕事の予算", "来期の予算を決める\n\n#仕事")
    add(window, "私用の予算", "旅行の予算を決める\n\n#私用")
    add(window, "会議の記録", "来期の予算の話\n\n#仕事/会議")
    return window


def titles(window: MainWindow, query: str) -> set[str]:
    return {item.title for item in window._search._search_items(query)}


class TestFilter:
    def test_タグで絞れる(self, filled) -> None:
        assert titles(filled, "#仕事 予算") == {"仕事の予算", "会議の記録"}

    def test_タグ無しは今まで通り(self, filled) -> None:
        assert titles(filled, "予算") == {"仕事の予算", "私用の予算", "会議の記録"}

    def test_タグだけでも引ける(self, filled) -> None:
        assert titles(filled, "#私用") == {"私用の予算"}

    def test_親のタグで子も出る(self, filled) -> None:
        assert titles(filled, "#仕事") == {"仕事の予算", "会議の記録"}

    def test_書く順は問わない(self, filled) -> None:
        assert titles(filled, "予算 #私用") == {"私用の予算"}


class TestJump:
    def test_選ぶとその行へ飛ぶ(self, filled) -> None:
        """G-1 の飛び先は**言葉のほう**で探す（`#仕事` は本文に無い）。"""
        from hitofude.ui.quick_open import PaletteItem

        items = filled._search._search_items("#仕事 予算")
        target = next(i for i in items if i.title == "仕事の予算")
        filled._search._on_search_chosen(
            PaletteItem(title=target.title, subtitle=target.subtitle, path=target.path)
        )
        line = filled.editor.textCursor().blockNumber()
        assert "予算" in filled.editor.toPlainText().split("\n")[line]


class TestHint:
    def test_書き方を案内する(self, window) -> None:
        """**書けることを知らせる。** 説明が無いと誰も使わない。"""
        assert "#" in window._search.search_placeholder()
