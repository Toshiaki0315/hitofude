"""ノート一覧と、その上のヘッダ（spec §5.1）。

新規ノートがメニューと `Cmd+N` からしか作れなかったので、**画面の中にも
入口を置く**。`EditorPane` と同じ形で、一覧をヘッダごと包む。

ここは入口を置くだけで、**ノートを作る仕事は持たない**。作るのは
`MainWindow`（vault と索引の両方に触る必要があるため）。
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hitofude.storage.index_db import SortOrder
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.format_toolbar import BAR_HEIGHT, BUTTON_RADIUS, BUTTON_SIZE, ICON_SIZE
from hitofude.ui.icons import TOOLBAR_SCALE, Glyph, glyph_icon
from hitofude.ui.note_list import NoteListView
from hitofude.ui.panes import NOTE_LIST_MIN_WIDTH

# ポップアップ用の三角の場所（C-3 の手直し）。**記号と重なる**ので確保する。
# 既定のボタン幅は 28px で、記号 13.5px を引くと三角に 14px しか残らず、
# 実機で重なって見えた（ユーザー報告）。
#
# 拡大して並べて選んだ: 14 は接触、20 は際どい、**26 で明確に離れる**
HEADER_MARGIN = round(6 * TOOLBAR_SCALE)

EMPTY_NOTICE = "ノートがありません。\n右上の ＋ で作れます。"

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
        # 記号だけでは何のボタンか分からない。ショートカットも案内する
        self._new.setToolTip("新規ノート（Cmd+N）")
        self._new.setAutoRaise(True)
        self._new.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new.clicked.connect(self.new_note_requested.emit)

        self._sort = QToolButton(self)
        self._sort.setToolTip("並び順")
        self._sort.setAutoRaise(True)
        self._sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # **本文側の書式ツールバーと同じ正方形にする**（ユーザー指摘）。
        # 文字＋三角の形は横に間延びし、三角が記号と重なることもあった
        for button in (self._sort, self._new):
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            # 押しても本文のキャレットを手放さない（書式ツールバーと同じ扱い）
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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

        # **本文側のツールバーと同じ高さにする**（ユーザー要望）。左右に並んで
        # 見えるので、高さが違うと段差になって目に付く。高さは入れ物で決め、
        # 記号は上下の真ん中に置く（上に張り付くと、ただ余白が空いて見える）
        self._header = QWidget(self)
        self._header.setFixedHeight(BAR_HEIGHT)
        header = QHBoxLayout(self._header)
        header.setContentsMargins(HEADER_MARGIN, 0, HEADER_MARGIN, 0)
        header.addWidget(self._sort, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._new, 0, Qt.AlignmentFlag.AlignVCenter)

        # 一覧の上に重ねる。差し替えではなく重ねるのは、一覧の幅や
        # スクロール位置をそのまま保つため（C-6）
        self._empty = QLabel(EMPTY_NOTICE, self._list)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.hide()
        self._list.model().modelReset.connect(self._sync_empty_notice)
        self._list.model().rowsInserted.connect(self._sync_empty_notice)
        self._list.model().rowsRemoved.connect(self._sync_empty_notice)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._list, 1)
        self._sync_empty_notice()

        self.set_theme(theme)

    def header_height(self) -> int:
        """上のバーの高さ。本文側のツールバーと同じ。"""
        return self._header.height()

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

    def empty_notice_visible(self) -> bool:
        return not self._empty.isHidden()

    def empty_notice_text(self) -> str:
        return self._empty.text()

    def set_empty_notice(self, text: str) -> None:
        """空のときの案内を差し替える。

        **何を見ているかで案内は変わる。** ゴミ箱で「＋ で作れます」は
        噛み合わない（作ったノートはゴミ箱に入らない）。何を出すかは
        絞り込みを持っている `MainWindow` が決める。
        """
        self._empty.setText(text)

    def _sync_empty_notice(self) -> None:
        """ノートが 0 件のときだけ案内を出す（C-6）。

        **絞り込んだ結果が 0 件でも出す。** 一覧が真っ白なのは同じで、
        次に何をすればよいか分からない。
        """
        empty = self._list.model().rowCount() == 0
        self._empty.setVisible(empty)
        if empty:
            self._empty.resize(self._list.viewport().size())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_empty_notice()

    def set_theme(self, theme: ThemeColors) -> None:
        self._list.set_theme(theme)
        # **本文側のツールバーと同じ見た目にする**（ユーザー要望）。同じバーに
        # 並ぶのに片方だけ枠が無いと、押せるものだと分かりにくい。丸みは
        # 向こうの値を引く（別々に書くと食い違う）。QSS は**ボタン全部に、
        # ボタンだけに**当てる——ペイン全体へ流すと一覧の配色まで上書きし、
        # 片方だけだと後から足したボタンが枠付きで浮く（実機で `⇅` だけ出た）
        self._sort.setIcon(glyph_icon(Glyph.SORT, theme.muted_foreground))
        self._new.setIcon(glyph_icon(Glyph.NEW_NOTE, theme.muted_foreground))
        style = (
            f"QToolButton {{ color: {theme.muted_foreground}; "
            f"border: 1px solid {theme.rule}; border-radius: {BUTTON_RADIUS}px; "
            f"padding: 2px 6px; }}"
            # **Qt の三角を消す。** 正方形に収めた絵の横に出ると、はみ出すか
            # 記号と重なる（過去のユーザー報告）
            f"QToolButton::menu-indicator {{ image: none; width: 0; }}"
        )
        for button in (self._new, self._sort):
            button.setStyleSheet(style)
        # **案内は一覧の背景の上に描く。** 透けるのに任せていたが、上のバーの
        # 高さを変えたら別の色（実測 #303032）で塗られた。何色の上に出るかは
        # ここで決めておく
        self._empty.setStyleSheet(
            f"QLabel {{ background: {theme.background}; color: {theme.muted_foreground}; }}"
        )
