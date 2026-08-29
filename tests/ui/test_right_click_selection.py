"""右クリックで本文を入れ替えない（ユーザー報告 2026-08-29）。

一覧を右クリックすると選択が動き、`currentChanged` から
`note_activated` が飛んで**本文まで入れ替わって**いた（実測）。
「横に開く」を選ぼうとしただけで、開きたいノートがメインにも出る。

**指した行に印は付ける**（どのノートのメニューか分からないと選べない）。
**開くのは左クリックだけ。**
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.gui


@pytest.fixture
def listed(window):
    for name in ("一枚目", "二枚目"):
        note = window._vault.create(name, f"# {name}\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(window._vault.root / "一枚目.md")
    return window


def right_press(view, row: int) -> None:
    point = view.visualRect(view.model().index(row, 0)).center()
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(
                kind,
                QPointF(point),
                QPointF(point),
                Qt.MouseButton.RightButton,
                Qt.MouseButton.RightButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )


class TestRightClick:
    def test_本文が入れ替わらない(self, listed) -> None:
        """**これが本題。**"""
        before = listed.current_note.path
        right_press(listed.note_list, 1)
        assert listed.current_note.path == before

    def test_開く合図を出さない(self, listed) -> None:
        got: list = []
        listed.note_list.note_activated.connect(got.append)
        right_press(listed.note_list, 1)
        assert got == []

    def test_指した行に印が付く(self, listed) -> None:
        """**どのノートのメニューか**が分からないと選べない（Finder と同じ）。"""
        right_press(listed.note_list, 1)
        assert listed.note_list.currentIndex().row() == 1


class TestLeftClickUnchanged:
    """**直しすぎない。** 左クリックは今までどおり開く。"""

    def test_左クリックは開く(self, listed) -> None:
        view = listed.note_list
        point = view.visualRect(view.model().index(1, 0)).center()
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(
                view.viewport(),
                QMouseEvent(
                    kind,
                    QPointF(point),
                    QPointF(point),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
        assert listed.current_note.path.name == "二枚目.md"


class TestMenuStillOpens:
    """**メニューは今までどおり出せる。** 右押しを飲んだので、そこを確かめる。

    本物の右クリックは送らない——`customContextMenuRequested` は
    `menu.exec()` に繋がっており、**答える人がいないと止まる**（実際に
    テストが固まった。Q-4 と同じ罠）。届く仕掛けと、指した行を対象に
    することを別々に見る。
    """

    def test_合図を出す設定になっている(self, listed) -> None:
        """policy が CustomContextMenu なら、Qt が右クリックで合図を出す。
        飲んでいるのはマウスの押下だけで、メニューの合図は別の経路。
        """
        assert listed.note_list.contextMenuPolicy() is Qt.ContextMenuPolicy.CustomContextMenu

    def test_指した行を対象にする(self, listed) -> None:
        """**選択ではなく、指した行**でメニューを組む（元からその作り）。"""
        from pathlib import Path

        menu = listed._notes.context_menu_for(Path("二枚目.md"))
        try:
            assert "横に開く" in [action.text() for action in menu.actions()]
        finally:
            menu.deleteLater()
