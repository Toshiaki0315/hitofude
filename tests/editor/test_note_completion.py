"""`[[` を打ったときのノート名補完（ユーザー要望）。

`[[会議メモ]]` は書けるのに**候補が出なかった**。正確な名前を覚えているか、
別のノートを開いて確かめる必要がある。

**タグ補完の仕組みをそのまま使う**（同じポップアップ、同じキー操作）。
行の形が重ならない（`#` と `[[`）ので、1 つで足りる。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui

TITLES = ["会議メモ", "会計メモ", "買い物リスト"]


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.set_note_source(lambda: TITLES)
    widget.show()
    return widget


def type_text(editor: MarkdownEditor, text: str) -> None:
    """日本語は `keyClicks` に渡せない（Qt が abort する）ので挿入で入れる。"""
    editor.textCursor().insertText(text)
    editor.update_tag_completion()


class TestCandidates:
    def test_二重括弧で候補が出る(self, editor) -> None:
        type_text(editor, "[[")
        assert editor.tag_candidates() == TITLES

    def test_打つほど絞られる(self, editor) -> None:
        type_text(editor, "[[会議")
        assert editor.tag_candidates() == ["会議メモ"]

    def test_本文の途中でも出る(self, editor) -> None:
        type_text(editor, "詳しくは [[会")
        assert editor.tag_candidates() == ["会議メモ", "会計メモ"]

    def test_閉じたあとは出さない(self, editor) -> None:
        type_text(editor, "[[会議メモ]] のあと")
        assert editor.tag_candidates() == []

    def test_渡し口が無ければ出さない(self, qtbot) -> None:
        """**エディタは索引を知らない。** 呼び出し側が渡すまで黙っている。"""
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        type_text(widget, "[[")
        assert widget.tag_candidates() == []

    def test_変換中は出さない(self, editor) -> None:
        """R6。確定前に一覧が出ると変換候補と重なる。"""
        editor.textCursor().insertText("[[")
        editor._composing = True
        editor.update_tag_completion()
        assert editor.tag_candidates() == []


class TestComplete:
    def test_選ぶと名前が入る(self, editor) -> None:
        type_text(editor, "[[会議")
        editor.complete_tag("会議メモ")
        assert editor.toPlainText() == "[[会議メモ]]"

    def test_閉じ括弧の内側に入れる(self, editor) -> None:
        """**既に `]]` があるなら足さない。** 直すときに `]]]]` にならない。"""
        editor.setPlainText("[[]]")
        cursor = editor.textCursor()
        cursor.setPosition(2)
        editor.setTextCursor(cursor)
        editor.complete_tag("会議メモ")
        assert editor.toPlainText() == "[[会議メモ]]"

    def test_選んだあとカーソルは閉じ括弧の外(self, editor) -> None:
        """続けて書けるように。中に残ると、打った文字がリンク名に入る。"""
        type_text(editor, "[[会議")
        editor.complete_tag("会議メモ")
        assert editor.textCursor().position() == len("[[会議メモ]]")

    def test_Undoは1手で戻る(self, editor) -> None:
        type_text(editor, "[[会議")
        editor.complete_tag("会議メモ")
        editor.undo()
        assert editor.toPlainText() == "[[会議"

    def test_候補は閉じる(self, editor) -> None:
        type_text(editor, "[[会議")
        editor.complete_tag("会議メモ")
        assert editor.tag_candidates() == []


class TestKeys:
    def test_Escで閉じる(self, editor, qtbot) -> None:
        type_text(editor, "[[会")
        qtbot.keyClick(editor, Qt.Key.Key_Escape)
        assert editor.tag_candidates() == []

    def test_Enterで決まる(self, editor, qtbot) -> None:
        type_text(editor, "[[会議")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.toPlainText() == "[[会議メモ]]"
        assert "\n" not in editor.toPlainText()


class TestSource:
    def test_索引から取り直す(self, editor) -> None:
        """開いている間にノートが増えることがある。**毎回聞く。**"""
        titles = ["最初"]
        editor.set_note_source(lambda: titles)
        type_text(editor, "[[")
        assert editor.tag_candidates() == ["最初"]

        titles.append("あとから")
        editor.setPlainText("")
        editor.setTextCursor(QTextCursor(editor.document()))
        type_text(editor, "[[")
        assert editor.tag_candidates() == ["最初", "あとから"]


class TestCompleteInsideLink:
    """既存リンクの名前の途中で確定したとき（コードレビュー指摘 / 回帰）。

    閉じ判定がカーソル直後 2 文字しか見ておらず、[[会議メモ]] の途中で
    確定すると [[会議メモ]]モ]] のように壊れていた。
    """

    def test_名前の途中で確定しても壊れない(self, editor) -> None:
        editor.set_note_source(lambda: ["会議メモ"])
        editor.setPlainText("[[会議メ]] のあと")
        cursor = editor.textCursor()
        cursor.setPosition(4)  # [[会議 | メ]] — 名前の途中
        editor.setTextCursor(cursor)
        editor.update_tag_completion()
        assert "会議メモ" in editor.tag_candidates()

        editor.complete_tag("会議メモ")
        assert editor.toPlainText() == "[[会議メモ]] のあと"

    def test_確定後のカーソルは閉じ括弧の外(self, editor) -> None:
        editor.set_note_source(lambda: ["会議メモ"])
        editor.setPlainText("[[会議メ]]")
        cursor = editor.textCursor()
        cursor.setPosition(4)
        editor.setTextCursor(cursor)
        editor.update_tag_completion()
        editor.complete_tag("会議メモ")
        assert editor.textCursor().position() == len("[[会議メモ]]")

    def test_タグ補完は後ろの括弧に反応しない(self, editor) -> None:
        """カーソル送り（]] の外へ出す）はリンク補完だけの動き。
        タグの確定でたまたま後ろに ]] があっても飛ばない。"""
        editor.set_tag_source(lambda: ["日報"])
        editor.setPlainText("#日]]")
        cursor = editor.textCursor()
        cursor.setPosition(2)  # #日 | ]]
        editor.setTextCursor(cursor)
        editor.update_tag_completion()
        assert "日報" in editor.tag_candidates()

        editor.complete_tag("日報")
        assert editor.toPlainText() == "#日報]]"
        assert editor.textCursor().position() == 3  # ]] の手前のまま
