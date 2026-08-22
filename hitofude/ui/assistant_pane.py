"""手元の LLM の答えを出すペイン（L-1 / [ADR-0025](../../docs/adr/0025-local-llm.md)）。

**ここはモデルを知らない。** 押されたら合図を出し、届いた文字を出すだけ
（`outline_pane` が vault を知らないのと同じ分担）。頼む相手と本文の
受け渡しは `MainWindow` の仕事。

見せ方の約束は 3 つ。

- **押してから断らない。** Ollama が動いていなければボタンを灰色にする
- **黙って待たせない。** 最初の 1 文字まで実測 5.4 秒（M4 / gemma3:4b）
  かかるので、届いたぶんから順に出す
- **本文は書き換えない**（R1）。答えはここにしか出ない
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hitofude.core.llm import Task
from hitofude.theme import LIGHT, ThemeColors

ASSISTANT_MIN_WIDTH = 240
"""これより狭いと答えが読めない（`outline_pane` と同じ考え方）。"""

WAITING = "読んでいます…"

UNAVAILABLE = "Ollama が動いていません。\ndocs/ollama.md の手順で入れてください。"

STOPPED = "止めました。"

NO_RELATED = "関連するノートはありません。\nタグを付けるか `[[ノート名]]` で結ぶと出ます。"

# 題名と理由のあいだ。理由どうしは `/` で繋ぐ
REASON_MARK = " — "
REASON_JOIN = " / "


class AssistantPane(QWidget):
    requested = Signal(object)
    """押された `Task`。**読ませるのは呼び出し側**（ここは本文を知らない）。"""

    stopped = Signal()
    """「止める」が押された。"""

    related_requested = Signal()
    """「関連」が押された。**探すのは呼び出し側**（索引を引く）。"""

    note_activated = Signal(object)
    """関連ノートの相対 `Path`。**開くのは呼び出し側**。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme
        self._available = True
        self._running = False

        self._summary = QPushButton("要約", self)
        self._review = QPushButton("レビュー", self)
        self._related = QPushButton("関連", self)
        self._stop = QPushButton("止める", self)
        for button in (self._summary, self._review, self._related, self._stop):
            # 本文から手が離れないように（一覧のボタンと同じ作法）
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._summary.clicked.connect(lambda: self.requested.emit(Task.SUMMARY))
        self._review.clicked.connect(lambda: self.requested.emit(Task.REVIEW))
        self._stop.clicked.connect(self.stopped.emit)
        self._related.clicked.connect(self.related_requested.emit)

        # 関連ノート（L-3）は**モデルを通さない**ので、答えの欄とは分ける
        self._notes = QListWidget(self)
        self._notes.setFrameShape(QListWidget.Shape.NoFrame)
        self._notes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # **横に流さない。** 2 方向へ動かして読むことになる。切れたぶんは
        # マウスを置けば読める（`outline_pane` と同じ作法）
        self._notes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._notes.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._notes.setWordWrap(False)
        self._notes.itemClicked.connect(lambda item: self.activate_related(self._notes.row(item)))
        self._notes.hide()
        self._related_paths: list[object] = []

        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)  # 直すなら本文で直す（版の履歴と同じ）
        self._output.setFrameShape(QPlainTextEdit.Shape.NoFrame)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(8, 8, 8, 4)
        buttons.setSpacing(6)
        buttons.addWidget(self._summary)
        buttons.addWidget(self._review)
        buttons.addWidget(self._related)
        buttons.addStretch(1)
        buttons.addWidget(self._stop)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(buttons)
        layout.addWidget(self._status)
        layout.addWidget(self._notes, 1)
        layout.addWidget(self._output, 1)

        self.setMinimumWidth(ASSISTANT_MIN_WIDTH)
        self.set_theme(theme)
        self._refresh_buttons()

    # ------------------------------------------------------------------ 参照

    @property
    def summary_button(self) -> QPushButton:
        return self._summary

    @property
    def review_button(self) -> QPushButton:
        return self._review

    @property
    def related_button(self) -> QPushButton:
        return self._related

    @property
    def stop_button(self) -> QPushButton:
        return self._stop

    def text(self) -> str:
        return self._output.toPlainText()

    def related_labels(self) -> list[str]:
        return [self._notes.item(row).text() for row in range(self._notes.count())]

    def related_tooltips(self) -> list[str]:
        return [self._notes.item(row).toolTip() for row in range(self._notes.count())]

    @property
    def related_list(self) -> QListWidget:
        return self._notes

    def status_text(self) -> str:
        return self._status.text()

    def is_read_only(self) -> bool:
        return self._output.isReadOnly()

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ 状態

    def set_available(self, available: bool) -> None:
        """Ollama が使えるか。**押してから断らない**ための切り替え。"""
        self._available = available
        if not available:
            self._running = False
            self._status.setText(UNAVAILABLE)
        elif self._status.text() == UNAVAILABLE:
            self._status.setText("")
        self._refresh_buttons()

    def set_related(self, found: list[tuple[object, str, tuple[str, ...]]]) -> None:
        """関連ノートを並べる（L-3）。`(相対パス, 題名, 理由)` の並び。

        **理由も出す。** なぜ出たのかが読めないと、関係あるのか確かめよう
        がない。0 件なら**そう言う**（空欄で黙ると押し忘れと区別が付かない）。
        """
        self._notes.clear()
        self._related_paths = [path for path, _title, _reasons in found]
        for _path, title, reasons in found:
            label = f"{title}{REASON_MARK}{REASON_JOIN.join(reasons)}"
            item = QListWidgetItem(label)
            item.setToolTip(label)
            self._notes.addItem(item)
        self._notes.setVisible(bool(found))
        self._status.setText("" if found else NO_RELATED)

    def activate_related(self, row: int) -> None:
        """その行を押したことにする（クリックとテストの共通の口）。"""
        if 0 <= row < len(self._related_paths):
            self.note_activated.emit(self._related_paths[row])

    def begin(self) -> None:
        """頼んだところ。**前の答えは消す**（混ざると読めない）。"""
        self._running = True
        self.set_related([])
        self._output.setPlainText("")
        self._status.setText(WAITING)
        self._refresh_buttons()

    def append(self, chunk: str) -> None:
        """届いたぶんを足す。最初の 1 文字で「読んでいます」を消す。"""
        if not chunk:
            return
        self._status.setText("")
        cursor = self._output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._output.setTextCursor(cursor)

    def finish(self) -> None:
        self._running = False
        if self._status.text() == WAITING:
            self._status.setText("")
        self._refresh_buttons()

    def cancel(self) -> None:
        """止めたとき。**書きかけは残す**（そこまでは読める）。"""
        self._running = False
        self._status.setText(STOPPED)
        self._refresh_buttons()

    def fail(self, reason: str) -> None:
        """うまくいかなかった。**黙って何も出さないのがいちばん分かりにくい。**"""
        self._running = False
        self._status.setText(reason)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        can_ask = self._available and not self._running
        self._summary.setEnabled(can_ask)
        self._review.setEnabled(can_ask)
        # **関連は索引を引くだけ。** Ollama の有無に関係なく押せる（L-3）
        self._related.setEnabled(not self._running)
        self._stop.setEnabled(self._running)

    # ------------------------------------------------------------------ 見た目

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._output.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.background}; "
            f"color: {theme.foreground}; border: none; padding: 4px 8px; }}"
        )
        self._notes.setStyleSheet(
            f"QListWidget {{ background: {theme.background}; "
            f"color: {theme.foreground}; border: none; }}"
            f"QListWidget::item {{ padding: 3px 8px; }}"
            f"QListWidget::item:selected {{ background: {theme.selection_background}; }}"
        )
        self._status.setStyleSheet(
            f"QLabel {{ background: {theme.background}; "
            f"color: {theme.muted_foreground}; padding: 0 8px 4px 8px; }}"
        )
