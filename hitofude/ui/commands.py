"""メニューバーの項目を平らに並べる（U-3 コマンドパレット）。

**命令の一覧を別に持たない。** 持つと、メニューに足したのにパレットに
出ない（あるいはその逆）が起きる——「同じことをする道が 2 つあり、
片方だけ直す」形は直近で何度も踏んだ（TASKS.md の T 群）。

ここは**押す側を知らない**。集めて返すだけで、出すのも動かすのも
呼び出し側（`ui/search_actions`）。
"""

from dataclasses import dataclass

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QMenuBar

SEPARATOR = " ▸ "
"""道筋の区切り。**メニューの「▸ 書き出す」と同じ記号**を使う。"""

MAX_DEPTH = 4
"""入れ子の上限。輪になっていても止まるための保険。"""


@dataclass(frozen=True, slots=True)
class Command:
    label: str
    """項目の言葉。`&` の飾りは落としてある。"""

    path: str
    """どこにある項目か（`ファイル ▸ 書き出す`）。

    **同じ言葉が別のメニューにもある**ので、これが無いと選べない。
    """

    action: QAction

    @property
    def shortcut(self) -> str:
        return self.action.shortcut().toString()


def _clean(label: str) -> str:
    """`元に戻す(&U)` の飾りを落とす。

    **飾りは動作の文字列に常に入っている**（実測）。macOS は描くときに
    外すが、こちらが読むと付いたまま来るので、探す言葉に混ざる。
    """
    return label.replace("&", "").strip()


def _walk(menu: QMenu, path: str, depth: int, found: list[Command]) -> None:
    for action in menu.actions():
        if action.isSeparator():
            continue
        label = _clean(action.text())
        if not label:
            continue
        child = action.menu()
        if child is not None:
            # 押しても中が開くだけ。**命令ではない**ので入れず、中へ降りる
            if depth < MAX_DEPTH:
                _walk(child, f"{path}{SEPARATOR}{label}", depth + 1, found)
            continue
        if not action.isEnabled():
            continue  # **押せないものを並べない。** 選んでも何も起きない
        found.append(Command(label=label, path=path, action=action))


def commands(bar: QMenuBar) -> list[Command]:
    """メニューバーにある「押せる項目」を平らに並べる。"""
    found: list[Command] = []
    for action in bar.actions():
        menu = action.menu()
        if menu is None:
            continue
        _walk(menu, _clean(action.text()), 1, found)
    return found
