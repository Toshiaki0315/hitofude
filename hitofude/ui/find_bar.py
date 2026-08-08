"""ノート内検索のバー（`Cmd+F`）。

**探し方を知らないウィジェット。** 入力を受けてシグナルを出すだけで、
文字列を探すのは `core/search.py`、カーソルを動かすのは `MarkdownEditor`。
`ui/editor_pane.py` が両者を繋ぐ。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hitofude.theme import LIGHT, ThemeColors

NO_MATCH = "見つかりません"


class _SearchInput(QLineEdit):
    """変換中の Enter を検索に使わない入力欄（R6）。

    日本語変換の確定は Enter で行う。そのまま `returnPressed` に流すと、
    **確定した瞬間に検索が走って本文へカーソルが飛ぶ**。
    """

    accepted = Signal(bool)
    """検索の実行。後ろ向きなら True。"""

    dismissed = Signal()

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._composing = False
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)

    def is_composing(self) -> bool:
        return self._composing

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.dismissed.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._composing:
                super().keyPressEvent(event)
                return
            self.accepted.emit(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return
        super().keyPressEvent(event)


class FindBar(QWidget):
    find_requested = Signal(str, bool)
    """クエリと向き（後ろ向きなら True）。"""

    replace_requested = Signal(str, str)
    replace_all_requested = Signal(str, str)
    query_changed = Signal(str)
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme

        self._query = _SearchInput("検索", self)
        self._replacement = _SearchInput("置換", self)
        self._status = QLabel("", self)
        self._case = QCheckBox("大文字小文字を区別", self)

        previous = QPushButton("前へ", self)
        following = QPushButton("次へ", self)
        replace = QPushButton("置換", self)
        replace_all = QPushButton("すべて置換", self)
        close = QPushButton("閉じる", self)

        top = QHBoxLayout()
        top.addWidget(self._query, 1)
        top.addWidget(self._status)
        top.addWidget(previous)
        top.addWidget(following)
        top.addWidget(close)

        bottom = QHBoxLayout()
        bottom.addWidget(self._replacement, 1)
        bottom.addWidget(replace)
        bottom.addWidget(replace_all)
        bottom.addWidget(self._case)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addLayout(bottom)

        self._query.textChanged.connect(self.query_changed.emit)
        self._query.accepted.connect(lambda backward: self._emit_find(backward=backward))
        self._query.dismissed.connect(self.dismissed.emit)
        self._replacement.accepted.connect(lambda _: self._emit_replace())
        self._replacement.dismissed.connect(self.dismissed.emit)
        self._case.toggled.connect(lambda _: self.query_changed.emit(self.query))

        previous.clicked.connect(lambda: self._emit_find(backward=True))
        following.clicked.connect(lambda: self._emit_find(backward=False))
        replace.clicked.connect(self._emit_replace)
        replace_all.clicked.connect(
            lambda: self.replace_all_requested.emit(self.query, self.replacement)
        )
        close.clicked.connect(self.dismissed.emit)

        self.set_theme(theme)

    # ------------------------------------------------------------------ 参照

    @property
    def query(self) -> str:
        return self._query.text()

    @property
    def replacement(self) -> str:
        return self._replacement.text()

    @property
    def case_sensitive(self) -> bool:
        return self._case.isChecked()

    # ------------------------------------------------------------------ 操作

    def open_with(self, seed: str = "") -> None:
        """バーを出して入力欄へ移る。選択していた文字を初期値にする。

        改行を含む選択は初期値にしない。行をまたいで選んだ状態で `Cmd+F` を
        押すのはたいてい「今の選択を探したい」ではない。
        """
        if seed and "\n" not in seed:
            self._query.setText(seed)
        self.show()
        self._query.setFocus()
        self._query.selectAll()

    def set_status(self, total: int) -> None:
        if not self.query:
            self._status.setText("")
        else:
            self._status.setText(f"{total} 件" if total else NO_MATCH)

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._status.setStyleSheet(f"color: {theme.muted_foreground};")

    def _emit_find(self, *, backward: bool) -> None:
        if self.query:
            self.find_requested.emit(self.query, backward)

    def _emit_replace(self) -> None:
        if self.query:
            self.replace_requested.emit(self.query, self.replacement)
