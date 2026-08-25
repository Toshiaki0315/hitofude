"""自前のツールチップ（ユーザー要望 2026-08-24）。

Qt の `QToolTip` では角が丸くならない。窓を不透明に描くので
`border-radius` の外側まで地の色で塗られ、しかも出すたびにラベルを
作り直して透過の設定を戻す。外から直す道は 3 つとも壊れた
（`app.apply_tooltip_colors` に実測の記録）。

**Qt に描かせるのをやめ、自分が所有する 1 つの窓を描く。**

- 窓は作り直されない。透過も丸みも一度決めれば保たれる
- 見た目は `paintEvent` で描く。QSS は使わない（translucent な
  トップレベルでは背景が描かれないことがある。実測）
- 採用（`attach`）したウィジェットの `QEvent.ToolTip` を受け取り、
  ネイティブの代わりにこれを出す。**アプリ全体のフィルタは使わない**
  （空のフィルタでもテスト群を segfault させた。同記録）

採用していないウィジェットには今まで通りネイティブが出る。そちらの
色と余白は `app.apply_tooltip_colors` / `apply_tooltip_margin` が整える。
"""

import logging

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QHelpEvent, QPainter
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLabel, QToolTip, QWidget

from hitofude.app import TOOLTIP_BACKGROUND, TOOLTIP_FOREGROUND

logger = logging.getLogger(__name__)

RADIUS = 8
"""角の丸み（px）。メニュー（10px）より少し小さく、小さな窓らしく。"""

PADDING = (10, 7)
"""左右・上下の余白（px）。Qt の既定は 0 で、文字が縁に貼り付く。
Claude Desktop のツールチップに合わせた（ユーザー添付の見本）。"""

OFFSET = QPoint(8, 18)
"""マウスからのずらし。真上に出すとカーソルが文字に重なる。"""

WRAP_WIDTH = 420
"""折り返しを始める幅（px）。画面の端まで 1 行で伸びると読みにくい。"""

_HIDE_EVENTS = frozenset(
    {
        QEvent.Type.Leave,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.KeyPress,
        QEvent.Type.Wheel,
        QEvent.Type.Hide,
        QEvent.Type.FocusOut,
        QEvent.Type.WindowDeactivate,
    }
)


class _Bubble(QLabel):
    """ツールチップの窓。黒地に白・角丸・四隅は透明。"""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 入力を奪わない。ツールチップにフォーカスが移ると打鍵が途切れる
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # 出したままでもアプリの終了を止めない（Mermaid で踏んだ轍）
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        horizontal, vertical = PADDING
        self.setContentsMargins(horizontal, vertical, horizontal, vertical)
        palette = self.palette()
        palette.setColor(self.foregroundRole(), QColor(TOOLTIP_FOREGROUND))
        self.setPalette(palette)
        # 消し忘れの保険。ネイティブと同じく、置きっぱなしでは残さない
        self._expiry = QTimer(self)
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self.hide)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOOLTIP_BACKGROUND))
        painter.drawRoundedRect(self.rect(), RADIUS, RADIUS)
        painter.end()
        super().paintEvent(event)

    def show_at(self, at: QPoint, text: str) -> None:
        if self.isVisible() and self.text() == text:
            return  # 同じ説明のまま。位置を追いかけるとちらつく
        # 文字の大きさはネイティブと同じ口（`QToolTip.setFont`）から取る。
        # `apply_chrome_font` の +2pt（ユーザー要望）をそのまま引き継ぐ
        self.setFont(QToolTip.font())
        self.setWordWrap(False)
        self.setText(text)
        self.adjustSize()
        if self.width() > WRAP_WIDTH:
            self.setWordWrap(True)
            self.setFixedWidth(WRAP_WIDTH)
            self.adjustSize()
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)  # 次の説明のために固定を解く
        self.move(self._clamped(at + OFFSET))
        self.show()
        # ネイティブの読み終わる目安と同じ形（長いほど残す）
        self._expiry.start(10000 + 40 * max(0, len(text) - 100))

    def _clamped(self, at: QPoint) -> QPoint:
        screen = QApplication.screenAt(at) or QApplication.primaryScreen()
        if screen is None:
            return at
        area = screen.availableGeometry()
        x = min(max(at.x(), area.left()), area.right() - self.width())
        y = min(max(at.y(), area.top()), area.bottom() - self.height())
        return QPoint(x, y)


class _Guide(QObject):
    """採用したウィジェットの合図で出し入れするフィルタ。

    **必ず消費する（True）。** 返さないと Qt が同じ合図でネイティブを
    出し、二重に表示される。
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            assert isinstance(event, QHelpEvent)
            text = _text_for(watched, event.pos())
            if text:
                show(event.globalPos(), text)
            else:
                hide()
            return True
        if event.type() in _HIDE_EVENTS and is_showing():
            hide()
        return False


def _text_for(widget: QWidget, at: QPoint) -> str:
    """出すべき説明。一覧の中ではアイテム側の説明を見る。"""
    view = widget.parent()
    if isinstance(view, QAbstractItemView) and widget is view.viewport():
        index = view.indexAt(at)
        found = index.data(Qt.ItemDataRole.ToolTipRole) if index.isValid() else None
        return str(found) if found else ""
    return widget.toolTip()


_bubble: _Bubble | None = None
_guide: _Guide | None = None
"""**参照を持ち続ける。** Qt は所有しないので、捨てるとフィルタが外れる。"""


def _the_bubble() -> _Bubble:
    global _bubble
    if _bubble is None:
        _bubble = _Bubble()
    return _bubble


def _the_guide() -> _Guide:
    global _guide
    if _guide is None:
        _guide = _Guide()
    return _guide


def show(at: QPoint, text: str) -> None:
    """`at`（グローバル座標）のそばに説明を出す。"""
    _the_bubble().show_at(at, text)


def hide() -> None:
    if _bubble is not None:
        _bubble.hide()


def is_showing() -> bool:
    return _bubble is not None and _bubble.isVisible()


def shown_text() -> str:
    return _bubble.text() if is_showing() else ""


def attach(widget: QWidget) -> None:
    """このウィジェットのツールチップを自前の窓で出す。

    同じフィルタを 2 度入れても Qt は 1 つに保つので、重ねて呼んでよい。
    """
    widget.installEventFilter(_the_guide())


def attach_view(view: QAbstractItemView) -> None:
    """一覧を採用する。合図はビューではなく **viewport に届く**。"""
    attach(view.viewport())


def adopt(root: QWidget) -> None:
    """`root` 以下で説明を持つウィジェットをまとめて採用する。

    画面を組み終えたところで 1 回呼ぶ。個別に張ると必ず張り漏れる。
    説明が**あとから**付くウィジェットは拾えないので、そういう作りの
    場所は `attach` / `attach_view` を自分で呼ぶ（一覧のアイテムなど）。
    """
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, QAbstractItemView):
            attach_view(widget)
        elif widget.toolTip():
            attach(widget)
