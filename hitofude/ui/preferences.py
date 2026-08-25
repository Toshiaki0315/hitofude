"""設定（spec §5.4 では「環境設定」。画面の言葉は「設定」で揃える）。

フォント / テーマ / 保管フォルダ / ゴミ箱の保持日数。

**保管フォルダの変更は再起動が要る**ことを画面に出す。索引も監視も
起動時に開いた vault に紐づいているため、黙って切り替えると
「一覧が更新されない」という分かりにくい壊れ方をする。
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hitofude.config import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_HISTORY_INTERVAL,
    DEFAULT_LLM_TIMEOUT_MINUTES,
    DEFAULT_MONO_FAMILY,
    DEFAULT_POINT_SIZE,
    DEFAULT_TAB_WIDTH,
    DEFAULT_TRASH_DAYS,
    HISTORY_INTERVAL_CHOICES,
    MAX_LLM_TIMEOUT_MINUTES,
    MAX_POINT_SIZE,
    MAX_TAB_WIDTH,
    MIN_LLM_TIMEOUT_MINUTES,
    MIN_POINT_SIZE,
    MIN_TAB_WIDTH,
    Config,
    ContentWidth,
    LineSpacing,
)
from hitofude.core.llm import (
    CONTEXT_CHOICES,
    CONTEXT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    KEEP_ALIVE_CHOICES,
    KEEP_ALIVE_MINUTES,
)
from hitofude.core.ocr import DEFAULT_ENGINE, Engine
from hitofude.theme import ThemeMode
from hitofude.ui import tooltip

THEME_LABELS = {
    ThemeMode.SYSTEM: "システムに合わせる",
    ThemeMode.LIGHT: "ライト",
    ThemeMode.DARK: "ダーク",
}

WIDTH_LABELS = {
    ContentWidth.STANDARD: "標準",
    ContentWidth.WIDE: "広め",
    ContentWidth.FULL: "最大（ウィンドウ幅）",
}

SPACING_LABELS = {
    LineSpacing.TIGHT: "詰めて",
    LineSpacing.NORMAL: "ふつう",
    LineSpacing.RELAXED: "ゆったり",
}

MAX_TRASH_DAYS = 3650

# 行と行のあいだ（ユーザー指摘 2026-08-16）。既定の 6px では詰まって見えた
ROW_SPACING = 12
# ラベルと入力欄のあいだ。**縦より横を広く取る。** 近すぎると、どのラベルが
# どの欄のものか目で追いにくい
LABEL_GAP = 16
# 節と節のあいだ（ユーザー指摘 2026-08-24）。行の間隔より広くしないと
# 切れ目が見えず、項目がのっぺり並んで見える
SECTION_GAP = 22
# 見出しと、その節の最初の行のあいだ
HEADING_GAP = 8
# ラベルの列幅。**節をまたいで入力欄の左端を揃える。** 節ごとに列幅が
# 決まると、節が変わるたび欄の位置がずれて落ち着かない
LABEL_COLUMN = 130
# 入力欄の幅。**選ぶ欄も打ち込む欄も同じ幅にする。** 中身の長さで幅が
# 決まると、右端がぎざぎざになる（参考にした画面はどれも揃っている）
FIELD_WIDTH = 300
# ダイアログの外周
DIALOG_MARGIN = 20
# 窓の最小幅。狭いと保管フォルダの欄が溢れる（487px で溢れていた）
MIN_DIALOG_WIDTH = 600
# 保管フォルダの表示幅。**パスの長さでダイアログの形を決めない。**
# 深い場所を選ぶと窓が横に伸びるか、収まらない文字が潰れる（ユーザー指摘）
VAULT_LABEL_WIDTH = FIELD_WIDTH
# 数字を打つ欄。**中身の長さで幅を決めない**（ユーザー指摘 2026-08-24）。
# `setMaximumWidth` では上限を決めるだけで欄は伸びない（伸縮しない欄は
# sizeHint のまま）。伸ばすには幅そのものを決める
NUMBER_FIELD = 110
# 単位のラベルが隣に付く欄。**数字の左に残る余りを半分に詰める**
# （ユーザー要望 2026-08-24）。単位が外に出ているぶん短くて足りる
UNIT_FIELD = 82


def _resolve_vault(text: str) -> Path | None:
    """打ち込まれた場所を `Path` にする。使えないなら `None`。

    - 前後の空白は落とす（Finder から貼ると付いてくる）
    - `~` はホームに直す
    - **相対パスは受け取らない。** どこを基準にするかが人によって違う
    - **ファイルは受け取らない**
    - **作るのは 1 階層まで。** 打ち間違えた深い道を黙って掘らない
      （フォルダ自体はアプリの起動時に作られる）
    """
    cleaned = text.strip()
    if not cleaned:
        return None

    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        return None
    if path.is_file():
        return None
    if not path.exists() and not path.parent.is_dir():
        return None
    return path


PAGE_MARGIN = 20
"""ページの内側の余白。タブの枠に文字が貼り付くと窮屈に見える。"""

SECTION_TITLE = "sectionTitle"
"""節の見出しに付ける名前。並びの検査に使う。"""

SECTION_NOTE = "sectionNote"
"""見出しの下の 1 行に付ける名前。"""

LLM_NOTE = "（送り先は 127.0.0.1 に固定）"
"""**外へ出さないことがこの機能の前提**（ADR-0025 の 3）。画面でも明示する。"""


def _form() -> QFormLayout:
    """節 1 つぶんの行の並び。間隔とラベルの寄せ方をここで揃える。"""
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setVerticalSpacing(ROW_SPACING)
    form.setHorizontalSpacing(LABEL_GAP)
    # ラベルは左揃え。**幅を決めた枠の中で左に置くほうが、日本語では
    # 読み始めの位置が揃って探しやすい**（右揃えだと語尾で揃う）
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return form


def _label(text: str) -> QLabel:
    """行のラベル。**幅を決め打ちして節をまたいで列を揃える。**"""
    label = QLabel(text)
    label.setMinimumWidth(LABEL_COLUMN)
    return label


def _with_unit(widget: QAbstractSpinBox, unit: str, parent: QWidget) -> QHBoxLayout:
    """数字の欄と単位のラベル。

    **単位を接尾辞にしない**（矢印が単位の右に付いて数字から離れる）。
    **数字は右に寄せる**（ユーザー要望 2026-08-24）。欄を長くしたので、
    左に寄せたままだと数字と単位のあいだが空いて別々のものに見える。
    """
    widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    widget.setFixedWidth(UNIT_FIELD)
    row = QHBoxLayout()
    row.addWidget(widget)
    row.addWidget(QLabel(unit, parent))
    row.addStretch(1)
    return row


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(SECTION_TITLE)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def _note(text: str) -> QLabel:
    """見出しの下の 1 行。**色を落として本文と区別する**（読み飛ばせるように）。

    配色は決め打ちしない。パレットの「使えない文字」の色を借りれば、
    明るいテーマでも暗いテーマでも本文より薄くなる。
    """
    label = QLabel(text)
    label.setObjectName(SECTION_NOTE)
    label.setWordWrap(True)
    palette = label.palette()
    palette.setColor(
        QPalette.ColorRole.WindowText,
        palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText),
    )
    label.setPalette(palette)
    return label


def _page(sections: list[tuple[str, str, QFormLayout]]) -> tuple[QWidget, list[tuple[str, str]]]:
    """節をいくつか積んで 1 ページにする（ユーザー要望 2026-08-24）。

    **節ごとにウィジェットで包まない。** 包むと入力欄の `parentWidget()` が
    節になり、「この欄はどのページのものか」が辿れなくなる（テストが見て
    いる）。包むのはレイアウトだけにして、欄はページの直下に置く。

    **余白はページ側で取る**（タブの枠に文字が貼り付くと窮屈に見える）。
    """
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    layout.setSpacing(HEADING_GAP)
    written: list[tuple[str, str]] = []
    for index, (title, note, form) in enumerate(sections):
        if index:
            layout.addSpacing(SECTION_GAP)
        layout.addWidget(_heading(title))
        layout.addWidget(_note(note))
        layout.addLayout(form)
        written.append((title, note))
    layout.addStretch(1)
    return page, written


class PreferencesDialog(QDialog):
    applied = Signal()
    """設定が書き込まれたあとに飛ぶ。呼び出し側が見た目を更新する。"""

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        *,
        models: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("設定")
        self.setMinimumWidth(MIN_DIALOG_WIDTH)

        # ---------------------------------------------------- 本文の見え方
        text_form = _form()

        self._font = QFontComboBox(self)
        self._font.setMinimumWidth(FIELD_WIDTH)
        self._font.setCurrentText(config.font_family)
        text_form.addRow(_label("本文フォント"), self._font)

        self._size = QDoubleSpinBox(self)
        self._size.setRange(MIN_POINT_SIZE, MAX_POINT_SIZE)
        self._size.setSingleStep(0.5)
        # **単位は欄の外**（ユーザー要望 2026-08-24）。接尾辞にすると矢印が
        # 「pt」の右に付いて数字から離れる。タブ幅で先に直したのと同じ形
        self._size.setValue(config.font_point_size)
        text_form.addRow(_label("文字サイズ"), _with_unit(self._size, "pt", self))

        self._mono = QFontComboBox(self)
        self._mono.setMinimumWidth(FIELD_WIDTH)
        self._mono.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self._mono.setCurrentText(config.mono_family)
        text_form.addRow(_label("等幅フォント"), self._mono)

        self._content_width = QComboBox(self)
        self._content_width.setMinimumWidth(FIELD_WIDTH)
        for width, label in WIDTH_LABELS.items():
            self._content_width.addItem(label, width)
        self._content_width.setCurrentIndex(self._content_width.findData(config.content_width))
        self._content_width.setToolTip("本文の最大幅。表の桁数と画像の大きさも一緒に変わります。")
        text_form.addRow(_label("本文の幅"), self._content_width)

        self._tab_width = QSpinBox(self)
        self._tab_width.setRange(MIN_TAB_WIDTH, MAX_TAB_WIDTH)
        self._tab_width.setValue(config.tab_width)
        self._tab_width.setToolTip("タブを何文字ぶんの幅で見せるか。書いた文字は変わりません。")
        text_form.addRow(_label("タブ幅"), _with_unit(self._tab_width, "文字", self))

        # -------------------------------------------------------- ウィンドウ
        window_form = _form()

        self._theme = QComboBox(self)
        self._theme.setMinimumWidth(FIELD_WIDTH)
        for mode, label in THEME_LABELS.items():
            self._theme.addItem(label, mode)
        self._theme.setCurrentIndex(self._theme.findData(config.theme_mode))
        window_form.addRow(_label("テーマ"), self._theme)

        self._spacing = QComboBox(self)
        self._spacing.setMinimumWidth(FIELD_WIDTH)
        for spacing, label in SPACING_LABELS.items():
            self._spacing.addItem(label, spacing)
        self._spacing.setCurrentIndex(self._spacing.findData(config.line_spacing))
        self._spacing.setToolTip("一覧とサイドバーの行の間隔。本文には効きません。")
        window_form.addRow(_label("行間"), self._spacing)

        # -------------------------------------------------- ノートの置き場所
        vault_form = _form()

        # **打ち込んでも変えられる**（ユーザー要望）。「変更…」だけだと、
        # パスを貼り付けたいときに遠回りになる。入力欄なら長い場所でも
        # 窓が広がらない（中で横に流れる）
        self._vault_label = QLineEdit(self)
        self._vault_label.setFixedWidth(VAULT_LABEL_WIDTH)
        self._vault_label.setPlaceholderText("~/Documents/HitofudeNotes")
        self._vault_label.textChanged.connect(self._on_vault_typed)
        self._show_vault(config.vault_path)
        self._vault_button = QPushButton("変更…", self)
        self._vault_button.clicked.connect(self._choose_vault)
        vault_row = QHBoxLayout()
        vault_row.setSpacing(LABEL_GAP)
        vault_row.addWidget(self._vault_label)
        # **ボタンは入力欄のすぐ右。** 欄の幅は決め打ちなので、場所の文字数で
        # ボタンの位置は動かない。窓の右端まで飛ばすと、他の行の欄の右端と
        # 揃わずに 1 行だけ間延びして見える
        vault_row.addWidget(self._vault_button)
        vault_row.addStretch(1)
        vault_form.addRow(_label("保管フォルダ"), vault_row)

        self._trash_days = QSpinBox(self)
        self._trash_days.setRange(1, MAX_TRASH_DAYS)
        self._trash_days.setValue(config.trash_days)
        vault_form.addRow(_label("ゴミ箱の保持"), _with_unit(self._trash_days, "日", self))

        # 版を残す間隔（ユーザー要望 2026-08-24）。**本文の保存とは別。**
        # 本文は打ち終わって 0.8 秒で書く（§7.4）。ここで決めるのは
        # `.hitofude/history/` に何分おきに 1 版残すか
        self._history = QComboBox(self)
        self._history.setMinimumWidth(FIELD_WIDTH)
        for minutes in HISTORY_INTERVAL_CHOICES:
            self._history.addItem("なし" if minutes == 0 else f"{minutes} 分", minutes)
        self._history.setCurrentIndex(self._history.findData(config.history_interval_minutes))
        self._history.setToolTip(
            "「戻す」ために残す版の間隔。本文の保存は打ち終わって 0.8 秒後で、"
            "ここでは変わりません。「なし」は自分で保存したときだけ残します。"
        )
        vault_form.addRow(_label("履歴を残す間隔"), self._history)

        # ------------------------------------------------- ローカルLLM
        # **毛色が違うものを同じ列に並べない**（ユーザー要望）。フォントや
        # 行間は「見え方」で、ここは「誰に読ませるか」。ページを分ける
        llm_form = _form()

        # **送り先は出さない。** 相手は `127.0.0.1` に固定（ADR-0025 の 3）。
        # ここを設定に出すと「うっかり外に出す」道ができる
        self._model = QComboBox(self)
        self._model.setMinimumWidth(FIELD_WIDTH)
        self._model.setEditable(True)  # これから pull するモデルも書ける
        self._model.addItems(models if models else [config.llm_model])
        self._model.setCurrentText(config.llm_model)
        self._model.setToolTip("`ollama list` に出る名前。入っていないものも書けます。")
        llm_form.addRow(_label("モデル"), self._model)

        self._port = QSpinBox(self)
        self._port.setRange(1, 65535)
        self._port.setValue(config.llm_port)
        self._port.setFixedWidth(NUMBER_FIELD)
        self._port.setToolTip("Ollama のポート。`OLLAMA_HOST` で変えている場合はここも合わせます。")
        port_row = QHBoxLayout()
        port_row.setSpacing(LABEL_GAP)
        port_row.addWidget(self._port)
        self._llm_note = QLabel(LLM_NOTE, self)
        port_row.addWidget(self._llm_note)
        port_row.addStretch(1)
        llm_form.addRow(_label("ポート"), port_row)

        self._context = QComboBox(self)
        self._context.setMinimumWidth(FIELD_WIDTH)
        for tokens in CONTEXT_CHOICES:
            self._context.addItem(f"{tokens // 1024}k トークン", tokens)
        self._context.setCurrentIndex(self._context.findData(config.llm_context))
        self._context.setToolTip("一度に渡せる長さ。**広げるほどメモリを食います**。")
        llm_form.addRow(_label("一度に渡す量"), self._context)

        # 応答待ち時間（ユーザー要望 2026-08-24）。**読み込みも含めて待つ。**
        # 12b で 8 秒、26b で 392 秒（実測）と桁が違うので、手元のモデルに
        # 合わせて延ばせるようにする
        self._timeout = QSpinBox(self)
        self._timeout.setRange(MIN_LLM_TIMEOUT_MINUTES, MAX_LLM_TIMEOUT_MINUTES)
        self._timeout.setValue(config.llm_timeout_minutes)
        self._timeout.setToolTip(
            "応答待ち時間。**大きいモデルは読み込みだけで数分かかります**"
            "（実測: 26b で 6 分半）。短いと途中で切れます。"
        )
        llm_form.addRow(_label("応答待ち時間"), _with_unit(self._timeout, "分", self))

        # モデルを残す時間（ユーザー報告 2026-08-24）。**抱えたままにさせない。**
        # 12b でも `llama-server` が 8.0GB を抱える（実測）
        self._keep_alive = QComboBox(self)
        self._keep_alive.setMinimumWidth(FIELD_WIDTH)
        for minutes in KEEP_ALIVE_CHOICES:
            label = "答えたらすぐ降ろす" if minutes == 0 else f"{minutes} 分"
            self._keep_alive.addItem(label, minutes)
        self._keep_alive.setCurrentIndex(self._keep_alive.findData(config.llm_keep_alive_minutes))
        self._keep_alive.setToolTip(
            "答えたあとモデルをメモリに残す長さ。**残すと次が速く、"
            "降ろすとメモリが空きます**（実測: 12b で 8.0GB、読み込み直しに 8 秒）。"
        )
        llm_form.addRow(_label("モデルを残す時間"), self._keep_alive)

        # ------------------------------------------------------ 画像とPDF
        # 画像を文字にする読み手（ADR-0027）。**選ぶ材料を画面に置く**
        ocr_form = _form()

        self._ocr = QComboBox(self)
        self._ocr.setMinimumWidth(FIELD_WIDTH)
        self._ocr.addItem("macOS（デフォルト）", Engine.MAC)
        self._ocr.addItem("ローカルLLM", Engine.LLM)
        self._ocr.setCurrentIndex(self._ocr.findData(config.ocr_engine))
        self._ocr.setToolTip("PDF や画像から文字を読み取るときに使うもの。")
        ocr_form.addRow(_label("文字の読み取り"), self._ocr)

        self._restart_note = QLabel("保管フォルダの変更は再起動後に反映されます。", self)
        self._restart_note.setVisible(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # `ResetRole` に置くと OS の作法どおり左端へ並ぶ
        self._reset = buttons.addButton("デフォルトに戻す", QDialogButtonBox.ButtonRole.ResetRole)
        self._reset.setToolTip("両方のページを既定へ戻します（保管フォルダはそのまま）")
        self._reset.clicked.connect(self.reset_to_defaults)

        general, general_sections = _page(
            [
                (
                    "本文の見え方",
                    "エディタに出る文字の形と幅。開いているノートにすぐ反映されます。",
                    text_form,
                ),
                ("ウィンドウ", "アプリ全体の配色と、一覧やサイドバーの詰まり具合。", window_form),
                (
                    "ノートの置き場所",
                    ".md ファイルを読み書きするフォルダ。変えても中のファイルは移動しません。",
                    vault_form,
                ),
            ]
        )
        assistant, assistant_sections = _page(
            [
                ("ローカルLLM", "Ollama に繋いで、要約やレビューを頼みます。", llm_form),
                (
                    "画像とPDF",
                    "取り込んだ画像や PDF から、絵の中の文字を起こすときに使うもの。",
                    ocr_form,
                ),
            ]
        )
        self._sections = [general_sections, assistant_sections]

        self._tabs = QTabWidget(self)
        self._tabs.addTab(general, "一般")
        self._tabs.addTab(assistant, "アシスタント")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(SECTION_GAP - HEADING_GAP)
        layout.addWidget(self._tabs)
        layout.addWidget(self._restart_note)
        layout.addWidget(buttons)

        self._pending_vault: Path | None = None
        # 自前のツールチップ（黒地に白・角丸）。組み終えてから 1 回
        tooltip.adopt(self)

    # ------------------------------------------------------------------ 参照

    @property
    def reset_button(self) -> QPushButton:
        return self._reset

    def sections(self, index: int) -> list[tuple[str, str]]:
        """ページの節（`(見出し, 説明)`）。**説明のない節を作らない**
        ための検査に使う。"""
        return list(self._sections[index])

    @property
    def tabs(self) -> QTabWidget:
        """ページ。**開いていないページも保存する**（`apply` は全部を見る）。"""
        return self._tabs

    @property
    def model_box(self) -> QComboBox:
        return self._model

    @property
    def port_box(self) -> QSpinBox:
        return self._port

    @property
    def context_box(self) -> QComboBox:
        return self._context

    @property
    def timeout_box(self) -> QSpinBox:
        return self._timeout

    @property
    def history_box(self) -> QComboBox:
        """版を残す間隔。**本文の保存の間隔ではない**（§7.4 は変えない）。"""
        return self._history

    @property
    def keep_alive_box(self) -> QComboBox:
        """答えたあとモデルを残す長さ。**メモリと速さの綱引き**。"""
        return self._keep_alive

    @property
    def ocr_box(self) -> QComboBox:
        return self._ocr

    def llm_note_text(self) -> str:
        return self._llm_note.text()

    @property
    def line_spacing(self) -> LineSpacing:
        """選ばれている行間。"""
        return self._spacing.currentData()

    @property
    def content_width(self) -> ContentWidth:
        """選ばれている本文の幅。"""
        return self._content_width.currentData()

    @property
    def selected_theme(self) -> ThemeMode:
        return self._theme.currentData()

    @property
    def selected_vault(self) -> Path:
        return self._pending_vault or self._config.vault_path

    # ------------------------------------------------------------------ 動作

    def _choose_vault(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "保管フォルダを選ぶ", str(self._config.vault_path)
        )
        if chosen:
            self.set_vault(Path(chosen))

    def set_vault(self, path: Path) -> None:
        """フォルダ選択の結果を反映する。ダイアログを介さず呼べるようにしてある。"""
        self._pending_vault = path
        self._show_vault(path)
        self._restart_note.setVisible(path != self._config.vault_path)

    def _show_vault(self, path: Path) -> None:
        """入力欄に場所を入れる。全文を入れ、先頭を見せる。

        **省略しない。** 打ち直す人が全部を読めないと直せない。長い場所は
        欄の中で横に流れる（窓は広がらない）。
        """
        self._vault_label.setText(str(path))
        self._vault_label.setToolTip(str(path))
        self._vault_label.setCursorPosition(0)

    def set_vault_text(self, text: str) -> None:
        """入力欄へ直に入れる（打ち込みと同じ）。"""
        self._vault_label.setText(text)

    def vault_label_text(self) -> str:
        return self._vault_label.text()

    def vault_tooltip(self) -> str:
        return self._vault_label.toolTip()

    def _on_vault_typed(self, text: str) -> None:
        self._vault_label.setToolTip(text)
        if not hasattr(self, "_restart_note"):
            return  # 組み立て中（入力欄のほうが先にできる）
        resolved = _resolve_vault(text)
        self._restart_note.setVisible(resolved is not None and resolved != self._config.vault_path)

    def _accept_typed_vault(self) -> Path | None:
        """入力欄の内容を場所として受け取る。駄目なら知らせて `None`。

        **打ち間違いを受け取らない。** 取り違えると、ノートが 1 つも無い
        フォルダを指してしまい、消えたように見える。
        """
        resolved = _resolve_vault(self._vault_label.text())
        if resolved is None:
            QMessageBox.warning(
                self,
                "保管フォルダ",
                "その場所は使えません。\n\n"
                "・`/` から始まる場所か `~/` で書いてください\n"
                "・ファイルではなくフォルダを指してください\n"
                "・作れるのは 1 階層までです（親のフォルダは先に作ってください）",
            )
            return None
        return resolved

    def reset_to_defaults(self) -> None:
        """入力欄を既定値に戻す。

        **保管フォルダは戻さない。** そこはノートの置き場であって好みの設定では
        ない。戻すと別のフォルダ（多くは空）を指すことになり、ノートが消えた
        ように見える。

        書き込むのは OK を押したとき。間違えて押しても Cancel で元に戻せる。
        """
        self._font.setCurrentText(DEFAULT_FONT_FAMILY)
        self._size.setValue(DEFAULT_POINT_SIZE)
        self._mono.setCurrentText(DEFAULT_MONO_FAMILY)
        self._theme.setCurrentIndex(self._theme.findData(ThemeMode.SYSTEM))
        self._tab_width.setValue(DEFAULT_TAB_WIDTH)
        self._trash_days.setValue(DEFAULT_TRASH_DAYS)
        self._history.setCurrentIndex(self._history.findData(DEFAULT_HISTORY_INTERVAL))
        self._spacing.setCurrentIndex(self._spacing.findData(LineSpacing.NORMAL))
        self._content_width.setCurrentIndex(self._content_width.findData(ContentWidth.STANDARD))
        self._model.setCurrentText(DEFAULT_MODEL)
        self._port.setValue(DEFAULT_PORT)
        self._context.setCurrentIndex(self._context.findData(CONTEXT_TOKENS))
        self._timeout.setValue(DEFAULT_LLM_TIMEOUT_MINUTES)
        self._keep_alive.setCurrentIndex(self._keep_alive.findData(KEEP_ALIVE_MINUTES))
        self._ocr.setCurrentIndex(self._ocr.findData(DEFAULT_ENGINE))

    def accept(self) -> None:
        """OK。**受け取れない場所なら閉じない。** 閉じると打ち直しからになる。"""
        if not self.apply():
            return
        super().accept()

    def apply(self) -> bool:
        """入力内容を設定へ書き込む。書けたら True。"""
        self._config.font_family = self._font.currentText()
        self._config.font_point_size = self._size.value()
        self._config.mono_family = self._mono.currentText()
        self._config.theme_mode = self.selected_theme
        self._config.tab_width = self._tab_width.value()
        self._config.line_spacing = self.line_spacing
        self._config.content_width = self.content_width
        self._config.trash_days = self._trash_days.value()
        self._config.history_interval_minutes = self._history.currentData()
        self._config.llm_model = self._model.currentText()
        self._config.llm_port = self._port.value()
        self._config.llm_context = self._context.currentData()
        self._config.llm_timeout_minutes = self._timeout.value()
        self._config.llm_keep_alive_minutes = self._keep_alive.currentData()
        self._config.ocr_engine = self._ocr.currentData()
        vault = self._accept_typed_vault()
        if vault is None:
            return False
        if vault != self._config.vault_path:
            self._config.vault_path = vault
        self._config.sync()
        self.applied.emit()
        return True
