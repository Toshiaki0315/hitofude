"""書式をメニューバーに出す（2026-08-25）。

**入口がツールバーとキーしか無かった。** `Cmd+3` でツールバーを隠すと
**書式に手が届かなくなる**——設定への入口が消えていた件（歯車を
ステータスバーへ移した 2026-08-24）と同じ形の問題。

ツールバー側のコメントは前から **「登録は `ui/menus.py` の仕事」** と
書いてあった。台帳（`FormatToolbar.ACTIONS`）は 1 つのまま、メニューは
そこから組む。

**フォーカスのあるところだけに効かせる。** `Cmd+B` は今まで
エディタの `keyPressEvent` が受けていて、検索欄では何も起きなかった。
`QAction` にすると窓のどこにいても飛ぶので、**エディタに焦点が無ければ
何もしない**ようにして今までの挙動を保つ。
"""

import pytest
from PySide6.QtCore import Qt

from hitofude.ui.format_toolbar import FormatToolbar

pytestmark = pytest.mark.gui


def labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


class TestMenu:
    def test_書式のサブメニューがある(self, window) -> None:
        assert "書式" in window.menus

    def test_ツールバーと同じ顔ぶれ(self, window) -> None:
        """**台帳は 1 つ。** 片方に足してもう片方に足し忘れる、を防ぐ。"""
        assert labels(window.menus["書式"]) == [a.label for a in FormatToolbar.ACTIONS]

    def test_編集の中にある(self, window) -> None:
        found = [a.text() for a in window.menus["編集"].actions()]
        assert "書式" in found

    def test_編集を太らせない(self, window) -> None:
        """**畳んで入れる**（「ファイル」を 20 行にした反省）。"""
        assert len(labels(window.menus["編集"])) <= 12


KEYS = {
    "太字": "Ctrl+B",
    "斜体": "Ctrl+I",
    "打ち消し": "Ctrl+Shift+X",
    "コード": "Ctrl+E",
    "マーカー": "Ctrl+Shift+H",
    "チェックボックス": "Ctrl+Shift+T",
    "リンク": "Ctrl+K",
}


class TestShortcuts:
    """キーは今まで通り。**メニューに出しても表示だけが嘘、にしない。**"""

    def test_持っているものは登録されている(self, window) -> None:
        found = {a.text(): a.shortcut().toString() for a in window.menus["書式"].actions()}
        for label, key in KEYS.items():
            assert found[label] == key, label

    def test_持たないものには付けない(self, window) -> None:
        found = {a.text(): a.shortcut().toString() for a in window.menus["書式"].actions()}
        for label in ("見出し", "箇条書き", "番号付き", "引用"):
            assert found[label] == ""


class TestFocus:
    """**エディタに焦点があるときだけ効く**（今までと同じ）。"""

    def test_本文で押せば書式が付く(self, window, qtbot, activate) -> None:
        """**窓を活かしてから見る。** 表示していない窓では焦点が立たない
        （`hasFocus()` が False のままで、この試験だけ落ちた）。
        """
        activate(window)
        window.editor.setPlainText("会議メモ")
        cursor = window.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        window.editor.setTextCursor(cursor)
        window.editor.setFocus()
        qtbot.waitUntil(window.editor.hasFocus, timeout=2000)
        window.menu_actions["太字"].trigger()
        assert "**" in window.editor.toPlainText()

    def test_他所に焦点があれば何もしない(self, window, qtbot, activate) -> None:
        """`Cmd+B` を検索欄で押しても本文が太字にならない（今までの挙動）。"""
        activate(window)
        window.editor.setPlainText("会議メモ")
        cursor = window.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        window.editor.setTextCursor(cursor)
        window._pane.open_find()
        qtbot.waitUntil(lambda: not window.editor.hasFocus(), timeout=2000)
        window.menu_actions["太字"].trigger()
        assert window.editor.toPlainText() == "会議メモ"


class TestKeyStillWorks:
    """**打鍵の道は塞がない。** メニューへ移しても本文で押せば効く。"""

    @pytest.mark.parametrize(
        ("key", "mark"),
        [(Qt.Key.Key_B, "**"), (Qt.Key.Key_I, "*"), (Qt.Key.Key_E, "`")],
    )
    def test_本文で押せば効く(self, window, qtbot, key, mark: str) -> None:
        window.editor.setPlainText("会議メモ")
        cursor = window.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        window.editor.setTextCursor(cursor)
        window.editor.setFocus()
        qtbot.keyClick(window.editor, key, Qt.KeyboardModifier.ControlModifier)
        assert mark in window.editor.toPlainText()
