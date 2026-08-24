"""メニューを開くボタン（ステータスバーの歯車）。

**メニューは必ず上に開く**（ユーザー要望 2026-08-24）。Qt 任せだと画面の
下に余裕がある限り下へ開くが、このボタンは窓のいちばん下にいる。下に
開くとメニューが窓の外（デスクトップの上）へ出て、窓から切り離されて
浮いて見える。

位置を決めているのは `QToolButton` の private な処理なので、設定では
変えられない。押されたことをここで受け取って自分で開く。
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMenu, QToolButton, QWidget


def above_position(anchor: QWidget, menu: QMenu) -> QPoint:
    """`anchor` の真上にメニューを置く座標。左端は `anchor` に揃える。

    `sizeHint()` は表示前でも当たる（QMenu は項目から高さを決める）。
    画面の上に収まらないときは `QMenu` 側が押し戻す。
    """
    return anchor.mapToGlobal(QPoint(0, 0)) - QPoint(0, menu.sizeHint().height())


class MenuButton(QToolButton):
    """押すとメニューが**上に**開くボタン。

    `InstantPopup` のまま（押した瞬間に開く）だが、開くのは Qt ではなく
    こちら。ついでに `QMenu.popup()` になるので、`QToolButton` が使う
    `QMenu.exec()` のように呼び出し側を止めない（テストが書ける）。
    """

    def setMenu(self, menu: QMenu) -> None:
        super().setMenu(menu)
        # 閉じたら押された見た目を戻す。`exec()` を使わないので、
        # 押し下げの解除も自分でやる
        menu.aboutToHide.connect(lambda: self.setDown(False))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        menu = self.menu()
        if menu is None or event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setDown(True)
        menu.popup(above_position(self, menu))
        event.accept()
