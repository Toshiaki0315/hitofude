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

    def test_ふつうの一覧から消える(self, opened) -> None:
        """落としたあとはゴミ箱で絞られるので、**「すべて」へ戻して見る。**"""
        from hitofude.ui.sidebar import Filter, FilterKind

        opened._on_note_trashed(Path("捨てるノート.md"))
        opened.set_filter(Filter(FilterKind.ALL))
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


class TestSameAsFolderMove:
    """**フォルダへ移すのと同じ動き**にする（ユーザー要望 2026-08-28）。

    ドラッグ中に行が塗られず、落としたあとも画面が動かないので、
    「ゴミ箱に入ったのか分からない」と報告された。フォルダへの移動は
    ①落とす先を塗る ②行き先で絞る（左の選択も動く）③知らせる、の
    3 つを揃えている。
    """

    def test_ドラッグ中にゴミ箱の行を塗る(self, opened) -> None:
        """**これが見えないと、受けるかどうかが矢印でしか分からない。**"""
        sidebar = opened._sidebar
        index = sidebar._find_label("ゴミ箱")
        assert index is not None
        assert sidebar._acceptable_index(index) is True

    def test_フォルダの行は今までどおり塗る(self, opened) -> None:
        """フォルダは入れ子の行なので、フィルタで引く（見出しの直下ではない）。"""
        from hitofude.ui.sidebar import Filter, FilterKind

        sidebar = opened._sidebar
        opened._notes.move_note_to(opened._vault.root / "残すノート.md", "箱")
        index = sidebar._find(Filter(FilterKind.FOLDER, folder="箱"))
        assert index is not None
        assert sidebar._acceptable_index(index) is True

    def test_お気に入りの行は塗らない(self, opened) -> None:
        sidebar = opened._sidebar
        index = sidebar._find_label("お気に入り")
        assert index is not None
        assert sidebar._acceptable_index(index) is False

    def test_落としたらゴミ箱で絞る(self, opened) -> None:
        """行き先を見せる（フォルダ移動と同じ理屈。移したものが画面から消える）。"""
        from hitofude.ui.sidebar import FilterKind

        opened._on_note_trashed(Path("捨てるノート.md"))
        assert opened.filter.kind is FilterKind.TRASH

    def test_左の選択も動く(self, opened) -> None:
        """一覧だけ変わると、今どれで絞っているのか分からない。"""
        from hitofude.ui.sidebar import FilterKind

        opened._on_note_trashed(Path("捨てるノート.md"))
        assert opened._sidebar.current_filter().kind is FilterKind.TRASH

    def test_知らせる(self, opened) -> None:
        opened._on_note_trashed(Path("捨てるノート.md"))
        assert "ゴミ箱" in opened.notice()

    def test_捨てられなければ動かない(self, opened) -> None:
        """**お気に入りは捨てない。** 捨てていないのに画面だけ動かさない。"""
        from hitofude.ui.sidebar import FilterKind

        opened._notes.toggle_pin(opened._vault.root / "捨てるノート.md")
        opened._on_note_trashed(Path("捨てるノート.md"))
        assert opened.filter.kind is not FilterKind.TRASH
