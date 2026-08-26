"""表の大きさを聞く小さな窓（ユーザー要望 2026-08-26）。

ツールバーの「表」ボタンと「編集」→「表を作る…」から開く。
`QInputDialog` は 1 つしか聞けないので、行と列の 2 つを並べるために
自前で組む。**聞くだけ**——作るのは `core/table.new_table`。

行の数は**見出しを除いた本体の行数**。数え方が食い違うと 1 行ずれた表が
できるので、窓の中でも一言で示す（`hint()`）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

DEFAULT_ROWS = 3
DEFAULT_COLUMNS = 3
# 上限は「押して作る」大きさの範囲。これを超える表は貼り付けか読み込みで来る
MAX_ROWS = 50
MAX_COLUMNS = 20

HINT = "見出しの行は別に付きます。"

# 数字の欄。設定画面（`preferences.UNIT_FIELD`）と同じ考えで、
# 単位のラベルを欄の外に置き、数字は右へ寄せる
FIELD_WIDTH = 82


class TableSizeDialog(QDialog):
    """行と列の数を聞く。`exec()` が受け入れなら `values()` を読む。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("表を作る")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._rows = self._number(DEFAULT_ROWS, MAX_ROWS)
        self._columns = self._number(DEFAULT_COLUMNS, MAX_COLUMNS)
        # **単位は付けない。** ラベルが「行」なので、欄の右にもう一度
        # 「行」と置くと同じ言葉が 2 度出る（設定画面の pt や 日 とは違う）
        form.addRow(QLabel("行"), self._rows)
        form.addRow(QLabel("列"), self._columns)
        layout.addLayout(form)

        self._hint = QLabel(HINT, self)
        self._hint.setEnabled(False)  # 読み飛ばせるように色を落とす
        layout.addWidget(self._hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("作る")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ 参照

    def values(self) -> tuple[int, int]:
        """`(行, 列)`。行は見出しを除いた本体の行数。"""
        return self._rows.value(), self._columns.value()

    def set_values(self, *, rows: int, columns: int) -> None:
        self._rows.setValue(rows)
        self._columns.setValue(columns)

    def hint(self) -> str:
        return self._hint.text()

    # ---------------------------------------------------------------- 組み立て

    def _number(self, value: int, maximum: int) -> QSpinBox:
        found = QSpinBox(self)
        found.setRange(1, maximum)
        found.setValue(value)
        found.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        found.setFixedWidth(FIELD_WIDTH)
        return found
