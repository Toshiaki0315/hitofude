"""版を選んで戻す画面（提案 6 / ADR-0023）。

**中身を見てから戻す。** 日時だけでは、どれが探している版か分からない。
左に版の一覧、右にその中身を出す。

**ここでは直せない**（読むだけ）。直すなら戻してから本文で直す。画面が
2 つの編集場所を持つと、どちらが本物か分からなくなる。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hitofude.core import frontmatter
from hitofude.storage.history import Version

LIST_MIN_WIDTH = 260

EMPTY_NOTICE = "まだ版がありません。\n書いて保存すると、ここに溜まっていきます。"

# 版が読めなかったときに出す（消された・壊れた）
UNREADABLE = "（この版を読めませんでした）"


class HistoryDialog(QDialog):
    restore_requested = Signal(object)
    """選ばれた `Version`。**戻すのは呼び出し側**（ここは vault を知らない）。"""

    def __init__(self, versions: list[Version], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("版の履歴")
        self.resize(760, 480)
        self._versions = list(versions)

        self._list = QListWidget(self)
        # 日時と題名が並ぶ。狭いと題名が切れて、どれか見分けられない
        self._list.setMinimumWidth(LIST_MIN_WIDTH)
        self._list.addItems([self._label(version) for version in self._versions])
        self._list.currentRowChanged.connect(self._show_row)

        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)

        self._empty = QLabel(EMPTY_NOTICE, self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setVisible(not self._versions)

        body = QHBoxLayout()
        body.addWidget(self._list, 1)
        body.addWidget(self._preview, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        # Qt の既定は英語（`Close`）。画面の言葉を揃える
        self._close = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close.setText("閉じる")
        self._restore = buttons.addButton("この版に戻す", QDialogButtonBox.ButtonRole.AcceptRole)
        self._restore.setEnabled(bool(self._versions))
        self._restore.clicked.connect(self.restore)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self._empty)
        layout.addWidget(buttons)

        if self._versions:
            # **開いた瞬間に何も出ていないと、壊れているように見える**
            self._list.setCurrentRow(0)

    # ------------------------------------------------------------------ 参照

    @property
    def restore_button(self) -> QPushButton:
        return self._restore

    @property
    def close_button(self) -> QPushButton:
        return self._close

    def row_count(self) -> int:
        return self._list.count()

    def row_label(self, row: int) -> str:
        return self._list.item(row).text()

    def select_row(self, row: int) -> None:
        self._list.setCurrentRow(row)

    def preview_text(self) -> str:
        return self._preview.toPlainText()

    def preview_is_read_only(self) -> bool:
        return self._preview.isReadOnly()

    def empty_notice_visible(self) -> bool:
        return not self._empty.isHidden()

    def current_version(self) -> Version | None:
        row = self._list.currentRow()
        return self._versions[row] if 0 <= row < len(self._versions) else None

    # ------------------------------------------------------------------ 動作

    def restore(self) -> None:
        """選んでいる版で戻すよう頼む。**戻すのは呼び出し側**。"""
        version = self.current_version()
        if version is None:
            return
        self.restore_requested.emit(version)
        self.accept()

    def _show_row(self, row: int) -> None:
        version = self._versions[row] if 0 <= row < len(self._versions) else None
        if version is None:
            self._preview.setPlainText("")
            return
        try:
            # **front matter は出さない**（ADR-0013）。本文で見えないものが
            # ここだけ見えると、書く人の知らない情報が漏れて見える
            self._preview.setPlainText(frontmatter.split(version.read()).body)
        except OSError:
            self._preview.setPlainText(UNREADABLE)

    def _label(self, version: Version) -> str:
        """一覧の 1 行。**日時と題名を並べる**（日時だけでは見当が付かない）。"""
        return f"{version.saved_at:%Y-%m-%d %H:%M}　{version.title}"
