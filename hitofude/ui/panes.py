"""3 ペインの分割と、その幅の面倒（spec §5.1）。

幅の復元・退避・出し入れは `QSplitter` 自身の仕事なので、`MainWindow` から
ここへ移した。**隠したペインの幅は 0 になる**という Qt の性質が、
保存と復元の両方に絡んでくる（実際に「ペインが二度と戻らない」不具合を
出した）ので、その扱いを 1 か所にまとめている。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget

from hitofude.config import DEFAULT_SPLITTER_SIZES

# ペインの区切り線。細くしないと掴む場所ではなく境界として読まれない
SPLITTER_HANDLE_WIDTH = 1
# ペインの最小幅。spec §5.1 の既定（180 / 280）より少し狭いところまでは
# 縮められるが、それ以下には潰れないようにする
SIDEBAR_MIN_WIDTH = 140
NOTE_LIST_MIN_WIDTH = 200


def _default_width(index: int, widget: QWidget) -> int:
    """そのペインの既定幅。既定表に無い後付けのペインは最小幅で起こす。

    アウトライン（4 枚目 / ADR-0022）の追加で `DEFAULT_SPLITTER_SIZES`
    （3 要素）を範囲外参照し、**起動のたびに IndexError で落ちる**経路が
    あった（コードレビュー指摘。設定を手で直すまで再発する）。
    """
    if index < len(DEFAULT_SPLITTER_SIZES):
        return DEFAULT_SPLITTER_SIZES[index]
    return widget.minimumWidth()


class _Divider(QSplitterHandle):
    """ペインの境界に引く 1px の線。"""

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.splitter().rule_color))


class PaneSplitter(QSplitter):
    """区切り線を自前で描く QSplitter。

    **スタイルシートを使わない。** `setStyleSheet()` は子ウィジェットにも
    波及し、`QPalette` より優先されるため、エディタのテーマ切替が効かなく
    なる（実際に踏んだ）。線 1 本のために表示系全体の仕組みを壊せない。
    """

    def __init__(self, rule_color: str, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.rule_color = rule_color
        self.setHandleWidth(SPLITTER_HANDLE_WIDTH)
        # 隠す直前の幅。隠すと Qt が 0 にするので、元の幅が失われる
        self._widths: dict[int, int] = {}

    def createHandle(self) -> QSplitterHandle:
        return _Divider(self.orientation(), self)

    def set_rule_color(self, color: str) -> None:
        self.rule_color = color
        for index in range(1, self.count()):
            self.handle(index).update()

    # ------------------------------------------------------------------ 幅

    def restore_sizes(self, stored: list[int]) -> None:
        """保存されていた幅を戻す。**表示状態を決めた後に呼ぶこと。**

        隠れているウィジェットは幅 0 になるので、順序が逆だと割り当てが
        その場で捨てられる。
        """
        for index in range(min(len(stored), self.count())):
            if stored[index] >= self.widget(index).minimumWidth():
                self._widths[index] = stored[index]
        self.setSizes(self._usable(stored))

    def _usable(self, sizes: list[int]) -> list[int]:
        """潰れた幅を既定へ戻す。

        ペインを隠すと `QSplitter` はその幅を 0 にし、終了時にそのまま
        保存される。次の起動でも 0 のまま復元されるため、**表示されて
        いるのに幅 0 のペイン**ができていた。

        戻すのは最小幅を下回っているときだけ。手で狭めた幅は保つ。
        広げた分は最後のペインから借りて**合計を変えない**。合計が
        ウィンドウ幅と食い違うと `QSplitter` が比例配分し直し、戻した幅が
        その場で縮む。
        """
        restored = list(sizes)
        for index in range(min(len(restored), self.count())):
            widget = self.widget(index)
            # `isVisible()` はウィンドウを表示するまで常に False。ここは
            # まだ `show()` の前なので、隠す意図があるかを `isHidden()` で見る
            if widget.isHidden() or restored[index] >= widget.minimumWidth():
                continue
            wanted = max(_default_width(index, widget), widget.minimumWidth())
            restored[-1] = max(1, restored[-1] - (wanted - restored[index]))
            restored[index] = wanted
        return restored

    def sizes_to_keep(self) -> list[int]:
        """保存する幅。隠れているペインは隠す直前の値を残す。

        0 のまま保存すると、次に出したときユーザーが決めた幅へ戻せない。
        """
        return [
            self._widths.get(index, size) if self.widget(index).isHidden() else size
            for index, size in enumerate(self.sizes())
        ]

    def toggle_pane(self, index: int) -> None:
        """ペインの表示を切り替える。出すときは使える幅を確保する。

        隠したペインの幅は 0 になっている。`setVisible(True)` だけでは 0 の
        ままなので、見えているつもりで見えないペインが残る。
        """
        self.set_pane_visible(index, self.widget(index).isHidden())

    def set_pane_visible(self, index: int, visible: bool) -> None:
        """ペインの表示を決める。幅の退避・復元込み。

        **`widget.setVisible()` を直に呼ばない**（コードレビュー指摘）。
        直に呼ぶと隠す直前の幅が退避されず、次に出したときや次の起動で
        ユーザーが決めた幅が失われる。
        """
        widget = self.widget(index)
        if visible == (not widget.isHidden()):
            return
        if not visible:
            self._widths[index] = self.sizes()[index]
        widget.setVisible(visible)
        if visible:
            self._grow(index)

    def _grow(self, index: int) -> None:
        sizes = self.sizes()
        widget = self.widget(index)
        if sizes[index] >= widget.minimumWidth():
            return

        # 隠す前の幅へ戻す。覚えていなければ既定
        wanted = max(self._widths.get(index, _default_width(index, widget)), widget.minimumWidth())
        # 広げた分は最後のペインから借りる。全体の合計を変えないため
        sizes[-1] = max(1, sizes[-1] - (wanted - sizes[index]))
        sizes[index] = wanted
        self.setSizes(sizes)
