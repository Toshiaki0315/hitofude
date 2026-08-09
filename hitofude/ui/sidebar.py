"""サイドバー（spec §5.1）。

すべて / お気に入り / ゴミ箱と、階層タグのツリー。

タグツリーの組み立ては純関数に分けてある。`/` 区切りの平坦なタグ一覧を
入れ子に直す処理は境界条件が多く、ウィジェット越しに検査しづらい。
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView, QWidget

from hitofude.core import tags as tag_utils
from hitofude.storage.index_db import TagCount
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.icons import Glyph, glyph_icon

ALL_LABEL = "すべて"
PINNED_LABEL = "お気に入り"
TRASH_LABEL = "ゴミ箱"
TAGS_LABEL = "タグ"

_FILTER_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class FilterKind(Enum):
    ALL = auto()
    PINNED = auto()
    TRASH = auto()
    TAG = auto()


_GLYPHS = {
    FilterKind.ALL: Glyph.ALL,
    FilterKind.PINNED: Glyph.PINNED,
    FilterKind.TRASH: Glyph.TRASH,
    FilterKind.TAG: Glyph.TAG,
}


@dataclass(frozen=True, slots=True)
class Filter:
    kind: FilterKind
    tag: str | None = None

    @property
    def label(self) -> str:
        match self.kind:
            case FilterKind.ALL:
                return ALL_LABEL
            case FilterKind.PINNED:
                return PINNED_LABEL
            case FilterKind.TRASH:
                return TRASH_LABEL
            case FilterKind.TAG:
                return f"#{self.tag}"


ALL = Filter(FilterKind.ALL)
PINNED = Filter(FilterKind.PINNED)
TRASH = Filter(FilterKind.TRASH)


@dataclass(frozen=True, slots=True)
class TagNode:
    tag: str
    count: int
    children: tuple["TagNode", ...] = field(default=())

    @property
    def label(self) -> str:
        return tag_utils.leaf(self.tag)


def build_tag_tree(counts: list[TagCount]) -> list[TagNode]:
    """平坦なタグ件数を入れ子に直す。

    索引側が祖先も含めて格納している（`index_db.upsert_note`）ので、
    ここでは親を作り足す必要はない。ただし外部で作られたデータや
    将来の変更に備え、親が欠けていても子を捨てないようにしてある。
    """
    known = {entry.tag: entry.count for entry in counts}
    children: dict[str, list[str]] = {tag: [] for tag in known}
    roots: list[str] = []

    for tag in sorted(known):
        parent = tag_utils.parent(tag)
        if parent is not None and parent in children:
            children[parent].append(tag)
        else:
            roots.append(tag)

    def build(tag: str) -> TagNode:
        return TagNode(
            tag=tag,
            count=known[tag],
            children=tuple(build(child) for child in children[tag]),
        )

    return [build(tag) for tag in roots]


class Sidebar(QTreeView):
    filter_changed = Signal(object)
    """選ばれた `Filter`。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme
        self._counts: list[TagCount] = []
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setFrameShape(QTreeView.Shape.NoFrame)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.set_tags([])
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.select(ALL)

    # ------------------------------------------------------------------ 構築

    def set_theme(self, theme: ThemeColors) -> None:
        """アイコンをテーマの色で描き直す。

        線で描いているので、色を変えるには作り直すしかない。項目ごと
        組み直すのが単純で、サイドバーの規模なら問題にならない。
        """
        self._theme = theme
        self.set_tags(self._counts)

    def set_tags(self, counts: list[TagCount]) -> None:
        """タグ一覧を差し替える。選択中の項目は可能なら保つ。"""
        self._counts = list(counts)
        keep = self.current_filter()
        self._model.clear()
        root = self._model.invisibleRootItem()

        color = self._theme.foreground
        for filter_ in (ALL, PINNED, TRASH):
            root.appendRow(_make_item(filter_.label, filter_, color))

        if counts:
            header = QStandardItem(glyph_icon(Glyph.TAG, color), TAGS_LABEL)
            header.setSelectable(False)
            header.setEditable(False)
            root.appendRow(header)
            for node in build_tag_tree(counts):
                header.appendRow(_make_tag_item(node, color))
            self.expandAll()

        if keep is not None:
            self.select(keep)

    # ------------------------------------------------------------------ 選択

    def current_filter(self) -> Filter | None:
        item = self._model.itemFromIndex(self.currentIndex())
        return item.data(_FILTER_ROLE) if item is not None else None

    def select(self, target: Filter) -> None:
        index = self._find(target)
        if index is not None:
            self.setCurrentIndex(index)

    def _find(self, target: Filter):
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            found = _search(item, target)
            if found is not None:
                return found.index()
        return None

    def _on_current_changed(self, current, _previous) -> None:
        item = self._model.itemFromIndex(current)
        if item is None:
            return
        target = item.data(_FILTER_ROLE)
        if target is not None:
            self.filter_changed.emit(target)


def _make_item(label: str, target: Filter, color: str) -> QStandardItem:
    # **アイコンは絵として付ける。** ラベルに記号を混ぜると、選択の判定や
    # タグ名の突き合わせに紛れ込む
    item = QStandardItem(glyph_icon(_GLYPHS[target.kind], color), label)
    item.setEditable(False)
    item.setData(target, _FILTER_ROLE)
    return item


def _make_tag_item(node: TagNode, color: str) -> QStandardItem:
    item = _make_item(f"{node.label}  {node.count}", Filter(FilterKind.TAG, node.tag), color)
    for child in node.children:
        item.appendRow(_make_tag_item(child, color))
    return item


def _search(item: QStandardItem, target: Filter) -> QStandardItem | None:
    if item.data(_FILTER_ROLE) == target:
        return item
    for row in range(item.rowCount()):
        found = _search(item.child(row), target)
        if found is not None:
            return found
    return None
