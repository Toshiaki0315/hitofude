"""一覧が組み直されたら、表示中のノートに選択を当てる（ユーザー要望 2026-08-28）。

`set_rows()` は**前の選択**を覚えて戻していた。それが新しい並びに無いと
何も選ばれない——たとえば「お気に入り」（0 件）へ絞ってからフォルダへ
戻すと、**開いているノートが一覧にあるのに選ばれていない**（実測）。

本文が出ているのに一覧のどれか分からない状態なので、前の選択で当たら
なければ**表示中のノート**で当て直す。
"""

from pathlib import Path

import pytest

from hitofude.ui.sidebar import Filter, FilterKind

pytestmark = pytest.mark.gui


@pytest.fixture
def opened(window):
    note = window._vault.create("箱のノート", "# 箱のノート\n\n本文\n")
    moved = window._notes.move_note_to(note.path, "箱")
    other = window._vault.create("外のノート", "# 外のノート\n\n本文\n")
    window._db.upsert_note(window._vault.read(other.path), window._vault.root)
    window.refresh()
    window.open_and_select(moved)
    return window


def shown(window) -> Path:
    return window.current_note.path.relative_to(window._vault.root)


class TestFilterRoundTrip:
    def test_戻したら選ばれている(self, opened) -> None:
        """**これが本題。** 0 件の絞り込みを挟むと選択が失われていた。"""
        box = Filter(FilterKind.FOLDER, folder="箱")
        opened.set_filter(Filter(FilterKind.PINNED))
        opened.set_filter(box)
        assert opened.note_list.current_path() == shown(opened)

    def test_すべてへ戻しても選ばれている(self, opened) -> None:
        opened.set_filter(Filter(FilterKind.PINNED))
        opened.set_filter(Filter(FilterKind.ALL))
        assert opened.note_list.current_path() == shown(opened)

    def test_一覧に無いなら選ばない(self, opened) -> None:
        """**当てずっぽうで別のノートを選ばない。**"""
        opened.set_filter(Filter(FilterKind.PINNED))
        assert opened.note_list.current_path() is None


class TestRefresh:
    def test_引き直しでも当たる(self, opened) -> None:
        opened.note_list.clearSelection()
        opened.note_list.setCurrentIndex(opened.note_list.model().index(-1, -1))
        opened.refresh()
        assert opened.note_list.current_path() == shown(opened)

    def test_開いていないなら選ばない(self, window) -> None:
        """ノートを開いていなければ、勝手に選ばない。"""
        note = window._vault.create("一枚", "# 一枚\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        assert window.note_list.current_path() is None
