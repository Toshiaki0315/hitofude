"""サイドバー（spec §5.1）。

すべて / お気に入り / ゴミ箱と、階層タグのツリー。

タグツリーの組み立ては純関数に分けてある。`/` 区切りの平坦なタグ一覧を
入れ子に直す処理は境界条件が多く、ウィジェット越しに検査しづらい。
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView, QWidget

from hitofude.config import LineSpacing
from hitofude.core import tags as tag_utils
from hitofude.storage.index_db import TagCount
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.icons import Glyph, glyph_icon

ALL_LABEL = "すべて"
PINNED_LABEL = "お気に入り"
TRASH_LABEL = "ゴミ箱"

# 行の上下の余白（ユーザー指摘）。**文字の高さそのままでは詰まって見える。**
# 比べた相手（Claude Desktop）は 13px の文字に対して行の間隔が約 26px。
# こちらは 20px しかなく、字が上下でくっついていた。字送り（16px 前後）＋
# 上下 5px で 26px 前後になり、同じ落ち着きになる
ROW_PADDING = 5

# 環境設定の「行間」から引く余白。**px は設定に出さない**（文字サイズと
# 連れ立って効き方が変わる）ので、名前から実際の値をここで決める
_PADDINGS = {
    LineSpacing.TIGHT: 2,
    LineSpacing.NORMAL: ROW_PADDING,
    LineSpacing.RELAXED: 8,
}


def padding_for(spacing: LineSpacing) -> int:
    return _PADDINGS[spacing]


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
        self._row_padding = ROW_PADDING
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setFrameShape(QTreeView.Shape.NoFrame)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._apply()  # set_tags([]) は「変化なし」で素通りするので直接組む
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.select(ALL)

    # ------------------------------------------------------------------ 構築

    def set_line_spacing(self, spacing: LineSpacing) -> None:
        """行間を変える（環境設定）。**組み直して初めて効く**ので引き直す。"""
        padding = padding_for(spacing)
        if padding == self._row_padding:
            return
        self._row_padding = padding
        self._apply()

    def set_theme(self, theme: ThemeColors) -> None:
        """アイコンをテーマの色で描き直す。

        線で描いているので、色を変えるには作り直すしかない。項目ごと
        組み直すのが単純で、サイドバーの規模なら問題にならない。
        """
        self._theme = theme
        self._apply()

    def set_tags(self, counts: list[TagCount]) -> None:
        """タグ一覧を差し替える。選択中の項目は可能なら保つ。

        **変わっていなければ何もしない。** 自動保存（800ms）のたびに
        呼ばれるので、タグ集合が同じなら組み直し自体を省く。
        テーマや行間の変更は `_apply()` を直接呼ぶので、この早期 return に
        巻き込まれない。
        """
        counts = list(counts)
        if counts == self._counts:
            return
        self._counts = counts
        self._apply()

    def _apply(self) -> None:
        """今の状態（タグ・テーマ・行間）でツリーを組み直す。

        **組み直しの途中では通知しない。** 項目を作り直すと選択が先頭
        （「すべて」）に移るので、そのまま通知すると、ゴミ箱やタグを
        見ている最中に保存や復元が起きただけで一覧が「すべて」に
        切り替わってしまう（ユーザー報告の一歩手前で見つけた）。

        **選んでいたものが消えたときだけ通知する。** そのときは実際に
        見る対象が変わるので、黙って別のものを見せるほうが危ない。
        """
        keep = self.current_filter()

        self.blockSignals(True)
        try:
            self._rebuild(self._counts)
            if keep is not None:
                self.select(keep)
        finally:
            self.blockSignals(False)

        current = self.current_filter()
        if current is None:
            self.select(ALL)  # 選択が外れたまま置かない
        elif current != keep:
            self.filter_changed.emit(current)

    def _rebuild(self, counts: list[TagCount]) -> None:
        collapsed = self._collapsed_filters()
        self._model.clear()
        root = self._model.invisibleRootItem()

        color = self._theme.foreground
        height = _row_height(self, self._row_padding)
        for filter_ in (ALL, PINNED, TRASH):
            root.appendRow(_sized(_make_item(filter_.label, filter_, color), height))

        if counts:
            header = QStandardItem(glyph_icon(Glyph.TAG, color), TAGS_LABEL)
            header.setSelectable(False)
            header.setEditable(False)
            root.appendRow(_sized(header, height))
            for node in build_tag_tree(counts):
                root_item = _sized(_make_tag_item(node, color), height)
                _size_children(root_item, height)
                header.appendRow(root_item)
            # 既定は全部開く。**畳んであった枝だけ**畳み直す。
            # 開いた側を覚えると、新しく現れた枝が畳まれて見落とされる
            self.expandAll()
            for filter_ in collapsed:
                index = self._find(filter_)
                if index is not None:
                    self.setExpanded(index, False)

    def _collapsed_filters(self) -> set[Filter]:
        """畳まれているタグ枝。組み直しをまたいで畳みを保つために覚える。"""
        collapsed: set[Filter] = set()

        def walk(item: QStandardItem) -> None:
            for row in range(item.rowCount()):
                child = item.child(row)
                if child is None:
                    continue
                data = child.data(_FILTER_ROLE)
                if data is not None and child.rowCount() > 0 and not self.isExpanded(child.index()):
                    collapsed.add(data)
                walk(child)

        walk(self._model.invisibleRootItem())
        return collapsed

    # ------------------------------------------------------------------ 選択

    def filter_at(self, point) -> Filter | None:
        """その位置にある項目の `Filter`。無ければ `None`（G-3 の右クリック）。"""
        item = self._model.itemFromIndex(self.indexAt(point))
        return item.data(_FILTER_ROLE) if item is not None else None

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


def _sized(item: QStandardItem, height: int) -> QStandardItem:
    """行の高さを与える。幅は 0 のまま（列幅は view が決める）。"""
    item.setSizeHint(QSize(0, height))
    return item


def _size_children(item: QStandardItem, height: int) -> None:
    """入れ子のタグにも同じ高さを与える。"""
    for row in range(item.rowCount()):
        child = item.child(row)
        child.setSizeHint(QSize(0, height))
        _size_children(child, height)


def _row_height(widget: QWidget, padding: int = ROW_PADDING) -> int:
    """行の高さ。**字送りから決める**（`height()` ではない）。

    `QFontMetrics.height()` は字の高さで、行を積むときの送りは
    `lineSpacing()`。前者で組むと日本語のように背の高い字で詰まる
    （一覧のプレビューでも同じ間違いをして 2 行目が切れた）。
    """
    return QFontMetrics(widget.font()).lineSpacing() + padding * 2


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
