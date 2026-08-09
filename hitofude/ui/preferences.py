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
)
from hitofude.theme import ThemeMode

THEME_LABELS = {
    ThemeMode.SYSTEM: "システムに合わせる",
    ThemeMode.LIGHT: "ライト",
    ThemeMode.DARK: "ダーク",
}

MAX_TRASH_DAYS = 3650
# タブ幅の入力欄。1 桁ぶん + 矢印が収まればよい
TAB_WIDTH_FIELD = 70


class PreferencesDialog(QDialog):
    applied = Signal()
    """設定が書き込まれたあとに飛ぶ。呼び出し側が見た目を更新する。"""

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("環境設定")
        self.setMinimumWidth(420)

        form = QFormLayout()

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

        self._theme = QComboBox(self)
        for mode, label in THEME_LABELS.items():
            self._theme.addItem(label, mode)
        self._theme.setCurrentIndex(self._theme.findData(config.theme_mode))
        form.addRow("テーマ", self._theme)

        self._vault_label = QLabel(str(config.vault_path), self)
        self._vault_label.setWordWrap(True)
        self._vault_button = QPushButton("変更…", self)
        self._vault_button.clicked.connect(self._choose_vault)
        vault_row = QHBoxLayout()
        vault_row.addWidget(self._vault_label, 1)
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
            "フォント・タブ幅・テーマ・ゴミ箱の保持を既定へ戻します（保管フォルダはそのまま）"
        )
        self._reset.clicked.connect(self.reset_to_defaults)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._restart_note)
        layout.addWidget(buttons)

        self._pending_vault: Path | None = None

    # ------------------------------------------------------------------ 参照

    @property
    def reset_button(self) -> QPushButton:
        return self._reset

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
        self._vault_label.setText(str(path))
        self._restart_note.setVisible(path != self._config.vault_path)

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

    def accept(self) -> None:
        self.apply()
        super().accept()

    def apply(self) -> None:
        """入力内容を設定へ書き込む。"""
        self._config.font_family = self._font.currentText()
        self._config.font_point_size = self._size.value()
        self._config.mono_family = self._mono.currentText()
        self._config.theme_mode = self.selected_theme
        self._config.tab_width = self._tab_width.value()
        self._config.trash_days = self._trash_days.value()
        if self._pending_vault is not None:
            self._config.vault_path = self._pending_vault
        self._config.sync()
        self.applied.emit()
