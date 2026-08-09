"""書式ツールバー（B-1 / ユーザー要望）。

アイコンのボタンで太字・箇条書きなどを直感的に行えるようにする。
変換そのものは `editor/commands.py` と `MarkdownEditor` のテストが見ている。
ここで見るのは**ツールバーであること**から来る要求:

- 押しても**エディタからフォーカスが外れない**（外れると選択が消えて空振りする）
- 押すたびに Undo が 1 段だけ増える
- ボタンが指す操作が実在する（綴り間違いを機械で捕まえる）
"""

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QTextCursor

from hitofude.theme import DARK, LIGHT
from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.format_toolbar import FormatToolbar

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> EditorPane:
    widget = EditorPane()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def button(pane: EditorPane, name: str):
    """表示名でボタンを引く。"""
    for action, found in zip(FormatToolbar.ACTIONS, pane.toolbar.buttons(), strict=True):
        if action.label == name:
            return found
    raise AssertionError(f"{name} のボタンが無い")


def select_all(pane: EditorPane) -> None:
    cursor = pane.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
    pane.editor.setTextCursor(cursor)


class TestButtons:
    def test_ボタンが並ぶ(self, pane) -> None:
        assert len(pane.toolbar.buttons()) == len(FormatToolbar.ACTIONS)

    def test_主な装飾が揃っている(self, pane) -> None:
        labels = {action.label for action in FormatToolbar.ACTIONS}
        assert {"太字", "斜体", "箇条書き", "番号付き", "見出し", "引用", "リンク"} <= labels

    def test_操作が実在する(self, pane) -> None:
        """綴り間違いはボタンを押すまで気づけない。ここで捕まえる。"""
        for action in FormatToolbar.ACTIONS:
            assert callable(getattr(pane.editor, action.method, None)), action.method

    def test_アイコンがある(self, pane) -> None:
        for found in pane.toolbar.buttons():
            assert not found.icon().isNull()

    def test_ツールチップにショートカットが出る(self, pane) -> None:
        assert "⌘B" in button(pane, "太字").toolTip()

    def test_ショートカットの無いものは名前だけ(self, pane) -> None:
        assert button(pane, "引用").toolTip() == "引用"


class TestPressing:
    def test_太字にする(self, pane) -> None:
        pane.editor.setPlainText("強調")
        select_all(pane)
        button(pane, "太字").click()
        assert pane.editor.toPlainText() == "**強調**"

    def test_選んだ行を箇条書きにする(self, pane) -> None:
        pane.editor.setPlainText("りんご\nみかん")
        select_all(pane)
        button(pane, "箇条書き").click()
        assert pane.editor.toPlainText() == "- りんご\n- みかん"

    def test_見出しは押すたびに深くなる(self, pane) -> None:
        pane.editor.setPlainText("メモ")
        button(pane, "見出し").click()
        button(pane, "見出し").click()
        assert pane.editor.toPlainText() == "## メモ"

    def test_Undoは1手で戻る(self, pane) -> None:
        pane.editor.setPlainText("りんご\nみかん")
        select_all(pane)
        button(pane, "箇条書き").click()
        pane.editor.undo()
        assert pane.editor.toPlainText() == "りんご\nみかん"


class TestFocus:
    """**ここが要**。ボタンにフォーカスが移ると選択が外れ、囲むものが無くなる。"""

    def test_ボタンはフォーカスを受け取らない(self, pane) -> None:
        for found in pane.toolbar.buttons():
            assert found.focusPolicy() == Qt.FocusPolicy.NoFocus

    def test_押しても選択が残る(self, pane) -> None:
        pane.editor.setPlainText("強調")
        select_all(pane)
        button(pane, "太字").click()
        assert pane.editor.textCursor().hasSelection()

    def test_二度押すと元に戻る(self, pane) -> None:
        """選択が残っていることの実地の証明。残らないと外せない。"""
        pane.editor.setPlainText("強調")
        select_all(pane)
        button(pane, "太字").click()
        button(pane, "太字").click()
        assert pane.editor.toPlainText() == "強調"

    def test_押したあとエディタに書ける(self, pane) -> None:
        pane.editor.setPlainText("")
        pane.editor.setFocus()
        button(pane, "箇条書き").click()
        assert pane.editor.hasFocus()


class TestTheme:
    def test_色がテーマに追従する(self, pane, qapp) -> None:
        def icon_colors(widget) -> set[str]:
            image = widget.icon().pixmap(QSize(32, 32)).toImage()
            return {
                QColor(image.pixelColor(x, y)).name()
                for y in range(image.height())
                for x in range(image.width())
                if image.pixelColor(x, y).alpha() > 128
            }

        pane.set_theme(LIGHT)
        light = icon_colors(button(pane, "太字"))
        pane.set_theme(DARK)
        assert icon_colors(button(pane, "太字")) != light


class TestVisibility:
    def test_既定で見える(self, pane) -> None:
        assert not pane.toolbar.isHidden()

    def test_隠せる(self, pane) -> None:
        pane.set_toolbar_visible(False)
        assert pane.toolbar.isHidden()

    def test_戻せる(self, pane) -> None:
        pane.set_toolbar_visible(False)
        pane.set_toolbar_visible(True)
        assert not pane.toolbar.isHidden()

    def test_今の状態を答える(self, pane) -> None:
        pane.set_toolbar_visible(False)
        assert pane.toolbar_visible() is False
