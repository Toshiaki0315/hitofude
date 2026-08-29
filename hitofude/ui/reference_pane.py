"""もう 1 枚のノートを本文の横に置く（U-1。ユーザー要望 2026-08-29）。

**読むだけ。** 目的は「参照しながら書く」で、それは読めれば満たせる。
両方を編集できるようにするには保存・競合・監視を**ノートごとに持ち直す**
必要があり（`save_controller` だけで 10 箇所が単一のノートを握っている）、
そこは分けて考える。

**本文と同じ `MarkdownEditor` を読み取り専用で使う。** 別の描き方を
用意すると、帯や折りたたみがまた 2 系統になる——「同じことをする道が
2 つあり、片方だけ直す」形は今回の一連で 3 度踏んだ（TASKS.md の T 群）。

ここは**エディタの設定も vault も知らない**（`OutlinePane` と同じ作法）。
出す中身は呼び出し側が渡す。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.theme import LIGHT, ThemeColors

REFERENCE_MIN_WIDTH = 240
"""これより狭いと本文が読めない（`OutlinePane` と同じ考え方）。"""

EMPTY_NOTICE = "ここに別のノートを置けます。\n一覧を右クリックして「横に開く」。"

TITLE_HEIGHT = 24
"""題名の帯。**どのノートを見ているか**が分からないと参照にならない。"""


class ReferencePane(QWidget):
    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self.setMinimumWidth(REFERENCE_MIN_WIDTH)
        self._title = ""

        self._label = QLabel(EMPTY_NOTICE, self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label.setFixedHeight(TITLE_HEIGHT)

        self._editor = MarkdownEditor(self, theme=theme)
        self._editor.setReadOnly(True)
        # **入力の道を塞ぐだけでは足りない。** 読み取り専用でもキャレットは
        # 出るので、書けそうに見える。触れないことを見た目でも示す
        self._editor.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._label)
        layout.addWidget(self._editor, 1)

    # ------------------------------------------------------------------ 参照

    @property
    def editor(self) -> MarkdownEditor:
        return self._editor

    def title(self) -> str:
        """いま出しているノートの題名。出していなければ空。"""
        return self._title

    def is_empty(self) -> bool:
        return not self._title

    # ------------------------------------------------------------------ 操作

    def show_note(self, title: str, text: str) -> None:
        """ノートを出す。**中身は呼び出し側が読む**（ここは vault を知らない）。"""
        self._title = title
        self._label.setText(title)
        self._editor.setPlainText(text)
        # **先頭から見せる。** 前に出していたノートの位置が残ると、
        # 開いた瞬間に途中から始まって面食らう
        self._editor.moveCursor(self._editor.textCursor().MoveOperation.Start)

    def clear(self) -> None:
        self._title = ""
        self._label.setText(EMPTY_NOTICE)
        self._editor.setPlainText("")

    def set_theme(self, theme: ThemeColors) -> None:
        self._editor.set_theme(theme)

    def set_text_style(self, *, family: str, point_size: float, mono: str) -> None:
        """本文と同じ字にする（U-1）。**片方だけ古い設定で描かない。**"""
        self._editor.set_font_family(family)
        self._editor.set_base_point_size(point_size)
        self._editor.set_mono_family(mono)
