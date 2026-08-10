"""ノート一覧と、その上のヘッダ（spec §5.1）。

新規ノートがメニューと `Cmd+N` からしか作れなかったので、**画面の中にも
入口を置く**。`EditorPane` と同じ形で、一覧をヘッダごと包む。

ここは入口を置くだけで、**ノートを作る仕事は持たない**。作るのは
`MainWindow`（vault と索引の両方に触る必要があるため）。
"""

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFontMetricsF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hitofude.storage.index_db import SortOrder
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.note_list import NoteListView
from hitofude.ui.panes import NOTE_LIST_MIN_WIDTH

NEW_NOTE_GLYPH = "＋"
SORT_GLYPH = "⇅"
# ポップアップ用の三角の場所（C-3 の手直し）。**記号と重なる**ので確保する。
# 既定のボタン幅は 28px で、記号 13.5px を引くと三角に 14px しか残らず、
# 実機で重なって見えた（ユーザー報告）。
#
# 拡大して並べて選んだ: 14 は接触、20 は際どい、**26 で明確に離れる**
SORT_INDICATOR_ROOM = 26
HEADER_MARGIN = 6

# 並び順の選択肢（C-3）。**設定ダイアログには置かない。** 並び替えは
# 「今そうしたい」操作で、一度決めて忘れる設定とは性質が違う
SORT_LABELS = {
    SortOrder.MODIFIED: "更新の新しい順",
    SortOrder.CREATED: "作成の新しい順",
    SortOrder.TITLE: "名前順",
}


class NoteListPane(QWidget):
    new_note_requested = Signal()
    sort_order_changed = Signal(object)
    """並び順が選ばれた（`SortOrder`）。覚えるのは `MainWindow` の仕事。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self.setMinimumWidth(NOTE_LIST_MIN_WIDTH)

        self._list = NoteListView(theme=theme)
        self._new = QToolButton(self)
        self._new.setText(NEW_NOTE_GLYPH)
        # 記号だけでは何のボタンか分からない。ショートカットも案内する
        self._new.setToolTip("新規ノート（Cmd+N）")
        self._new.setAutoRaise(True)
        self._new.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new.clicked.connect(self.new_note_requested.emit)

        self._sort = QToolButton(self)
        self._sort.setText(SORT_GLYPH)
        self._sort.setToolTip("並び順")
        self._sort.setAutoRaise(True)
        self._sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        glyph = QFontMetricsF(self._sort.font()).horizontalAdvance(SORT_GLYPH)
        # 切り捨てると 1px 足りずに重なることがある（実測 31.5 → 31）
        self._sort.setMinimumWidth(math.ceil(glyph + SORT_INDICATOR_ROOM))
        menu = QMenu(self._sort)
        self._sort_actions: dict[SortOrder, QAction] = {}
        for order, label in SORT_LABELS.items():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setData(order)
            action.triggered.connect(lambda _=False, o=order: self._choose_sort(o))
            self._sort_actions[order] = action
        self._sort.setMenu(menu)
        self._sort_order = SortOrder.MODIFIED
        self.set_sort_order(self._sort_order)

        header = QHBoxLayout()
        header.setContentsMargins(HEADER_MARGIN, HEADER_MARGIN, HEADER_MARGIN, 0)
        header.addWidget(self._sort)
        header.addStretch(1)
        header.addWidget(self._new)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self._list, 1)

        self.set_theme(theme)

    @property
    def note_list(self) -> NoteListView:
        return self._list

    @property
    def new_button(self) -> QToolButton:
        return self._new

    @property
    def sort_button(self) -> QToolButton:
        return self._sort

    def sort_order(self) -> SortOrder:
        return self._sort_order

    def set_sort_order(self, order: SortOrder) -> None:
        """今の並びを覚えて印を付け直す。**知らせは出さない**（読み込み用）。"""
        self._sort_order = order
        for candidate, action in self._sort_actions.items():
            action.setChecked(candidate is order)

    def _choose_sort(self, order: SortOrder) -> None:
        self.set_sort_order(order)
        self.sort_order_changed.emit(order)

    def set_theme(self, theme: ThemeColors) -> None:
        self._list.set_theme(theme)
        # ボタンだけに当てる。ペイン全体へ流すと一覧の配色まで上書きしてしまう
        self._new.setStyleSheet(f"QToolButton {{ color: {theme.muted_foreground}; border: none; }}")
