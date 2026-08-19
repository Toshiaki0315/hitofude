"""見出しの一覧を本文の横に出す（提案 5）。

`Cmd+R` のパレットは「飛んだら閉じる」道具で、**長い文書を見渡しながら
書く**用途には向かない。そばに出したままにできるようにする。

見出しの取り出しは `core/outline.py`（既にある）。ここは出す側だけで、
**エディタも vault も知らない**。押されたら行番号を知らせるところまで。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from hitofude.core.outline import Heading
from hitofude.theme import LIGHT, ThemeColors

OUTLINE_MIN_WIDTH = 160
"""これより狭いと見出しが読めない（`sidebar` と同じ考え方）。"""

EMPTY_NOTICE = "見出しがありません。\n`#` で書くとここに並びます。"

# 階層 1 段ぶんの字下げ。**深さを数字で出さない**（読み取りにくい。
# `Cmd+R` のパレットと同じ作法）
INDENT = "　"


class OutlinePane(QWidget):
    heading_activated = Signal(int)
    """押された見出しの行番号（0 始まり）。**飛ぶのは呼び出し側**。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme
        self._headings: list[Heading] = []

        self._list = QListWidget(self)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(self._on_clicked)

        self._empty = QLabel(EMPTY_NOTICE, self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._empty, 1)

        self.setMinimumWidth(OUTLINE_MIN_WIDTH)
        self.set_theme(theme)
        self.set_headings([])

    # ------------------------------------------------------------------ 中身

    def set_headings(self, headings: list[Heading]) -> None:
        """見出しを差し替える。**同じなら何もしない。**

        打つたびに呼ばれるので、作り直すと選択も位置も飛ぶ。
        """
        if headings == self._headings:
            return
        self._headings = list(headings)

        self._list.clear()
        for found in headings:
            item = QListWidgetItem(INDENT * (found.level - 1) + found.text)
            item.setToolTip(found.text)
            self._list.addItem(item)

        self._list.setVisible(bool(headings))
        self._empty.setVisible(not headings)

    def labels(self) -> list[str]:
        """今出ている行。テストと呼び出し側が読む。"""
        return [self._list.item(row).text() for row in range(self._list.count())]

    def empty_notice_visible(self) -> bool:
        return not self._empty.isHidden()

    def activate_row(self, row: int) -> None:
        """その行を押したことにする（クリックとキーの共通の口）。"""
        if 0 <= row < len(self._headings):
            self._list.setCurrentRow(row)
            self.heading_activated.emit(self._headings[row].line)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self.activate_row(self._list.row(item))

    # ------------------------------------------------------------------ 見た目

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._list.setStyleSheet(
            f"QListWidget {{ background: {theme.background}; "
            f"color: {theme.foreground}; border: none; }}"
            f"QListWidget::item {{ padding: 4px 8px; }}"
            f"QListWidget::item:selected {{ background: {theme.selection_background}; }}"
        )
        self._empty.setStyleSheet(
            f"QLabel {{ background: {theme.background}; color: {theme.muted_foreground}; }}"
        )
