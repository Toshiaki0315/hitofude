"""front matter を打ち壊さないことのテスト（回帰）。

エディタは front matter を保持しているが、ハイライタが潰すので**画面には
見えない**。位置 0 は見た目の先頭でも実際には `---` の前にあたる。
そこへ打つと front matter が本文の下へ押し出され、`frontmatter.split()` が
認識できなくなって `id` と `modified` が失われる。

新規ノートを作ってすぐ打ち始める、というアプリの主要な流れで起きていた。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtWidgets import QApplication

from hitofude.core import frontmatter
from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui

WITH_META = "---\nid: ABC123\ncreated: 2026-01-01T00:00:00+09:00\n---\n# 見出し\n\n本文\n"
WITHOUT_META = "# 見出し\n\n本文\n"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.setPlainText(WITH_META)
    return widget


def at(editor: MarkdownEditor, position: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(position)
    editor.setTextCursor(cursor)


def meta_survives(editor: MarkdownEditor) -> bool:
    parsed = frontmatter.split(editor.toPlainText())
    return parsed.present and parsed.meta.get("id") == "ABC123"


class TestTyping:
    def test_先頭で打っても壊れない(self, editor, qtbot) -> None:
        at(editor, 0)
        qtbot.keyClicks(editor, "abc")
        assert meta_survives(editor)

    def test_打った文字は本文の先頭に入る(self, editor, qtbot) -> None:
        at(editor, 0)
        qtbot.keyClicks(editor, "abc")
        assert frontmatter.split(editor.toPlainText()).body.startswith("abc")

    def test_front_matterの途中で打っても壊れない(self, editor, qtbot) -> None:
        at(editor, 8)
        qtbot.keyClicks(editor, "x")
        assert meta_survives(editor)

    def test_日本語の確定でも壊れない(self, editor) -> None:
        """IME は keyClicks では送れないので確定イベントを直に流す。"""
        at(editor, 0)
        QApplication.sendEvent(editor, QInputMethodEvent("にほん", []))
        commit = QInputMethodEvent()
        commit.setCommitString("日本語")
        QApplication.sendEvent(editor, commit)
        assert meta_survives(editor)

    def test_貼り付けても壊れない(self, editor) -> None:
        at(editor, 0)
        QApplication.clipboard().setText("貼り付けた文字")
        editor.paste()
        assert meta_survives(editor)

    def test_本文の中では今まで通り打てる(self, editor, qtbot) -> None:
        at(editor, len(WITH_META) - 1)
        qtbot.keyClicks(editor, "xyz")
        assert editor.toPlainText().endswith("xyz\n") or "xyz" in editor.toPlainText()
        assert meta_survives(editor)


class TestDeleting:
    def test_本文の先頭でBackspaceを押しても食べない(self, editor, qtbot) -> None:
        offset = frontmatter.body_offset(WITH_META)
        at(editor, offset)
        qtbot.keyClick(editor, Qt.Key.Key_Backspace)
        assert meta_survives(editor)

    def test_本文の先頭は削れていない(self, editor, qtbot) -> None:
        offset = frontmatter.body_offset(WITH_META)
        at(editor, offset)
        qtbot.keyClick(editor, Qt.Key.Key_Backspace)
        assert editor.toPlainText() == WITH_META

    def test_front_matterの中でBackspaceを押しても壊れない(self, editor, qtbot) -> None:
        at(editor, 10)
        qtbot.keyClick(editor, Qt.Key.Key_Backspace)
        assert meta_survives(editor)

    def test_本文の中では今まで通り消せる(self, editor, qtbot) -> None:
        at(editor, len(WITH_META) - 1)
        qtbot.keyClick(editor, Qt.Key.Key_Backspace)
        assert meta_survives(editor)
        assert len(editor.toPlainText()) < len(WITH_META)


class TestSelectAll:
    def test_全選択して打ち直しても残る(self, editor, qtbot) -> None:
        """`Cmd+A` は front matter ごと選ぶ。選択の**始点だけ**を本文へ丸める。"""
        editor.selectAll()
        qtbot.keyClicks(editor, "rewrite")
        assert meta_survives(editor)

    def test_全選択して打ち直すと本文は入れ替わる(self, editor, qtbot) -> None:
        editor.selectAll()
        qtbot.keyClicks(editor, "abc")
        assert frontmatter.split(editor.toPlainText()).body == "abc"

    def test_全選択して消しても残る(self, editor, qtbot) -> None:
        editor.selectAll()
        qtbot.keyClick(editor, Qt.Key.Key_Backspace)
        assert meta_survives(editor)

    def test_front_matterにまたがる選択を打ち替えても残る(self, editor, qtbot) -> None:
        cursor = editor.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(len(WITH_META) - 2, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        qtbot.keyClicks(editor, "x")
        assert meta_survives(editor)


class TestWithoutFrontMatter:
    """front matter が無いノートの挙動を変えない。"""

    def test_先頭に打てる(self, qtbot) -> None:
        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        editor.setPlainText(WITHOUT_META)
        at(editor, 0)
        qtbot.keyClicks(editor, "abc")
        assert editor.toPlainText().startswith("abc")

    def test_先頭のBackspaceで何も起きない(self, qtbot) -> None:
        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        editor.setPlainText(WITHOUT_META)
        at(editor, 0)
        qtbot.keyClick(editor, Qt.Key.Key_Backspace)
        assert editor.toPlainText() == WITHOUT_META


class TestUndo:
    def test_丸めてもUndoは1回で戻る(self, editor, qtbot) -> None:
        """R5 の約束を崩さない。"""
        at(editor, 0)
        qtbot.keyClicks(editor, "a")
        editor.undo()
        assert editor.toPlainText() == WITH_META
