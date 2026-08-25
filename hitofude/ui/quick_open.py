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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from hitofude.storage.index_db import HIGHLIGHT_END, HIGHLIGHT_START
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui import tooltip
from hitofude.ui.format_toolbar import BUTTON_RADIUS  # 丸みは 1 か所から引く
from hitofude.ui.icons import Glyph, glyph_icon

MAX_RESULTS = 50

# 閉じるボタン（ユーザー要望）。**記号だけでは気づかれない**（薄い × を
# 大きくしても見つからなかった、というユーザー報告が 2 回）。言葉で書き、
# 一覧のボタンと同じ角丸の枠を付ける
CLOSE_ICON = 12

# 1 行の内側の余白（上下左右）。帯と文字が接しないぶん
PADDING = 4
# 一覧の幅が分からないときの代用。ふつうは使われない
FALLBACK_WIDTH = 480

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
    line: int | None = None
    """同じノートの中の飛び先（アウトライン。C-2）。ノートを開く用途では None。"""


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
    """選ばれた `PaletteItem`。行番号を持つ用途（アウトライン）があるので
    パスだけでは足りない。"""

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

        # **閉じるボタン**（ユーザー要望）。枠の無い窓なので OS の閉じる
        # ボタンが無く、Esc を知らないと閉じられなかった
        self._close = QPushButton("閉じる", self)
        self._close.setIcon(glyph_icon(Glyph.CLOSE, theme.muted_foreground))
        self._close.setIconSize(QSize(CLOSE_ICON, CLOSE_ICON))
        self._close.setToolTip("閉じる（Esc）")
        tooltip.adopt(self)  # 自前のツールチップ（黒地に白・角丸）
        # 一覧のボタン（ソート・新規）と同じ形。**押せるものだと分かる形を
        # アプリの中で 1 つに揃える。** 色は増やさない
        self._close.setStyleSheet(
            f"QPushButton {{ color: {theme.muted_foreground}; "
            f"border: 1px solid {theme.rule}; border-radius: {BUTTON_RADIUS}px; "
            f"padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {theme.tag_background}; }}"
        )
        # **打つ手を止めない。** 押す気が無い人には無いのと同じ
        self._close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close.clicked.connect(self.reject)

        self._results = QListWidget(self)
        self._results.setItemDelegate(_ResultDelegate(theme, self._results))
        self._results.setFrameShape(QListWidget.Shape.NoFrame)

        # 書き方の案内（案 1）。**要らないときは場所を取らない**（一覧が狭くなる）
        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"QLabel {{ color: {theme.muted_foreground}; padding: 2px 4px; }}")
        self._hint.hide()

        # **縦を食わない。** 別の行にすると一覧が狭くなり、候補が減る
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(self._input, 1)
        top.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self._hint)
        layout.addWidget(self._results)

        self._input.textChanged.connect(self._refresh)
        self._results.itemActivated.connect(self._accept_item)
        self._input.installEventFilter(self)

    # ------------------------------------------------------------------ 参照

    @property
    def close_button(self) -> QPushButton:
        return self._close

    @property
    def input_box(self) -> QLineEdit:
        return self._input

    @property
    def results_list(self) -> QListWidget:
        return self._results

    # ------------------------------------------------------------------ 設定

    def set_provider(self, provider: Callable[[str], list[PaletteItem]]) -> None:
        self._provider = provider

    def open_with(self, query: str = "") -> None:
        """**先に出してから候補を入れる。**

        行の高さは幅で決まる（副題が折り返す）。出す前に入れると、一覧が
        まだ最終的な幅を知らないまま測ることになり、余分な折り返しのぶん
        行が高くなる。**選択の帯だけが下へ伸びて見えた**のがこれ
        （実測: 割当 72px に対し中身 46px）。
        """
        self.show()
        self._input.setText(query)
        self._refresh(query)
        self._input.setFocus()
        self._input.selectAll()

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

    def set_hint(self, text: str) -> None:
        """入力欄の下に一言出す。空にすると消える（案 1）。"""
        self._hint.setText(text)
        self._hint.setVisible(bool(text))

    def hint_text(self) -> str:
        return self._hint.text()

    def hint_visible(self) -> bool:
        return not self._hint.isHidden()

    def _refresh(self, query: str) -> None:
        # **前の案内を残さない。** 直したのに出たままだと、直っていない
        # ように見える。出すかどうかは候補を作る側が決める
        self.set_hint("")
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
        self.chosen.emit(item)
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
        """**描くときと同じ幅で測る**（ユーザー報告）。

        `option.rect` はレイアウトの前だと空で来る。決め打ちの幅で代用すると
        副題が余分に折り返し、**その高さぶんだけ行が高くなる**。中身は下に
        寄らず上から描くので、選択の帯だけが下へ伸びて見えた
        （実測: 割当 72px に対し中身 46px）。
        """
        width = self._row_width(option)
        document = self._document(index)
        document.setTextWidth(width)
        # **幅も一覧に合わせて返す。** 文字の理想幅（`idealWidth`）を返すと、
        # Qt がその狭い幅で測り直し、折り返しが増えて行が高くなる
        return QSize(width, int(document.size().height()) + PADDING * 2)

    def _row_width(self, option: QStyleOptionViewItem) -> int:
        """1 行に使える幅。**一覧の幅をそのまま使う。**

        `option.rect` は測り直しのたびに変わる（前回返した幅が入ってくる）
        ので、これを基準にすると幅がじわじわ縮む。
        """
        view = self.parent()
        viewport = getattr(view, "viewport", None)
        if viewport is not None and viewport().width() > 0:
            return viewport().width()
        return option.rect.width() or FALLBACK_WIDTH

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        from PySide6.QtWidgets import QStyle

        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(self._theme.selection_background))

        document = self._document(index)
        document.setTextWidth(option.rect.width())
        painter.translate(option.rect.topLeft() + type(option.rect.topLeft())(PADDING, PADDING))
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
