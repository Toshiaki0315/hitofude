"""バックリンクの帯（E-6 ③ / ADR-0011）。

「このノートを指しているのは誰か」を**本文の下**に出す。

置き場所の理由は ADR-0011。要点は 2 つで、パレットにすると探しに行った人
しか見ない（バックリンクの値打ちは気づいていない繋がりに気づくこと）、
右ペインにすると幅を常に取る（0 件のノートのほうが多い）。

**エディタの文書に文字として入れない。** `toPlainText()` がそのまま保存
内容（R1）なので、ファイルに無い文字が混ざる。ここはレイアウトに積む
ただのウィジェットで、本文には一切触れない。

**畳んだ状態を既定にする。** 帯は画面の下に居続けるので、開きっぱなしは
場所を取る。1 行の見出しに件数を出せば「繋がりがある」ことは伝わる。
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hitofude.theme import LIGHT, ThemeColors

LABEL = "バックリンク"
# 開閉の向き。三角は他の部品でも使っていないので、ここで意味が衝突しない
CLOSED_MARK = "▸"
OPEN_MARK = "▾"
# 一覧の高さ。**画面の半分を占めないこと。** 本文が主で、こちらは添え物
MAX_LIST_HEIGHT = 148
ROW_HEIGHT = 34
RULE_HEIGHT = 1


@dataclass(frozen=True, slots=True)
class Backlink:
    title: str
    context: str
    """指している行そのもの（`core/wikilink.context_line`）。冒頭ではない。"""

    path: Path
    """vault からの相対パス。開くのは `MainWindow` の仕事。"""


class BacklinkBar(QWidget):
    note_activated = Signal(object)
    """行が押された。載るのは相対 `Path`（一覧系の同名シグナルと同じ言葉）。
    **開くのはここではない**（ウィジェットは vault を知らない）。"""

    toggled = Signal(bool)
    """開閉が変わった。覚えておくのは `Config` の仕事。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme
        self._links: list[Backlink] = []
        self._expanded = False

        self._header = QToolButton(self)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        # **フォーカスを受け取らない。** 受け取ると本文の選択が外れる
        # （書式ツールバーと同じ約束）
        self._header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header.setToolTip("このノートを指しているノート（⌘4）")
        self._header.clicked.connect(self.toggle)

        self._list = QListWidget(self)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setUniformItemSizes(True)
        self._list.hide()
        self._list.itemClicked.connect(self._on_item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(0)
        layout.addWidget(self._header, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._list)

        self._apply_theme()
        self.hide()  # 0 件のうちは出さない

    # ------------------------------------------------------------------ 参照

    def header_text(self) -> str:
        return self._header.text()

    def header_button(self) -> QToolButton:
        return self._header

    def list_widget(self) -> QListWidget:
        return self._list

    def expanded(self) -> bool:
        return self._expanded

    def count(self) -> int:
        return len(self._links)

    def titles(self) -> list[str]:
        return [link.title for link in self._links]

    def item_text(self, row: int) -> str:
        item = self._list.item(row)
        return item.text() if item is not None else ""

    # ------------------------------------------------------------------ 操作

    def set_links(self, links: list[Backlink]) -> None:
        """一覧を入れ替える。0 件なら帯ごと隠す。

        **開閉は保つ。** ノートを切り替えるたびに畳み直されると、開いて
        おきたい人が毎回押すことになる。
        """
        self._links = list(links)
        self._list.clear()
        for link in self._links:
            item = QListWidgetItem(self._label_for(link))
            item.setToolTip(link.context or link.title)
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            self._list.addItem(item)

        self.setVisible(bool(self._links))
        self._sync()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._sync()
        self.toggled.emit(expanded)

    def activate(self, row: int) -> None:
        """行を選ぶ（クリックと同じ）。無い行なら何もしない。"""
        if 0 <= row < len(self._links):
            self.note_activated.emit(self._links[row].path)

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._apply_theme()

    # ------------------------------------------------------------------ 内部

    def _on_item(self, item: QListWidgetItem) -> None:
        self.activate(self._list.row(item))

    def _label_for(self, link: Backlink) -> str:
        return f"{link.title}\n{link.context}" if link.context else link.title

    def _sync(self) -> None:
        mark = OPEN_MARK if self._expanded else CLOSED_MARK
        self._header.setText(f"{mark} {LABEL} {len(self._links)}")
        self._list.setVisible(self._expanded and bool(self._links))
        if self._expanded:
            wanted = min(len(self._links) * ROW_HEIGHT + 4, MAX_LIST_HEIGHT)
            self._list.setFixedHeight(wanted)

    def paintEvent(self, event) -> None:
        """上端に 1px の線を引く。本文との境目（ツールバーと同じ引き方）。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), RULE_HEIGHT, QColor(self._theme.rule))
        painter.end()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"QWidget {{ background: {self._theme.background}; }}"
            f"QToolButton {{ border: none; padding: 3px 4px; "
            f"color: {self._theme.muted_foreground}; }}"
            f"QToolButton:hover {{ color: {self._theme.foreground}; }}"
            f"QListWidget {{ background: {self._theme.background}; "
            f"color: {self._theme.foreground}; }}"
            f"QListWidget::item {{ padding: 2px 4px; }}"
            f"QListWidget::item:hover {{ background: {self._theme.selection_background}; }}"
        )
