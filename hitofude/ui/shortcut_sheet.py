"""ショートカット一覧（C-7 / ユーザー提案）。

今まではメニューを開かないと分からなかった。

**メニューから作る。** 一覧を手で書くと、ショートカットを足したのに載せ
忘れる。メニューは既に「1 か所に集める」方針（`ui/menus.py`）なので、
そこから引けば二重管理にならない。
"""

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

DIALOG_WIDTH = 460
DIALOG_HEIGHT = 560


def shortcut_rows(window) -> list[tuple[str, str, str]]:
    """`(メニュー名, 項目名, キー)` の並び。

    キーの無い項目（「Hitofude について」など）は載せない。一覧の目的は
    「押し方を知る」ことなので、押せないものは邪魔にしかならない。
    """
    rows: list[tuple[str, str, str]] = []
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is None:
            continue
        for entry in menu.actions():
            keys = entry.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if entry.isSeparator() or not keys:
                continue
            rows.append((action.text(), entry.text(), keys))
    return rows


class ShortcutSheet(QDialog):
    """一覧を出すだけのダイアログ。押しても何も起きない（読むためのもの）。"""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle("ショートカット")
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)

        self._rows = shortcut_rows(window)
        self._label = QLabel(self._build_text(), self)
        self._label.setTextFormat(self._label.textFormat().RichText)
        self._label.setAlignment(self._label.alignment())

        holder = QWidget(self)
        inner = QVBoxLayout(holder)
        inner.addWidget(self._label)
        inner.addStretch(1)

        area = QScrollArea(self)
        area.setWidget(holder)
        area.setWidgetResizable(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(area, 1)
        layout.addWidget(buttons)

    def row_count(self) -> int:
        return len(self._rows)

    def text(self) -> str:
        return self._label.text()

    def _build_text(self) -> str:
        lines: list[str] = []
        current = ""
        for group, label, keys in self._rows:
            if group != current:
                current = group
                lines.append(f"<p><b>{group}</b></p>")
            lines.append(f"<p>{label}　<code>{keys}</code></p>")
        return "".join(lines)
