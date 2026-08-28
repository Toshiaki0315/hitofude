"""サイドバー（spec §5.1）。

すべて / お気に入り / ゴミ箱と、階層タグのツリー。

タグツリーの組み立ては純関数に分けてある。`/` 区切りの平坦なタグ一覧を
入れ子に直す処理は境界条件が多く、ウィジェット越しに検査しづらい。
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QPainter,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QWidget,
)

from hitofude.config import LineSpacing
from hitofude.core import tags as tag_utils
from hitofude.storage.index_db import ROOT_FOLDER, FolderCount, TagCount
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.icons import Glyph, glyph_icon
from hitofude.ui.note_list import dropped_note

ALL_LABEL = "すべて"
PINNED_LABEL = "お気に入り"
TRASH_LABEL = "ゴミ箱"

# 行の上下の余白（ユーザー指摘）。**文字の高さそのままでは詰まって見える。**
# 比べた相手（Claude Desktop）は 13px の文字に対して行の間隔が約 26px。
# こちらは 20px しかなく、字が上下でくっついていた。字送り（16px 前後）＋
# 上下 5px で 26px 前後になり、同じ落ち着きになる
ROW_PADDING = 5

# 設定の「行間」から引く余白。**px は設定に出さない**（文字サイズと
# 連れ立って効き方が変わる）ので、名前から実際の値をここで決める
_PADDINGS = {
    LineSpacing.TIGHT: 2,
    LineSpacing.NORMAL: ROW_PADDING,
    LineSpacing.RELAXED: 8,
}


def padding_for(spacing: LineSpacing) -> int:
    return _PADDINGS[spacing]


TAGS_LABEL = "タグ"
FOLDERS_LABEL = "フォルダ"
SEARCHES_LABEL = "検索"
ROOT_FOLDER_LABEL = "直下"

_FILTER_ROLE = int(Qt.ItemDataRole.UserRole) + 1

COUNT_ROLE = _FILTER_ROLE + 1
"""その行の件数。**名前とは別に持つ**（ユーザー要望 2026-08-22）。

`テスト２  2` のように名前へ混ぜ込むと、名前が数字で終わったときに
見分けが付かないうえ、描く側でも切り分けられない。
"""

# 名前と件数のあいだ。詰めると 1 つの語に見える
COUNT_GAP = 10


class FilterKind(Enum):
    ALL = auto()
    PINNED = auto()
    TRASH = auto()
    TAG = auto()
    FOLDER = auto()
    """手で作ったサブフォルダ（K-2）。"""

    SEARCH = auto()
    """保存した検索（K-4）。名前を付けた検索式で束ねる。"""


_GLYPHS = {
    FilterKind.ALL: Glyph.ALL,
    FilterKind.PINNED: Glyph.PINNED,
    FilterKind.TRASH: Glyph.TRASH,
    FilterKind.TAG: Glyph.TAG,
    FilterKind.FOLDER: Glyph.FOLDER,
    FilterKind.SEARCH: Glyph.SEARCH,
}


@dataclass(frozen=True, slots=True)
class Filter:
    kind: FilterKind
    tag: str | None = None
    folder: str | None = None
    """`FilterKind.FOLDER` のときの相対パス（`仕事/2026`）。"""

    name: str | None = None
    """`FilterKind.SEARCH` のときの表示名（K-4）。"""

    query: str | None = None
    """`FilterKind.SEARCH` のときの検索式（`#仕事 after:2026-08-01`）。"""

    def __post_init__(self) -> None:
        # 中身の無い FOLDER/TAG は、ラベルが「None/」になり一覧が黙って
        # 空になる（コードレビュー指摘）。作る時点で大声で失敗させる
        if self.kind is FilterKind.FOLDER and not self.folder:
            raise ValueError("FOLDER のフィルタには folder が要る")
        if self.kind is FilterKind.TAG and not self.tag:
            raise ValueError("TAG のフィルタには tag が要る")
        if self.kind is FilterKind.SEARCH and (not self.name or self.query is None):
            raise ValueError("SEARCH のフィルタには name と query が要る")

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
            case FilterKind.SEARCH:
                return self.name or ""
            case FilterKind.FOLDER:
                # ルートは記号（"."）を見せず「直下」と読ませる
                if self.folder == ROOT_FOLDER:
                    return ROOT_FOLDER_LABEL
                return f"{self.folder}/"


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


class SidebarItemDelegate(QStyledItemDelegate):
    """件数を右端に薄く描く（ユーザー要望 2026-08-22）。

    **位置で分ける。** 括弧で囲む手もあるが、同じ色・同じ並びのままなので
    `日報 (2)` のような名前には効かない。Finder や Mail と同じく、名前は
    左・件数は右端に置く。狭いときに削るのは**名前のほう**（件数が消えると
    数える手段が無くなる）。
    """

    def __init__(self, theme: ThemeColors = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        count = index.data(COUNT_ROLE)
        if count is None:
            super().paint(painter, option, index)
            return

        text = str(count)
        reserved = QFontMetrics(option.font).horizontalAdvance(text) + COUNT_GAP

        # 名前は右端の手前で止める。**背景と選択の色は元の幅のまま**
        # （幅を削って渡すと、右端に塗り残しの帯ができる）
        # **背景と選択の色は元の幅で塗る**（狭めた幅で塗ると右端に帯が残る）。
        # ここで `super().paint()` は使えない。あちらは中で
        # `initStyleOption()` をやり直すので、消したはずの名前が元の幅で
        # 描き直され、下に残ってしまう（数字に重なって見えていた）
        style = option.widget.style() if option.widget is not None else QApplication.style()
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, background, painter, option.widget
        )

        # 名前は数字のぶんだけ狭い幅で描かせる。**幅を渡して Qt に省略させる**
        # （自分で `elidedText` すると、字下げ・アイコン・字間の余白を数え
        # 落として数字に乗る。実際に長いタグ名で重なった）
        trimmed = QStyleOptionViewItem(option)
        trimmed.rect = option.rect.adjusted(0, 0, -reserved, 0)
        super().paint(painter, trimmed, index)

        painter.save()
        painter.setFont(option.font)
        painter.setPen(QColor(self._theme.muted_foreground))
        painter.drawText(
            option.rect.adjusted(0, 0, -COUNT_GAP // 2, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.restore()


class Sidebar(QTreeView):
    filter_changed = Signal(object)
    """選ばれた `Filter`。"""

    note_dropped = Signal(object, str)
    """落とされたノートの相対 `Path` と、移動先のフォルダ（直下は空文字）。

    **移すのは受け手（MainWindow）の仕事。** サイドバーは vault も索引も
    知らない（一覧が `files_dropped` で知らせるのと同じ分担）。"""

    note_trashed = Signal(object)
    """ゴミ箱の行へ落とされた（ユーザー要望 2026-08-28）。

    **フォルダとは分ける。** 行き先で意味が変わるうえ、フォルダ名に
    ゴミ箱を混ぜると `.trash` という名前のフォルダと見分けが付かない。
    """

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme
        self._counts: list[TagCount] = []
        self._folders: list[FolderCount] = []
        self._drop_index: QPersistentModelIndex | None = None
        self._saved_searches: list[tuple[str, str]] = []
        self._row_padding = ROW_PADDING
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self._delegate = SidebarItemDelegate(theme, self)
        self.setItemDelegate(self._delegate)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setFrameShape(QTreeView.Shape.NoFrame)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._apply()  # set_tags([]) は「変化なし」で素通りするので直接組む
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.select(ALL)
        # 一覧の行を落として移せるようにする（ユーザー要望）。
        # 受けるだけ（サイドバーの中身はドラッグしない）
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeView.DragDropMode.DropOnly)

    # ------------------------------------------------------------------ 構築

    def set_line_spacing(self, spacing: LineSpacing) -> None:
        """行間を変える（設定）。**組み直して初めて効く**ので引き直す。"""
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
        self._delegate.set_theme(theme)
        self._apply()

    def set_folders(self, counts: list["FolderCount"]) -> None:
        """フォルダ一覧を差し替える（K-2）。タグと同じ作法。

        **変わっていなければ何もしない**（保存のたびに呼ばれる）。
        """
        counts = list(counts)
        if counts == self._folders:
            return
        self._folders = counts
        self._apply()

    def set_saved_searches(self, entries: list[tuple[str, str]]) -> None:
        """保存した検索（K-4）。(名前, 検索式) の並び。同じなら何もしない。"""
        if entries == self._saved_searches:
            return
        self._saved_searches = list(entries)
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
        self._drop_index = None  # 行ごと作り直すので、塗る相手も持ち越さない
        self._model.clear()
        root = self._model.invisibleRootItem()

        color = self._theme.foreground
        height = _row_height(self, self._row_padding)
        for filter_ in (ALL, PINNED, TRASH):
            root.appendRow(_sized(_make_item(filter_.label, filter_, color), height))

        if self._folders:
            # **入れ物が先、ラベルが後。** 場所を探すほうが先に目に入る。
            # 見出しは飾りではなく**直下そのもの**（ユーザー要望）。
            # 見出しと「直下」で 2 行使うのに、見出しは押しても何も
            # 起きなかった。1 つにすると、その下のフォルダが Finder と
            # 同じく 1 段だけ下がって見える
            children = [count for count in self._folders if count.folder != ROOT_FOLDER]
            here = next((count for count in self._folders if count.folder == ROOT_FOLDER), None)
            folders = _make_item(
                FOLDERS_LABEL, Filter(FilterKind.FOLDER, folder=ROOT_FOLDER), color
            )
            if here is not None:
                folders.setData(here.count, COUNT_ROLE)
            root.appendRow(_sized(folders, height))
            for item in _folder_items(children, color, height):
                folders.appendRow(item)

        if self._saved_searches:
            searches = QStandardItem(glyph_icon(Glyph.SEARCH, color), SEARCHES_LABEL)
            searches.setSelectable(False)
            searches.setEditable(False)
            root.appendRow(_sized(searches, height))
            for name, query in self._saved_searches:
                searches.appendRow(
                    _sized(
                        _make_item(name, Filter(FilterKind.SEARCH, name=name, query=query), color),
                        height,
                    )
                )

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
        # 開いた側を覚えると、新しく現れた枝が畳まれて見落とされる。
        # **タグの if の外**に置く: 中に置くと、タグの無い vault で
        # フォルダツリーが畳まれたまま・畳み直しも効かない
        # （コードレビュー指摘）
        self.expandAll()
        for entry in collapsed:
            index = self._find(entry) if isinstance(entry, Filter) else self._find_label(entry)
            if index is not None:
                self.setExpanded(index, False)

    def _collapsed_filters(self) -> set[Filter | str]:
        """畳まれている枝。組み直しをまたいで畳みを保つために覚える。

        枝はフィルタ（タグ・フォルダ）で、見出し行（「フォルダ」「タグ」。
        フィルタを持たない）は**文言**で覚える。見出しを対象にしないと、
        畳んだ見出しが組み直しのたびに開き直される。
        """
        collapsed: set[Filter | str] = set()

        def walk(item: QStandardItem) -> None:
            for row in range(item.rowCount()):
                child = item.child(row)
                if child is None:
                    continue
                if child.rowCount() > 0 and not self.isExpanded(child.index()):
                    data = child.data(_FILTER_ROLE)
                    collapsed.add(data if data is not None else child.text())
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

    # ------------------------------------------------- ドラッグ＆ドロップ

    _DROP_KINDS = frozenset({FilterKind.FOLDER, FilterKind.TRASH})
    """落とせる行。**フォルダとゴミ箱だけ。**

    タグや「すべて」「お気に入り」には行き先が無い（タグは本文の
    `#タグ` が真実で、移して付くものではない）。
    """

    def drop_kind(self, target: Filter | None) -> bool:
        """その行に落とせるか。純粋な判定なので試験から直に呼べる。"""
        return target is not None and target.kind in self._DROP_KINDS

    def _drop_target(self, position) -> Filter | None:
        """その位置で受けられる行。受けられないなら None。"""
        index = self.indexAt(position)
        if not index.isValid():
            return None
        target = index.data(_FILTER_ROLE)
        return target if self.drop_kind(target) else None

    def _drop_folder(self, position) -> str | None:
        """その位置で受けられるフォルダ。受けられないなら None。"""
        target = self._drop_target(position)
        if target is None or target.kind is not FilterKind.FOLDER:
            return None
        return "" if target.folder == ROOT_FOLDER else (target.folder or "")

    def _acceptable(self, event) -> bool:
        if dropped_note(event.mimeData()) is None:
            return False
        return self._drop_target(event.position().toPoint()) is not None

    def drop_target(self) -> Filter | None:
        """今ドラッグが乗っているフォルダ。乗っていなければ None。"""
        if self._drop_index is None or not self._drop_index.isValid():
            return None
        return self._model.itemFromIndex(QModelIndex(self._drop_index)).data(_FILTER_ROLE)

    def _mark_drop(self, position) -> None:
        """落とす先の行を塗る（ユーザー要望）。

        **受けるかどうかは矢印の形でしか分からなかった。** 行の高さは
        26px ほどしかないので、どのフォルダに入るかは落とすまで分からず、
        ひとつ上のフォルダへ入ってしまう。Finder と同じく入る先を塗る。
        """
        index = self.indexAt(position) if position is not None else None
        if index is not None and not self._acceptable_index(index):
            index = None
        if index is not None and self._drop_index is not None and index == self._drop_index:
            return

        self._paint_drop(self._drop_index, marked=False)
        self._drop_index = QPersistentModelIndex(index) if index is not None else None
        self._paint_drop(self._drop_index, marked=True)
        # **色の付いた行を 2 つにしない**（ユーザー要望 2026-08-22）。今いる
        # フォルダの帯が残ったままだと、どちらが行き先か読み取れない
        if index is None:
            self._show_selection()
        else:
            self._hide_selection()

    def _hide_selection(self) -> None:
        """運んでいる間だけ帯を消す。

        **`currentIndex` は動かさない。** 動かすと `filter_changed` が飛び、
        運んでいる途中で一覧が入れ替わってしまう。消すのは選択（見た目）だけ。
        """
        self.selectionModel().clearSelection()

    def _show_selection(self) -> None:
        """帯を戻す。やめただけなら絞り込みは変わっていないのだから、
        今いるフォルダに戻るのが正しい。"""
        index = self.currentIndex()
        if index.isValid():
            self.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )

    def _acceptable_index(self, index) -> bool:
        """その行を塗るか。**受け入れの判定と同じ口を使う**——別に書くと、
        落とせる行が増えたときに「受けるのに塗られない」がまた起きる
        （ゴミ箱を足したとき実際に踏んだ。ユーザー報告 2026-08-28）。
        """
        target = index.data(_FILTER_ROLE) if index.isValid() else None
        return self.drop_kind(target)

    def _paint_drop(self, index, *, marked: bool) -> None:
        # 組み直し（refresh）を挟むと行そのものが消えている
        if index is None or not index.isValid():
            return
        item = self._model.itemFromIndex(QModelIndex(index))
        if item is None:
            return
        item.setBackground(QBrush(QColor(self._theme.selection_background)) if marked else QBrush())

    def dragEnterEvent(self, event) -> None:
        """入口では**中身だけ**を見る（ユーザー報告 2026-08-21）。

        ここで断ると、**Qt はそれ以降 `dragMoveEvent` を送ってこない**。
        位置まで見ていたため、サイドバーに入った場所がフォルダの行で
        なければ（タグの上でも、ツリーの下の余白でも）そこで拒否され、
        そのままフォルダまで運んでも受けられなかった。一覧の下の行ほど
        斜めに入って入口が下になるので、**特定のノートだけ動かせない**
        ように見えていた。

        どのフォルダに入るかは `dragMoveEvent` と `dropEvent` が見る。
        """
        if dropped_note(event.mimeData()) is None:
            event.ignore()
            return
        self._mark_drop(event.position().toPoint())
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._acceptable(event):
            self._mark_drop(event.position().toPoint())
            event.acceptProposedAction()
            return
        self._mark_drop(None)  # 受けない行へ滑らせたら塗りも消す
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        """**落とさずに戻したときに塗りを残さない。**"""
        self._mark_drop(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        relative = dropped_note(event.mimeData())
        target = self._drop_target(event.position().toPoint())
        self._mark_drop(None)
        if relative is None or target is None:
            event.ignore()
            return
        event.acceptProposedAction()
        if target.kind is FilterKind.TRASH:
            self.note_trashed.emit(relative)
            return
        self.note_dropped.emit(
            relative, "" if target.folder == ROOT_FOLDER else (target.folder or "")
        )

    def _find_label(self, label: str):
        """文言で行を探す（フィルタを持たない見出し行用）。"""
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None and item.text() == label:
                return item.index()
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


def _folder_items(counts: list["FolderCount"], color: str, height: int) -> list[QStandardItem]:
    """フォルダを入れ子に組む。

    索引は `仕事` と `仕事/2026` のように**全部の階層**を返すので、
    親の下に子を差し込むだけでよい（タグツリーのように組み直さない）。

    **ルート（直下）はここに来ない。** 見出し「フォルダ」がその役を担う。
    """
    items: dict[str, QStandardItem] = {}
    roots: list[QStandardItem] = []
    # folder_tree() が名前順で返す（親が先）。並びの契約はあちらが持つ
    for count in counts:
        item = _make_item(count.label, Filter(FilterKind.FOLDER, folder=count.folder), color)
        item.setData(count.count, COUNT_ROLE)
        item = _sized(item, height)
        items[count.folder] = item

        parent = items.get(count.folder.rsplit("/", 1)[0]) if "/" in count.folder else None
        if parent is not None:
            parent.appendRow(item)
        else:
            roots.append(item)
    return roots


def _make_tag_item(node: TagNode, color: str) -> QStandardItem:
    item = _make_item(node.label, Filter(FilterKind.TAG, node.tag), color)
    item.setData(node.count, COUNT_ROLE)
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
