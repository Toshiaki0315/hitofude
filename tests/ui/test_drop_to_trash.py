"""一覧からゴミ箱へドラッグして捨てる（ユーザー要望 2026-08-28）。

**フォルダへのドラッグは既にある**（サイドバーが受ける）。同じ操作で
ゴミ箱にも落とせるのが自然——Finder と同じ形。

行き先で意味が変わるので、**信号は分ける**。フォルダ名にゴミ箱を
混ぜると、`.trash` という名前のフォルダと見分けが付かなくなる。
"""

from pathlib import Path

import pytest

from hitofude.ui.sidebar import Filter, FilterKind

pytestmark = pytest.mark.gui


@pytest.fixture
def opened(window):
    note = window._vault.create("捨てるノート", "# 捨てるノート\n\n本文\n")
    window._db.upsert_note(note, window._vault.root)
    other = window._vault.create("残すノート", "# 残すノート\n\n本文\n")
    window._db.upsert_note(other, window._vault.root)
    window.refresh()
    return window


class TestSidebarAcceptsTrash:
    """サイドバー側（受ける口）。"""

    def test_ゴミ箱の行を受ける(self, opened) -> None:
        sidebar = opened._sidebar
        assert sidebar.drop_kind(Filter(FilterKind.TRASH)) is True

    def test_フォルダは今までどおり(self, opened) -> None:
        sidebar = opened._sidebar
        assert sidebar.drop_kind(Filter(FilterKind.FOLDER, folder="箱")) is True

    def test_タグには落とせない(self, opened) -> None:
        """**行き先が無い。** タグは本文の `#タグ` が真実。"""
        sidebar = opened._sidebar
        assert sidebar.drop_kind(Filter(FilterKind.TAG, tag="仕事")) is False

    def test_お気に入りにも落とせない(self, opened) -> None:
        sidebar = opened._sidebar
        assert sidebar.drop_kind(Filter(FilterKind.PINNED)) is False


class TestDropMovesToTrash:
    """窓側（受けたあと）。"""

    def test_ゴミ箱へ移る(self, opened) -> None:
        path = opened._vault.root / "捨てるノート.md"
        opened._on_note_trashed(Path("捨てるノート.md"))
        assert not path.exists()
        assert (opened._vault.trash_dir / "捨てるノート.md").exists()

    def test_一覧から消える(self, opened) -> None:
        opened._on_note_trashed(Path("捨てるノート.md"))
        opened.refresh()
        names = [
            opened.note_list.model().index(row, 0).data()
            for row in range(opened.note_list.model().rowCount())
        ]
        assert "捨てるノート" not in names

    def test_お気に入りは捨てない(self, opened) -> None:
        """**ピン留めは「これは残す」という意思表示**（メニューと同じ扱い）。"""
        path = opened._vault.root / "捨てるノート.md"
        opened._notes.toggle_pin(path)
        opened._on_note_trashed(Path("捨てるノート.md"))
        assert path.exists()


class TestRealDrop:
    """**本物の `dropEvent` を通す。** 判定だけ合っていても届かないと意味が無い。"""

    def drop_on(self, window, label: str) -> list:
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent

        from hitofude.ui.note_list import NOTE_MIME

        sidebar = window._sidebar
        index = sidebar._find_label(label)
        assert index is not None, f"{label} の行が無い"
        rect = sidebar.visualRect(index)
        payload = QMimeData()
        payload.setData(NOTE_MIME, "捨てるノート.md".encode())
        got: list = []
        sidebar.note_trashed.connect(got.append)
        event = QDropEvent(
            QPointF(rect.center()),
            Qt.DropAction.MoveAction,
            payload,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        sidebar.dropEvent(event)
        return got

    def test_ゴミ箱の行に落とすと届く(self, opened) -> None:
        assert self.drop_on(opened, "ゴミ箱") == [Path("捨てるノート.md")]

    def test_お気に入りの行では届かない(self, opened) -> None:
        assert self.drop_on(opened, "お気に入り") == []
