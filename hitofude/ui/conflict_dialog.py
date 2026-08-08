"""競合ダイアログ（spec §7.5）。

外部エディタとアプリの双方がノートを変更したときに、どちらを採るか尋ねる。
**既定は「両方残す」**。どちらかを黙って捨てる選択肢を既定にすると、
一度の押し間違いで書いた内容が消える。
"""

from enum import Enum, auto
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


class Resolution(Enum):
    KEEP_BOTH = auto()
    """自分の版を `名前 (競合 日付).md` として別に保存する。"""

    TAKE_EXTERNAL = auto()
    """外部の変更を採り、自分の編集を捨てる。"""

    TAKE_MINE = auto()
    """自分の版で上書きし、外部の変更を捨てる。"""

    CANCEL = auto()
    """何もしない。"""


class ConflictDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("変更が競合しました")
        self._resolution = Resolution.CANCEL

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"「{path.name}」は、このアプリの外でも変更されています。"))
        layout.addWidget(QLabel("どちらの内容を残しますか？"))

        buttons = QDialogButtonBox(self)
        # 既定（Enter で選ばれる）を「両方残す」にする。
        # 押し間違いで書いたものが消えないようにするため
        self._keep_both = buttons.addButton("両方残す", QDialogButtonBox.ButtonRole.AcceptRole)
        self._take_external = buttons.addButton(
            "外部の変更を採用", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self._take_mine = buttons.addButton(
            "自分の版を採用", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._keep_both.setDefault(True)

        buttons.clicked.connect(self._on_clicked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def resolution(self) -> Resolution:
        return self._resolution

    def _on_clicked(self, button) -> None:
        match button:
            case self._keep_both:
                self._resolution = Resolution.KEEP_BOTH
            case self._take_external:
                self._resolution = Resolution.TAKE_EXTERNAL
            case self._take_mine:
                self._resolution = Resolution.TAKE_MINE
            case _:
                return  # Cancel は rejected 側で処理する
        self.accept()
