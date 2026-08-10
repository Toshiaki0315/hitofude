"""タグの入力補完（C-4 / ユーザー提案）。

綴りを覚えていないと `#日報` と `#日報メモ` のような揺れが起きる。
打ち始めたところで既存のタグを出す。判定は `core/tags.py`（純関数）。
ここは**ポップアップの出し入れと確定**を見る。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui

KNOWN = ["日報", "日記", "仕事/日報", "hitofude/使い方"]


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.set_tag_source(lambda: KNOWN)
    widget.show()
    return widget


def type_tag(editor: MarkdownEditor, text: str) -> None:
    """本文を置いてカーソルを末尾へ。日本語は `insertText` で入れる
    （`keyClicks` に日本語を渡すとプロセスごと落ちる）。"""
    editor.setPlainText("")
    editor.textCursor().insertText(text)
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.update_tag_completion()


class TestPopup:
    def test_記号を打つと候補が出る(self, editor) -> None:
        type_tag(editor, "メモ #")
        assert editor.tag_candidates() == KNOWN

    def test_打つほど絞られる(self, editor) -> None:
        type_tag(editor, "メモ #日")
        assert editor.tag_candidates() == ["日報", "日記"]

    def test_階層も絞れる(self, editor) -> None:
        type_tag(editor, "#仕事/")
        assert editor.tag_candidates() == ["仕事/日報"]

    def test_タグの外では出ない(self, editor) -> None:
        type_tag(editor, "ただの文章")
        assert editor.tag_candidates() == []

    def test_一致が無ければ出ない(self, editor) -> None:
        type_tag(editor, "#存在しないタグ")
        assert editor.tag_candidates() == []

    def test_打ち終わったタグでは出ない(self, editor) -> None:
        """候補が今打っているものだけなら、選ぶものが無い。"""
        editor.set_tag_source(lambda: ["日報"])
        type_tag(editor, "#日報")
        assert editor.tag_candidates() == []

    def test_変換中は出さない(self, editor) -> None:
        """R6。確定前に一覧が出ると変換候補と重なる。"""
        editor.setPlainText("")
        editor.textCursor().insertText("メモ #")
        editor._composing = True
        editor.update_tag_completion()
        assert editor.tag_candidates() == []

    def test_タグ元が無くても落ちない(self, qtbot) -> None:
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.textCursor().insertText("#")
        widget.update_tag_completion()
        assert widget.tag_candidates() == []


class TestAccept:
    def test_選ぶと打ちかけを置き換える(self, editor) -> None:
        type_tag(editor, "メモ #日")
        editor.complete_tag("日報")
        assert editor.toPlainText() == "メモ #日報"

    def test_階層も置き換える(self, editor) -> None:
        type_tag(editor, "#仕事/")
        editor.complete_tag("仕事/日報")
        assert editor.toPlainText() == "#仕事/日報"

    def test_確定後はカーソルが末尾(self, editor) -> None:
        type_tag(editor, "メモ #日")
        editor.complete_tag("日報")
        assert editor.textCursor().positionInBlock() == len("メモ #日報")

    def test_確定後は候補が消える(self, editor) -> None:
        type_tag(editor, "メモ #日")
        editor.complete_tag("日報")
        assert editor.tag_candidates() == []

    def test_Undoは1手で戻る(self, editor) -> None:
        type_tag(editor, "メモ #日")
        editor.complete_tag("日報")
        editor.undo()
        assert editor.toPlainText() == "メモ #日"

    def test_タグの外では何もしない(self, editor) -> None:
        type_tag(editor, "ただの文章")
        editor.complete_tag("日報")
        assert editor.toPlainText() == "ただの文章"


class TestKeys:
    def test_Escで閉じる(self, editor, qtbot) -> None:
        type_tag(editor, "メモ #日")
        qtbot.keyClick(editor, Qt.Key.Key_Escape)
        assert editor.tag_candidates() == []
