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
from hitofude.core.models import BlockType
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


class TestSelectAllThenEdit:
    """全選択したあとに編集したとき。何が選ばれるかは `TestSelectAll` が見る。"""

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


class TestCut:
    """切り取りは `keyPressEvent` も `insertFromMimeData` も通らない。

    `Cmd+A` で全選択して `Cmd+X` を押すと front matter ごと消えていた
    （ユーザー報告）。入力の経路ごとに守りを足していたため、ここだけ
    抜けていた。
    """

    def test_全選択して切り取っても残る(self, editor) -> None:
        editor.selectAll()
        editor.cut()
        assert meta_survives(editor)

    def test_全選択して切り取ると本文だけ消える(self, editor) -> None:
        editor.selectAll()
        editor.cut()
        assert frontmatter.split(editor.toPlainText()).body == ""

    def test_切り取った中身に_front_matterを含めない(self, editor) -> None:
        """クリップボードに `id` が乗ると、貼り付け先に漏れる。"""
        from PySide6.QtWidgets import QApplication

        editor.selectAll()
        editor.cut()
        assert "ABC123" not in QApplication.clipboard().text()

    def test_ショートカットからでも残る(self, editor, qtbot) -> None:
        editor.selectAll()
        qtbot.keyClick(editor, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        assert meta_survives(editor)

    def test_front_matterの中だけ選んで切り取っても残る(self, editor) -> None:
        cursor = editor.textCursor()
        cursor.setPosition(4)
        cursor.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.cut()
        assert meta_survives(editor)

    def test_本文の中では今まで通り切り取れる(self, editor) -> None:
        offset = frontmatter.body_offset(WITH_META)
        cursor = editor.textCursor()
        cursor.setPosition(offset)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.cut()

        assert meta_survives(editor)
        assert frontmatter.split(editor.toPlainText()).body == ""

    def test_front_matterが無ければ全部切れる(self, qtbot) -> None:
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.setPlainText(WITHOUT_META)
        widget.selectAll()
        widget.cut()
        assert widget.toPlainText() == ""


class TestCutShortcut:
    """`Cmd+X` の生のキーイベント。

    `QPlainTextEdit` は標準のキー割り当てを内部で処理し、**仮想メソッドの
    `cut()` を通らない**。実アプリでは編集メニューの項目が先に受けるので
    `cut()` へ回るが、ウィジェット単体でも守れるようにしておく。
    """

    def send_cut(self, editor, text: str) -> None:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendEvent(
            editor,
            QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_X,
                Qt.KeyboardModifier.ControlModifier,
                text,
            ),
        )

    @pytest.mark.parametrize("text", ["", "\x18"])
    def test_全選択して切り取っても残る(self, editor, text: str) -> None:
        editor.selectAll()
        self.send_cut(editor, text)
        assert meta_survives(editor)

    def test_本文は切り取れる(self, editor) -> None:
        offset = frontmatter.body_offset(WITH_META)
        cursor = editor.textCursor()
        cursor.setPosition(offset)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        self.send_cut(editor, "")
        assert frontmatter.split(editor.toPlainText()).body == ""
        assert meta_survives(editor)


class TestSelectAll:
    """`Cmd+A` は本文だけを選ぶ（ユーザー報告）。

    front matter まで選ばれると、`id` や日時が画面に現れて選択色で塗られる。
    編集の経路では丸めているので消えはしないが、**消えるように見える**し、
    コピーすれば実際に混ざる。ユーザーにとっての「すべて」は本文。
    """

    def test_front_matterを選ばない(self, editor) -> None:
        editor.selectAll()
        offset = frontmatter.body_offset(WITH_META)
        assert editor.textCursor().selectionStart() == offset

    def test_本文は最後まで選ぶ(self, editor) -> None:
        editor.selectAll()
        cursor = editor.textCursor()
        assert cursor.selectionEnd() == editor.document().characterCount() - 1

    def test_選んだ中身に_front_matterを含めない(self, editor) -> None:
        editor.selectAll()
        assert "ABC123" not in editor.textCursor().selectedText()

    def test_コピーしても混ざらない(self, editor) -> None:
        from PySide6.QtWidgets import QApplication

        editor.selectAll()
        editor.copy()
        assert "ABC123" not in QApplication.clipboard().text()

    def test_ショートカットからでも本文だけ(self, editor, qtbot) -> None:
        qtbot.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert editor.textCursor().selectionStart() == frontmatter.body_offset(WITH_META)

    def test_front_matterが無ければ全部選ぶ(self, qtbot) -> None:
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.setPlainText(WITHOUT_META)
        widget.selectAll()
        assert widget.textCursor().selectionStart() == 0

    def test_選んでも_front_matterが現れない(self, editor) -> None:
        """選択範囲に入ると記号が現れる仕組み。本文だけ選べば出てこない。"""
        editor.selectAll()
        data = editor.document().findBlockByNumber(0).userData()
        assert data is not None
        assert data.info.type is BlockType.FRONT_MATTER

    def test_打ち直せば本文だけ入れ替わる(self, editor, qtbot) -> None:
        editor.selectAll()
        qtbot.keyClicks(editor, "rewrite")
        assert meta_survives(editor)
        assert frontmatter.split(editor.toPlainText()).body == "rewrite"
