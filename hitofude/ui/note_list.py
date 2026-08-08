"""ノート一覧（spec §5.1, §6.6）。

`QListWidget` は使わない（§6.6）。5,000 件のノートを扱うため、
行を widget として持つのではなくモデルから引く。

表示に必要な情報（タイトル・プレビュー・日付）は索引の `NoteRow` に
入っているので、**一覧を描くのにファイルを開かない**。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from hitofude.storage.index_db import NoteRow
from hitofude.theme import LIGHT, ThemeColors

PIN_MARK = "●"


class NoteRole(IntEnum):
    TITLE = int(Qt.ItemDataRole.UserRole) + 1
    PREVIEW = TITLE + 1
    DATE = TITLE + 2
    PATH = TITLE + 3
    PINNED = TITLE + 4


def format_date(value: str) -> str:
    """ノート一覧に出す短い日付。

    今日なら時刻、今年なら月日、それ以前は年から。front matter は手で
    編集されうるので、読めない値は空文字にして落ちないようにする。
    """
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return ""

    now = datetime.now(moment.tzinfo)
    if moment.date() == now.date():
        return f"{moment.hour:02d}:{moment.minute:02d}"
    if moment.year == now.year:
        return f"{moment.month}/{moment.day}"
    return f"{moment.year}/{moment.month}/{moment.day}"


class NoteListModel(QAbstractListModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[NoteRow] = []

    def set_rows(self, rows: list[NoteRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        # Qt からは QModelIndex() が渡る。既定値に呼び出しを書けないので
        # None を受けて中で判定する

        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        row = self.note_at(index)
        if row is None:
            return None
        match role:
            case Qt.ItemDataRole.DisplayRole | NoteRole.TITLE:
                return row.title
            case NoteRole.PREVIEW:
                return row.preview
            case NoteRole.DATE:
                return format_date(row.modified_at)
            case NoteRole.PATH:
                return row.path
            case NoteRole.PINNED:
                return row.pinned
            case _:
                return None

    def note_at(self, index: QModelIndex) -> NoteRow | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()]

    def index_of(self, path: Path) -> QModelIndex:
        """パスから行を引く。外部変更のあとで選択を保つのに使う。"""
        for number, row in enumerate(self._rows):
            if row.path == path:
                return self.index(number)
        return QModelIndex()


@dataclass(frozen=True, slots=True)
class _Metrics:
    padding: int = 12
    spacing: int = 4
    date_width: int = 48
    preview_lines: int = 2


class NoteItemDelegate(QStyledItemDelegate):
    """1 行に「タイトル / 日付 / プレビュー 2 行」を描く（spec §5.1）。"""

    def __init__(self, theme: ThemeColors = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._metrics = _Metrics()

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        metrics = QFontMetrics(option.font)
        height = (
            self._metrics.padding * 2
            + metrics.height()
            + self._metrics.spacing
            + metrics.height() * self._metrics.preview_lines
        )
        return QSize(option.rect.width(), height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, QColor(self._theme.selection_background))

        pad = self._metrics.padding
        body = option.rect.adjusted(pad, pad, -pad, -pad)

        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        line_height = QFontMetrics(title_font).height()

        date = index.data(NoteRole.DATE) or ""
        date_width = self._metrics.date_width if date else 0
        title_rect = QRect(body.left(), body.top(), body.width() - date_width, line_height)

        painter.setPen(QColor(self._theme.foreground))
        if index.data(NoteRole.PINNED):
            mark_width = QFontMetrics(title_font).horizontalAdvance(PIN_MARK + " ")
            painter.setPen(QColor(self._theme.accent))
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, PIN_MARK)
            title_rect = title_rect.adjusted(mark_width, 0, 0, 0)
            painter.setPen(QColor(self._theme.foreground))

        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(title_font).elidedText(
                index.data(NoteRole.TITLE) or "", Qt.TextElideMode.ElideRight, title_rect.width()
            ),
        )

        painter.setFont(option.font)
        painter.setPen(QColor(self._theme.muted_foreground))
        if date:
            painter.drawText(
                QRect(body.right() - date_width, body.top(), date_width, line_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                date,
            )

        preview_rect = QRect(
            body.left(),
            body.top() + line_height + self._metrics.spacing,
            body.width(),
            QFontMetrics(option.font).height() * self._metrics.preview_lines,
        )
        painter.drawText(
            preview_rect,
            Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            index.data(NoteRole.PREVIEW) or "",
        )
        painter.restore()


class NoteListView(QListView):
    note_activated = Signal(object)
    """選択されたノートの `Path`。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._model = NoteListModel(self)
        self._delegate = NoteItemDelegate(theme, self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.setUniformItemSizes(True)  # 5,000 件でも高さ計算を 1 回で済ませる
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.Shape.NoFrame)

    def set_rows(self, rows: list[NoteRow]) -> None:
        current = self.current_path()
        self._model.set_rows(rows)
        if current is not None:
            self.select_path(current)

    def set_theme(self, theme: ThemeColors) -> None:
        self._delegate.set_theme(theme)
        self.viewport().update()

    def current_path(self) -> Path | None:
        row = self._model.note_at(self.currentIndex())
        return row.path if row is not None else None

    def select_path(self, path: Path) -> None:
        index = self._model.index_of(path)
        if index.isValid():
            self.setCurrentIndex(index)

    def currentChanged(self, current: QModelIndex, previous: QModelIndex) -> None:
        super().currentChanged(current, previous)
        row = self._model.note_at(current)
        if row is not None:
            self.note_activated.emit(row.path)
