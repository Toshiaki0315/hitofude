"""クイックオープンと全文検索のパレット（spec §5.4）。

`Cmd+O` はタイトルへのあいまい一致、`Cmd+Shift+F` は全文検索。
入力欄と結果一覧という形は同じなので、**候補を出す関数だけを差し替える**
1 つのウィジェットで両方を賄う。

あいまい一致の判定は純関数に分けてある。順位付けは調整が入りやすく、
ウィジェット越しでは挙動を固定しづらい。
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from hitofude.storage.index_db import HIGHLIGHT_END, HIGHLIGHT_START
from hitofude.theme import LIGHT, ThemeColors

MAX_RESULTS = 50

_CONSECUTIVE_BONUS = 6
_START_BONUS = 12
_BOUNDARY_BONUS = 4
_GAP_PENALTY = 1
_BOUNDARY_CHARS = " 　/-_.,:;（(「[#"


@dataclass(frozen=True, slots=True)
class PaletteItem:
    title: str
    subtitle: str
    path: Path


def fuzzy_score(query: str, text: str) -> int | None:
    """`query` が `text` の部分列として現れるならスコア、無ければ None。

    大きいほど良い一致。連続している・先頭から始まる・区切りの直後から
    始まる、を優遇する。日本語も 1 文字ずつ照合するのでそのまま効く。
    """
    if not query:
        return 0

    needle = query.casefold()
    haystack = text.casefold()
    score = 0
    position = 0
    previous = -2

    for character in needle:
        found = haystack.find(character, position)
        if found < 0:
            return None

        if found == previous + 1:
            score += _CONSECUTIVE_BONUS
        elif found == 0:
            score += _START_BONUS
        elif haystack[found - 1] in _BOUNDARY_CHARS:
            score += _BOUNDARY_BONUS
        score -= min(found - position, 8) * _GAP_PENALTY

        previous = found
        position = found + 1

    # 同じ一致なら短いほうが目的のものである確率が高い
    return score - len(haystack) // 20


def fuzzy_filter(
    query: str, items: Iterable[PaletteItem], limit: int = MAX_RESULTS
) -> list[PaletteItem]:
    """スコア順に絞り込む。同点なら元の並び（更新順）を保つ。"""
    scored: list[tuple[int, int, PaletteItem]] = []
    for order, item in enumerate(items):
        score = fuzzy_score(query, item.title)
        if score is not None:
            scored.append((-score, order, item))
    scored.sort()
    return [item for _score, _order, item in scored[:limit]]


class Palette(QDialog):
    """入力欄 + 結果一覧。候補は `provider` が返す。"""

    chosen = Signal(object)
    """選ばれた `Path`。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        placeholder: str = "",
        theme: ThemeColors = LIGHT,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.resize(560, 380)

        self._provider: Callable[[str], list[PaletteItem]] = lambda _query: []
        self._items: list[PaletteItem] = []

        self._input = QLineEdit(self)
        self._input.setPlaceholderText(placeholder)
        self._input.setClearButtonEnabled(True)

        self._results = QListWidget(self)
        self._results.setItemDelegate(_ResultDelegate(theme, self._results))
        self._results.setFrameShape(QListWidget.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._input)
        layout.addWidget(self._results)

        self._input.textChanged.connect(self._refresh)
        self._results.itemActivated.connect(self._accept_item)
        self._input.installEventFilter(self)

    # ------------------------------------------------------------------ 設定

    def set_provider(self, provider: Callable[[str], list[PaletteItem]]) -> None:
        self._provider = provider

    def open_with(self, query: str = "") -> None:
        self._input.setText(query)
        self._refresh(query)
        self._input.setFocus()
        self._input.selectAll()
        self.show()

    @property
    def items(self) -> list[PaletteItem]:
        return list(self._items)

    @property
    def query(self) -> str:
        return self._input.text()

    def current_item(self) -> PaletteItem | None:
        row = self._results.currentRow()
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    # ------------------------------------------------------------------ 動作

    def _refresh(self, query: str) -> None:
        self._items = self._provider(query)
        self._results.clear()
        for item in self._items:
            entry = QListWidgetItem()
            entry.setData(Qt.ItemDataRole.DisplayRole, item.title)
            entry.setData(int(Qt.ItemDataRole.UserRole) + 1, item.subtitle)
            self._results.addItem(entry)
        if self._items:
            self._results.setCurrentRow(0)

    def _accept_item(self, _entry: QListWidgetItem | None = None) -> None:
        item = self.current_item()
        if item is None:
            return
        self.chosen.emit(item.path)
        self.accept()

    def move_selection(self, delta: int) -> None:
        if not self._items:
            return
        row = (self._results.currentRow() + delta) % len(self._items)
        self._results.setCurrentRow(row)

    def eventFilter(self, watched: QWidget, event) -> bool:
        """入力欄にフォーカスを置いたまま上下キーで候補を選べるようにする。"""
        from_input = watched is self._input and isinstance(event, QKeyEvent)
        if from_input and event.type() == QKeyEvent.Type.KeyPress:
            match event.key():
                case Qt.Key.Key_Down:
                    self.move_selection(1)
                    return True
                case Qt.Key.Key_Up:
                    self.move_selection(-1)
                    return True
                case Qt.Key.Key_Return | Qt.Key.Key_Enter:
                    self._accept_item()
                    return True
        return super().eventFilter(watched, event)


class _ResultDelegate(QStyledItemDelegate):
    """タイトルと、一致部分を太字にしたスニペットを描く（spec §5.4）。"""

    SUBTITLE_ROLE = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, theme: ThemeColors, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def _document(self, index: QModelIndex) -> QTextDocument:
        title = escape(index.data(Qt.ItemDataRole.DisplayRole) or "")
        subtitle = _to_html(index.data(self.SUBTITLE_ROLE) or "")
        document = QTextDocument()
        document.setHtml(
            f"<div>{title}</div><div style='color:{self._theme.muted_foreground}'>{subtitle}</div>"
        )
        return document

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        document = self._document(index)
        document.setTextWidth(option.rect.width() or 480)
        return QSize(int(document.idealWidth()), int(document.size().height()) + 8)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        from PySide6.QtWidgets import QStyle

        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(self._theme.selection_background))

        document = self._document(index)
        document.setTextWidth(option.rect.width())
        painter.translate(option.rect.topLeft() + type(option.rect.topLeft())(4, 4))
        document.drawContents(painter)
        painter.restore()


def _to_html(snippet: str) -> str:
    """スニペットの印を太字に変換する。

    エスケープしてから印を置き換える。逆にすると本文中の `<b>` が
    タグとして解釈され、書いた内容で表示が壊れる。
    """
    return (
        escape(snippet)
        .replace(escape(HIGHLIGHT_START), "<b>")
        .replace(escape(HIGHLIGHT_END), "</b>")
        .replace(HIGHLIGHT_START, "<b>")
        .replace(HIGHLIGHT_END, "</b>")
    )
