"""ノート一覧と、その上のヘッダ（spec §5.1）。

新規ノートがメニューと `Cmd+N` からしか作れなかったので、**画面の中にも
入口を置く**。`EditorPane` と同じ形で、一覧をヘッダごと包む。

ここは入口を置くだけで、**ノートを作る仕事は持たない**。作るのは
`MainWindow`（vault と索引の両方に触る必要があるため）。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.note_list import NoteListView
from hitofude.ui.panes import NOTE_LIST_MIN_WIDTH

NEW_NOTE_GLYPH = "＋"
HEADER_MARGIN = 6


class NoteListPane(QWidget):
    new_note_requested = Signal()

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

        header = QHBoxLayout()
        header.setContentsMargins(HEADER_MARGIN, HEADER_MARGIN, HEADER_MARGIN, 0)
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

    def set_theme(self, theme: ThemeColors) -> None:
        self._list.set_theme(theme)
        # ボタンだけに当てる。ペイン全体へ流すと一覧の配色まで上書きしてしまう
        self._new.setStyleSheet(f"QToolButton {{ color: {theme.muted_foreground}; border: none; }}")
