"""サイドバーのテスト（タスク 5-4 / spec §5.1）。"""

import pytest

from hitofude.storage.index_db import TagCount
from hitofude.ui.sidebar import (
    ALL,
    ALL_LABEL,
    PINNED,
    TAGS_LABEL,
    TRASH,
    Filter,
    FilterKind,
    Sidebar,
    build_tag_tree,
)

pytestmark = pytest.mark.gui


def counts(*pairs: tuple[str, int]) -> list[TagCount]:
    return [TagCount(tag=tag, count=count) for tag, count in pairs]


class TestBuildTagTree:
    def test_平坦なタグはそのまま根になる(self) -> None:
        nodes = build_tag_tree(counts(("work", 2), ("private", 1)))
        assert [node.tag for node in nodes] == ["private", "work"]

    def test_階層タグは入れ子になる(self) -> None:
        nodes = build_tag_tree(counts(("work", 2), ("work/会議", 1), ("work/企画", 1)))
        assert len(nodes) == 1
        assert nodes[0].tag == "work"
        assert [child.tag for child in nodes[0].children] == ["work/企画", "work/会議"]

    def test_3階層も組める(self) -> None:
        nodes = build_tag_tree(counts(("a", 1), ("a/b", 1), ("a/b/c", 1)))
        assert nodes[0].children[0].children[0].tag == "a/b/c"

    def test_ラベルは末端の名前(self) -> None:
        nodes = build_tag_tree(counts(("work", 1), ("work/会議", 1)))
        assert nodes[0].children[0].label == "会議"

    def test_親が欠けていても子を捨てない(self) -> None:
        """索引側が祖先も入れる約束だが、欠けても表示から消えないこと。"""
        nodes = build_tag_tree(counts(("work/会議", 1)))
        assert [node.tag for node in nodes] == ["work/会議"]

    def test_空なら空(self) -> None:
        assert build_tag_tree([]) == []


class TestSidebar:
    @pytest.fixture
    def sidebar(self, qtbot) -> Sidebar:
        widget = Sidebar()
        qtbot.addWidget(widget)
        widget.show()
        return widget

    def test_固定の3項目がある(self, sidebar) -> None:
        model = sidebar.model()
        labels = [model.item(row).text() for row in range(model.rowCount())]
        assert labels[:3] == ["すべて", "お気に入り", "ゴミ箱"]

    def test_初期選択はすべて(self, sidebar) -> None:
        assert sidebar.current_filter() == ALL

    def test_タグを表示する(self, sidebar) -> None:
        sidebar.set_tags(counts(("work", 2), ("work/会議", 1)))
        model = sidebar.model()
        header = model.item(model.rowCount() - 1)
        assert header.text() == "タグ"
        assert header.rowCount() == 1
        assert "work" in header.child(0).text()

    def test_件数を表示する(self, sidebar) -> None:
        sidebar.set_tags(counts(("work", 7)))
        model = sidebar.model()
        header = model.item(model.rowCount() - 1)
        assert "7" in header.child(0).text()

    def test_タグが無ければ見出しも出さない(self, sidebar) -> None:
        sidebar.set_tags([])
        model = sidebar.model()
        labels = [model.item(row).text() for row in range(model.rowCount())]
        assert "タグ" not in labels

    @pytest.mark.parametrize("target", [ALL, PINNED, TRASH])
    def test_選ぶとシグナルが出る(self, sidebar, qtbot, target: Filter) -> None:
        sidebar.select(ALL)
        with qtbot.waitSignal(sidebar.filter_changed, timeout=1000) as blocker:
            sidebar.select(TRASH if target == ALL else target)
        assert isinstance(blocker.args[0], Filter)

    def test_タグを選べる(self, sidebar, qtbot) -> None:
        sidebar.set_tags(counts(("work", 1), ("work/会議", 1)))
        target = Filter(FilterKind.TAG, "work/会議")
        with qtbot.waitSignal(sidebar.filter_changed, timeout=1000) as blocker:
            sidebar.select(target)
        assert blocker.args[0] == target

    def test_タグを更新しても選択が残る(self, sidebar) -> None:
        """外部変更で索引が更新されるたびに選択が飛ぶと使えない。"""
        sidebar.set_tags(counts(("work", 1), ("private", 1)))
        sidebar.select(Filter(FilterKind.TAG, "work"))
        sidebar.set_tags(counts(("work", 2), ("private", 1)))
        assert sidebar.current_filter() == Filter(FilterKind.TAG, "work")

    def test_消えたタグを選んでいたら選択は移らない(self, sidebar) -> None:
        sidebar.set_tags(counts(("work", 1)))
        sidebar.select(Filter(FilterKind.TAG, "work"))
        sidebar.set_tags(counts(("private", 1)))
        assert sidebar.current_filter() != Filter(FilterKind.TAG, "work")

    def test_見出しは選択できない(self, sidebar) -> None:
        sidebar.set_tags(counts(("work", 1)))
        model = sidebar.model()
        assert model.item(model.rowCount() - 1).isSelectable() is False


class TestFilterLabel:
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            (ALL, "すべて"),
            (PINNED, "お気に入り"),
            (TRASH, "ゴミ箱"),
            (Filter(FilterKind.TAG, "work/会議"), "#work/会議"),
        ],
    )
    def test_表示名(self, target: Filter, expected: str) -> None:
        assert target.label == expected


@pytest.fixture
def sidebar(qtbot) -> Sidebar:
    widget = Sidebar()
    qtbot.addWidget(widget)
    return widget


class TestIcons:
    """項目の左にアイコンを出す（ユーザー要望）。

    テーマの色で描くので、切り替えたら描き直す必要がある。
    """

    def counts(self):
        from hitofude.storage.index_db import TagCount

        return [TagCount(tag="仕事", count=3), TagCount(tag="仕事/会議", count=1)]

    def item_for(self, sidebar, target):
        index = sidebar._find(target)
        return sidebar._model.itemFromIndex(index)

    @pytest.mark.parametrize("target", [ALL, PINNED, TRASH])
    def test_固定の項目に付く(self, sidebar, target) -> None:
        assert not self.item_for(sidebar, target).icon().isNull()

    def test_タグの見出しにも付く(self, sidebar) -> None:
        sidebar.set_tags(self.counts())
        header = sidebar._model.item(3)
        assert header.text() == TAGS_LABEL
        assert not header.icon().isNull()

    def test_タグの項目にも付く(self, sidebar) -> None:
        sidebar.set_tags(self.counts())
        item = self.item_for(sidebar, Filter(FilterKind.TAG, "仕事"))
        assert not item.icon().isNull()

    def test_種類ごとに違う(self, sidebar) -> None:
        from PySide6.QtCore import QSize

        seen = set()
        for target in (ALL, PINNED, TRASH):
            image = self.item_for(sidebar, target).icon().pixmap(QSize(32, 32)).toImage()
            seen.add(bytes(image.constBits()))
        assert len(seen) == 3

    def test_テーマの色で描かれる(self, sidebar) -> None:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor

        from hitofude.theme import DARK

        sidebar.set_theme(DARK)
        image = self.item_for(sidebar, ALL).icon().pixmap(QSize(32, 32)).toImage()
        drawn = {
            QColor(image.pixelColor(x, y)).name()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 128
        }
        assert drawn == {DARK.foreground.lower()}

    def test_テーマを変えると描き直す(self, sidebar) -> None:
        from PySide6.QtCore import QSize

        from hitofude.theme import DARK, LIGHT

        sidebar.set_theme(LIGHT)
        light = bytes(
            self.item_for(sidebar, ALL).icon().pixmap(QSize(32, 32)).toImage().constBits()
        )
        sidebar.set_theme(DARK)
        dark = bytes(self.item_for(sidebar, ALL).icon().pixmap(QSize(32, 32)).toImage().constBits())
        assert light != dark

    def test_タグを入れ替えても残る(self, sidebar) -> None:
        """一覧の再構築でアイコンが消えない。"""
        sidebar.set_tags(self.counts())
        sidebar.set_tags([])
        assert not self.item_for(sidebar, ALL).icon().isNull()

    def test_文字は変えない(self, sidebar) -> None:
        """アイコンは絵として付ける。ラベルに記号を混ぜない。"""
        assert self.item_for(sidebar, ALL).text() == ALL_LABEL
