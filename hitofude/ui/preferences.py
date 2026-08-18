"""環境設定（spec §5.4）。

フォント / テーマ / 保管フォルダ / ゴミ箱の保持日数。

**保管フォルダの変更は再起動が要る**ことを画面に出す。索引も監視も
起動時に開いた vault に紐づいているため、黙って切り替えると
「一覧が更新されない」という分かりにくい壊れ方をする。
"""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from hitofude.config import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_MONO_FAMILY,
    DEFAULT_POINT_SIZE,
    DEFAULT_TAB_WIDTH,
    DEFAULT_TRASH_DAYS,
    MAX_POINT_SIZE,
    MAX_TAB_WIDTH,
    MIN_POINT_SIZE,
    MIN_TAB_WIDTH,
    Config,
    ContentWidth,
    LineSpacing,
)
from hitofude.theme import ThemeMode

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

# 行と行、ラベルと入力欄のあいだ（ユーザー指摘）。既定の 6px では詰まって
# 見えた。項目が 8 つ並ぶので、ここが効く
FORM_SPACING = 10
# ダイアログの外周
DIALOG_MARGIN = 20
# 保管フォルダの表示幅。**パスの長さでダイアログの形を決めない。**
# 深い場所を選ぶと窓が横に伸びるか、収まらない文字が潰れる（ユーザー指摘）
VAULT_LABEL_WIDTH = 260
# タブ幅の入力欄。1 桁ぶん + 矢印が収まればよい
TAB_WIDTH_FIELD = 70


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


class PreferencesDialog(QDialog):
    applied = Signal()
    """設定が書き込まれたあとに飛ぶ。呼び出し側が見た目を更新する。"""

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("環境設定")
        self.setMinimumWidth(420)

        form = QFormLayout()
        form.setVerticalSpacing(FORM_SPACING)
        form.setHorizontalSpacing(FORM_SPACING)

        self._font = QFontComboBox(self)
        self._font.setCurrentText(config.font_family)
        form.addRow("本文フォント", self._font)

        self._size = QDoubleSpinBox(self)
        self._size.setRange(MIN_POINT_SIZE, MAX_POINT_SIZE)
        self._size.setSingleStep(0.5)
        self._size.setSuffix(" pt")
        self._size.setValue(config.font_point_size)
        form.addRow("文字サイズ", self._size)

        self._mono = QFontComboBox(self)
        self._mono.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self._mono.setCurrentText(config.mono_family)
        form.addRow("等幅フォント", self._mono)

        self._tab_width = QSpinBox(self)
        self._tab_width.setRange(MIN_TAB_WIDTH, MAX_TAB_WIDTH)
        self._tab_width.setValue(config.tab_width)
        self._tab_width.setToolTip("タブを何文字ぶんの幅で見せるか。書いた文字は変わりません。")
        # **単位を接尾辞にしない。** `setSuffix(" 文字")` だと矢印が「文字」の
        # 右に付いて数字から離れる（ユーザー要望）。数字と単位を分け、
        # 矢印は数字のすぐ横に置く
        self._tab_width.setMaximumWidth(TAB_WIDTH_FIELD)
        tab_row = QHBoxLayout()
        tab_row.addWidget(self._tab_width)
        tab_row.addWidget(QLabel("文字", self))
        tab_row.addStretch(1)
        form.addRow("タブ幅", tab_row)

        self._spacing = QComboBox(self)
        for spacing, label in SPACING_LABELS.items():
            self._spacing.addItem(label, spacing)
        self._spacing.setCurrentIndex(self._spacing.findData(config.line_spacing))
        self._spacing.setToolTip("一覧とサイドバーの行の間隔。本文には効きません。")
        form.addRow("行間", self._spacing)

        self._content_width = QComboBox(self)
        for width, label in WIDTH_LABELS.items():
            self._content_width.addItem(label, width)
        self._content_width.setCurrentIndex(self._content_width.findData(config.content_width))
        self._content_width.setToolTip("本文の最大幅。表の桁数と画像の大きさも一緒に変わります。")
        form.addRow("本文の幅", self._content_width)

        self._theme = QComboBox(self)
        for mode, label in THEME_LABELS.items():
            self._theme.addItem(label, mode)
        self._theme.setCurrentIndex(self._theme.findData(config.theme_mode))
        form.addRow("テーマ", self._theme)

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
        vault_row.addWidget(self._vault_label)
        # **ボタンは他の欄と同じ右端に置く。** 場所の文字数で位置が動くと、
        # 行ごとに右端がばらついて落ち着かない
        vault_row.addStretch(1)
        vault_row.addWidget(self._vault_button)
        form.addRow("保管フォルダ", vault_row)

        self._trash_days = QSpinBox(self)
        self._trash_days.setRange(1, MAX_TRASH_DAYS)
        self._trash_days.setSuffix(" 日")
        self._trash_days.setValue(config.trash_days)
        form.addRow("ゴミ箱の保持", self._trash_days)

        self._restart_note = QLabel("保管フォルダの変更は再起動後に反映されます。", self)
        self._restart_note.setVisible(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # `ResetRole` に置くと OS の作法どおり左端へ並ぶ
        self._reset = buttons.addButton("デフォルトに戻す", QDialogButtonBox.ButtonRole.ResetRole)
        self._reset.setToolTip(
            "フォント・行間・タブ幅・テーマ・ゴミ箱の保持を既定へ戻します（保管フォルダはそのまま）"
        )
        self._reset.clicked.connect(self.reset_to_defaults)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(FORM_SPACING + 2)
        layout.addLayout(form)
        layout.addWidget(self._restart_note)
        layout.addWidget(buttons)

        self._pending_vault: Path | None = None

    # ------------------------------------------------------------------ 参照

    @property
    def reset_button(self) -> QPushButton:
        return self._reset

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
        self._spacing.setCurrentIndex(self._spacing.findData(LineSpacing.NORMAL))
        self._content_width.setCurrentIndex(self._content_width.findData(ContentWidth.STANDARD))

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
        vault = self._accept_typed_vault()
        if vault is None:
            return False
        if vault != self._config.vault_path:
            self._config.vault_path = vault
        self._config.sync()
        self.applied.emit()
        return True
