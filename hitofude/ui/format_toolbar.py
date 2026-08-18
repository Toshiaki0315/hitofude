"""書式ツールバー（B-1 / ユーザー要望）。

エディタの上に置くアイコンのボタン列。太字・箇条書きなどを、
ショートカットを覚えていなくても押せるようにする。

**ここは配線に徹する。** 変換そのものは `editor/commands.py` の純関数と
`MarkdownEditor` のメソッドが持っていて、ツールバーはそれを呼ぶだけ。
同じ操作にメニュー・ショートカット・ボタンの 3 つの入口ができるが、
中身が 1 つなら食い違わない。

**ボタンはフォーカスを受け取らない**（`NoFocus`）。受け取ると本文の選択が
外れ、囲むものが無くなって空振りする。ツールバーの実装でいちばん壊れやすい
のがここで、`tests/ui/test_format_toolbar.py::TestFocus` が固定している。
"""

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget

from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.icons import TOOLBAR_SCALE, Glyph, glyph_icon

# 元の寸法。実際に使うのは `TOOLBAR_SCALE` を掛けたほう
BASE_ICON_SIZE = 18
BASE_BUTTON_SIZE = 26
BASE_BAR_MARGIN = 6

ICON_SIZE = round(BASE_ICON_SIZE * TOOLBAR_SCALE)
BUTTON_SIZE = round(BASE_BUTTON_SIZE * TOOLBAR_SCALE)
BAR_MARGIN = round(BASE_BAR_MARGIN * TOOLBAR_SCALE)
# ボタンの上下。枠だけ広げても見やすくならないので、余白も一緒に伸ばす
BAR_PADDING = round(3 * TOOLBAR_SCALE)

# バーの高さ。**一覧側の上のバーもこれに揃える**（左右に並んで見えるので、
# 高さが違うと段差になって目に付く。ユーザー要望）
BAR_HEIGHT = BUTTON_SIZE + BAR_PADDING * 2

# ボタンの枠の丸み（ユーザー要望）。**一覧の上のボタンとも揃える**ので、
# 値はここに置いて向こうから引く（別々に書くと丸みが食い違う）
BUTTON_RADIUS = 5
# 生の Markdown を出す切り替え（ユーザー要望）。中身はソースモード
RAW_LABEL = "Raw"
# 本文との境目。ペインの区切り（`QSplitter::handle`）と同じ太さに揃える
RULE_HEIGHT = 1


@dataclass(frozen=True, slots=True)
class FormatAction:
    glyph: Glyph
    label: str
    method: str
    """`MarkdownEditor` のメソッド名。実在するかは `TestButtons` が見る。"""

    shortcut: str = ""
    """表示のみ。登録は `ui/menus.py` の仕事で、ここでは二重に登録しない。"""


class FormatToolbar(QWidget):
    # 並びは「文字の装飾 → 行の書式 → 差し込むもの」。押す頻度の高い順ではなく
    # 種類でまとめる。目で探すとき、ひとかたまりになっているほうが早い
    ACTIONS = (
        FormatAction(Glyph.BOLD, "太字", "toggle_strong", "⌘B"),
        FormatAction(Glyph.ITALIC, "斜体", "toggle_emphasis", "⌘I"),
        FormatAction(Glyph.STRIKE, "打ち消し", "toggle_strike", "⌘⇧X"),
        FormatAction(Glyph.CODE, "コード", "toggle_code", "⌘E"),
        FormatAction(Glyph.MARKER, "マーカー", "toggle_highlight", "⌘⇧H"),
        FormatAction(Glyph.HEADING, "見出し", "cycle_heading"),
        FormatAction(Glyph.BULLET, "箇条書き", "toggle_bullet"),
        FormatAction(Glyph.ORDERED, "番号付き", "toggle_ordered"),
        FormatAction(Glyph.CHECKBOX, "チェックボックス", "toggle_checkbox", "⌘⇧T"),
        FormatAction(Glyph.QUOTE, "引用", "toggle_quote"),
        FormatAction(Glyph.LINK, "リンク", "insert_link", "⌘K"),
    )

    # 区切り線を入れる位置（この番号のボタンの手前）。種類の切れ目
    SEPARATORS = (5, 10)

    def __init__(
        self, editor, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._theme = theme
        self._buttons: list[QToolButton] = []
        self._separators: list[QFrame] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(BAR_MARGIN, BAR_PADDING, BAR_MARGIN, BAR_PADDING)
        layout.setSpacing(2)

        for index, action in enumerate(self.ACTIONS):
            if index in self.SEPARATORS:
                layout.addWidget(self._separator())
            layout.addWidget(self._button(action))
        layout.addStretch(1)

        # **右端に離して置く。** 書式を付けるボタンとは役割が違い、
        # 押しっぱなしにする性質のもの（ユーザー要望）
        self._raw = QToolButton(self)
        # **Raw だけ取り残さない**（ユーザー指摘）。同じバーに並んでいるので、
        # 1 つだけ元の大きさだと不揃いが目に付く。こちらは絵ではなく文字なので
        # 字の大きさで効かせ、高さだけ他のボタンと揃える（幅は文字数で決まる）
        raw_font = QFont(self.font())
        raw_font.setPointSizeF(raw_font.pointSizeF() * TOOLBAR_SCALE)
        self._raw.setFont(raw_font)
        self._raw.setFixedHeight(BUTTON_SIZE)
        self._raw.setText(RAW_LABEL)
        self._raw.setCheckable(True)
        self._raw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._raw.setToolTip("Markdown の記号を出して直す（⌘/）")
        self._raw.setAccessibleName(RAW_LABEL)
        self._raw.clicked.connect(lambda checked: self._editor.set_source_mode(checked))
        self._editor.source_mode_changed.connect(self._raw.setChecked)
        layout.addWidget(self._raw)

        # メニューを開く歯車（ユーザー要望）。メニューバーまで手を伸ばさずに
        # 済む入口。**中身はここでは決めない。** ツールバーはエディタしか
        # 知らない層なので、メニューはウィンドウ側が挿す（`menus.build_gear_menu`）
        self._menu_button = QToolButton(self)
        self._menu_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._menu_button.setFixedSize(BUTTON_SIZE + 8, BUTTON_SIZE)
        self._menu_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_button.setToolTip("メニュー")
        self._menu_button.setAccessibleName("メニュー")
        layout.addWidget(self._menu_button)

        self._apply_theme()

    # ------------------------------------------------------------------ 参照

    def buttons(self) -> list[QToolButton]:
        return list(self._buttons)

    @property
    def raw_button(self) -> QToolButton:
        return self._raw

    @property
    def menu_button(self) -> QToolButton:
        return self._menu_button

    # ------------------------------------------------------------------ 見た目

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._apply_theme()

    def rule_height(self) -> int:
        return RULE_HEIGHT

    def rule_color(self) -> str:
        return self._theme.rule

    def paintEvent(self, event) -> None:
        """下端に 1px の線を引く。

        **QSS の `border-bottom` にしない。** ボタンにも書式を当てているので、
        同じシートで枠を足すと子まで巻き込む。ここは 1 本引くだけ。
        """
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(
            0, self.height() - RULE_HEIGHT, self.width(), RULE_HEIGHT, QColor(self._theme.rule)
        )
        painter.end()

    def _apply_theme(self) -> None:
        for action, found in zip(self.ACTIONS, self._buttons, strict=True):
            found.setIcon(glyph_icon(action.glyph, self._theme.foreground))
        for line in self._separators:
            line.setStyleSheet(f"color: {self._theme.rule};")
        self._menu_button.setIcon(glyph_icon(Glyph.GEAR, self._theme.foreground))
        self.setStyleSheet(
            f"QWidget {{ background: {self._theme.background}; }}"
            # **薄い枠を付ける**（ユーザー要望）。押せる場所がどこまでかが
            # 分かる。色は罫線と同じものを使う（同じ役目の線に色を増やさない）
            f"QToolButton {{ border: 1px solid {self._theme.rule}; "
            f"border-radius: {BUTTON_RADIUS}px; padding: 2px 6px; }}"
            f"QToolButton:hover {{ background: {self._theme.selection_background}; }}"
            # 押しっぱなしの状態が見えないと、今どちらのモードか分からない
            f"QToolButton:checked {{ background: {self._theme.selection_background}; "
            f"color: {self._theme.foreground}; }}"
            # 歯車の右に付く小さな矢印を消す。絵が 2 つ並ぶと窮屈になる
            "QToolButton::menu-indicator { image: none; }"
        )

    # ------------------------------------------------------------------ 組み立て

    def _button(self, action: FormatAction) -> QToolButton:
        found = QToolButton(self)
        found.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        found.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        # **押しても本文の選択を外さない。** 外すと囲むものが無くなる
        found.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        found.setToolTip(
            f"{action.label}（{action.shortcut}）" if action.shortcut else action.label
        )
        found.setAccessibleName(action.label)
        found.clicked.connect(lambda _=False, name=action.method: self._run(name))
        self._buttons.append(found)
        return found

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedHeight(BUTTON_SIZE - 8)
        self._separators.append(line)
        return line

    def _run(self, method: str) -> None:
        getattr(self._editor, method)()
        # フォーカスは既にエディタにあるはずだが、押す前にどこか別の場所
        # （検索欄など）に居た場合はここで戻す。打ち続けられるようにする
        self._editor.setFocus()
