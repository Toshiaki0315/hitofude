"""ローカルLLM の答えを出すペイン（L-1 / [ADR-0025](../../docs/adr/0025-local-llm.md)）。

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
    QLineEdit,
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

QUESTION_HINT = "ノート全体に質問する（例: 予算の話はどこ？）"

NO_SOURCES = "手がかりになるノートが見つかりませんでした。\n言葉を変えて試してください。"

SOURCES_CAPTION = "出典（この中だけを読ませています。押すと開きます）"
"""**題名だけが並んでも、それが何なのか分からない**（ユーザー報告）。"""

# 題名と理由のあいだ。理由どうしは `/` で繋ぐ
MAX_ROWS = 6
"""一覧に見せる行数の上限。**欄いっぱいに伸びると答えが見えない。**"""

REASON_MARK = " — "
REASON_JOIN = " / "


def _where(path) -> str:
    """置き場所を短く。**拡張子は出さない**（一覧でも出していない）。"""
    from pathlib import Path

    return Path(str(path)).with_suffix("").as_posix()


class AssistantPane(QWidget):
    requested = Signal(object)
    """押された `Task`。**読ませるのは呼び出し側**（ここは本文を知らない）。"""

    stopped = Signal()
    """「止める」が押された。"""

    related_requested = Signal()
    """「関連」が押された。**探すのは呼び出し側**（索引を引く）。"""

    note_activated = Signal(object)
    """関連ノート・出典の相対 `Path`。**開くのは呼び出し側**。"""

    question_asked = Signal(str)
    """打たれた質問（L-2）。**探して読ませるのは呼び出し側**。"""

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
            # **クリックでは奪わない。** 押した直後に本文へ打ち続けられる。
            # Tab で回るのは macOS の「フル キーボード アクセス」を入れた
            # ときだけ（既定では回らない。ユーザー報告で確認）
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
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

        # vault 全体への質問（L-2）。**打って Enter** が自然（検索欄と同じ）
        self._question = QLineEdit(self)
        self._question.setPlaceholderText(QUESTION_HINT)
        self._question.returnPressed.connect(self._on_question)
        self._ask = QPushButton("質問", self)
        self._ask.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._ask.clicked.connect(self._on_question)
        # **空の質問では押せない**（押しても何も起きないボタンを押させない）
        self._question.textChanged.connect(lambda _text: self._refresh_buttons())

        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)  # 直すなら本文で直す（版の履歴と同じ）
        self._output.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        # 折り返して読む。横棒が出ると 2 方向へ動かすことになる
        self._output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
        asking = QHBoxLayout()
        asking.setContentsMargins(8, 0, 8, 6)
        asking.setSpacing(6)
        asking.addWidget(self._question, 1)
        asking.addWidget(self._ask)

        layout.addLayout(buttons)
        layout.addLayout(asking)
        layout.addWidget(self._status)
        layout.addWidget(self._notes)
        layout.addWidget(self._output, 1)

        # 回るときの順は**上から下・左から右**（作った順だと「止める」が
        # 質問欄より前に来る）。macOS の既定では Tab はボタンへ行かないので、
        # 効くのは「フル キーボード アクセス」を入れている人だけ
        for previous, following in (
            (self._summary, self._review),
            (self._review, self._related),
            (self._related, self._stop),
            (self._stop, self._question),
            (self._question, self._ask),
        ):
            self.setTabOrder(previous, following)

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
    def ask_button(self) -> QPushButton:
        return self._ask

    @property
    def question_box(self) -> QLineEdit:
        return self._question

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

    @property
    def output(self) -> QPlainTextEdit:
        return self._output

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
        self._fill_notes(found, NO_RELATED)

    def _fill_notes(self, found, empty_notice: str) -> None:
        self._notes.clear()
        self._related_paths = [path for path, _title, _reasons in found]
        for _path, title, reasons in found:
            label = f"{title}{REASON_MARK}{REASON_JOIN.join(reasons)}" if reasons else title
            item = QListWidgetItem(label)
            item.setToolTip(label)
            self._notes.addItem(item)
        self._notes.setVisible(bool(found))
        # **件数に合わせて縮む。** 1 件のために欄の半分を使わない
        row = self._notes.sizeHintForRow(0) if found else 0
        self._notes.setMaximumHeight(row * min(len(found), MAX_ROWS) + 4)
        self._status.setText("" if found else empty_notice)

    def set_sources(self, found: list[tuple[object, str]]) -> None:
        """答えの材料にしたノート（L-2）。**出典はこちらが出す。**

        モデルに題名を書かせると、渡していないノートを作文することがある。
        **実際に渡したものだけ**をここに並べる。押せば開く。

        **同じ題名が並んだら置き場所を添える。** 実機で「Hitofude の使い方」
        が 2 行並び、どちらのことか分からなかった（ユーザー報告）。
        見分けが付くなら題名だけにする（要らない情報を足さない）。
        """
        titles = [title for _path, title in found]
        rows = [
            (path, title, (_where(path),) if titles.count(title) > 1 else ())
            for path, title in found
        ]
        self._fill_notes(rows, NO_SOURCES)
        if found:
            self._status.setText(SOURCES_CAPTION)

    def _on_question(self) -> None:
        asked = self._question.text().strip()
        if asked:  # **空の質問で GPU を回さない**
            self.question_asked.emit(asked)

    def activate_related(self, row: int) -> None:
        """その行を押したことにする（クリックとテストの共通の口）。"""
        if 0 <= row < len(self._related_paths):
            self.note_activated.emit(self._related_paths[row])

    def begin(self, *, keep_notes: bool = False) -> None:
        """頼んだところ。**前の答えは消す**（混ざると読めない）。

        質問（L-2）のときは**出典を残す**（後から並べ直すと、答えより先に
        材料が消えて何を見ているのか分からなくなる）。
        """
        self._running = True
        if not keep_notes:
            self.set_related([])
        self._output.setPlainText("")
        if not (keep_notes and self._caption_kept()):
            self._status.setText(WAITING)
        self._refresh_buttons()

    def append(self, chunk: str) -> None:
        """届いたぶんを足す。最初の 1 文字で「読んでいます」を消す。

        **出典の見出しは消さない。** 何を見て答えているかは、読んでいる
        あいだずっと要る。
        """
        if not chunk:
            return
        if self._status.text() == WAITING:
            self._status.setText("")
        cursor = self._output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._output.setTextCursor(cursor)

    def _caption_kept(self) -> bool:
        return self._status.text() == SOURCES_CAPTION

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

    def set_status(self, text: str) -> None:
        """待っている間の一言を差し替える（「読み込んでいます…」など）。

        **答えそのものではない。** 届いた言葉（`append`）は別に出る。
        """
        self._status.setText(text)

    def fail(self, reason: str) -> None:
        """うまくいかなかった。**黙って何も出さないのがいちばん分かりにくい。**"""
        self._running = False
        self._status.setText(reason)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        can_ask = self._available and not self._running
        self._summary.setEnabled(can_ask)
        self._review.setEnabled(can_ask)
        self._question.setEnabled(can_ask)
        self._ask.setEnabled(can_ask and bool(self._question.text().strip()))
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
        # **答えと地続きに見えない**ように薄い面を敷く（ユーザー要望）。
        # 色は増やさず、既にあるもの（タグの面と罫線）を使い回す
        self._notes.setStyleSheet(
            f"QListWidget {{ background: {theme.tag_background}; "
            f"color: {theme.foreground}; border: none; "
            f"border-bottom: 1px solid {theme.rule}; }}"
            f"QListWidget::item {{ padding: 3px 8px; }}"
            f"QListWidget::item:selected {{ background: {theme.selection_background}; }}"
        )
        self._question.setStyleSheet(
            f"QLineEdit {{ background: {theme.background}; color: {theme.foreground}; "
            f"border: 1px solid {theme.rule}; border-radius: 5px; padding: 3px 6px; }}"
        )
        self._status.setStyleSheet(
            f"QLabel {{ background: {theme.background}; "
            f"color: {theme.muted_foreground}; padding: 0 8px 4px 8px; }}"
        )
