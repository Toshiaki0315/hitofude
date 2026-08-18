"""エディタ上での検索・置換のテスト（`Cmd+F`）。

位置の計算そのものは `tests/core/test_search.py` が見る。ここは
**カーソルと Undo** の振る舞い、つまり Qt 側の約束だけを検査する。
"""

import pytest
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor

pytestmark = pytest.mark.gui

TEXT = "りんご みかん りんご\nぶどう りんご"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.setPlainText(TEXT)
    return widget


def selected(editor: MarkdownEditor) -> str:
    return editor.textCursor().selectedText()


class TestFind:
    def test_見つけると選択される(self, editor) -> None:
        assert editor.find_text("みかん") is True
        assert selected(editor) == "みかん"

    def test_見つからなければFalse(self, editor) -> None:
        assert editor.find_text("バナナ") is False

    def test_選択は動かさない(self, editor) -> None:
        """空振りでカーソルが飛ぶと、打ちかけの場所を見失う。"""
        cursor = editor.textCursor()
        cursor.setPosition(4)
        editor.setTextCursor(cursor)
        editor.find_text("バナナ")
        assert editor.textCursor().position() == 4

    def test_続けて押すと次へ進む(self, editor) -> None:
        editor.find_text("りんご")
        first = editor.textCursor().selectionStart()
        editor.find_text("りんご")
        assert editor.textCursor().selectionStart() != first

    def test_末尾まで行くと先頭へ戻る(self, editor) -> None:
        for _ in range(3):
            editor.find_text("りんご")
        editor.find_text("りんご")
        assert editor.textCursor().selectionStart() == 0

    def test_後ろ向きに探せる(self, editor) -> None:
        cursor = editor.textCursor()
        cursor.setPosition(len(TEXT))
        editor.setTextCursor(cursor)
        editor.find_text("りんご", backward=True)
        assert editor.textCursor().selectionStart() == 16

    def test_一致箇所が強調される(self, editor) -> None:
        editor.set_search_highlights("りんご")
        assert len(editor.extraSelections()) == 3

    def test_空のクエリで強調が消える(self, editor) -> None:
        editor.set_search_highlights("りんご")
        editor.set_search_highlights("")
        assert editor.extraSelections() == []

    def test_件数を数えられる(self, editor) -> None:
        assert editor.match_count("りんご") == 3

    def test_大文字小文字を区別させられる(self, editor) -> None:
        editor.setPlainText("Apple apple")
        assert editor.match_count("apple", case_sensitive=True) == 1


class TestReplace:
    def test_選択中の一致を置き換える(self, editor) -> None:
        editor.find_text("みかん")
        editor.replace_selection("みかん", "なし")
        assert "なし" in editor.toPlainText()
        assert "みかん" not in editor.toPlainText()

    def test_選択していなければまず探すだけ(self, editor) -> None:
        """いきなり本文を書き換えない。何が置き換わるか見えていないため。"""
        editor.replace_selection("みかん", "なし")
        assert editor.toPlainText() == TEXT
        assert selected(editor) == "みかん"

    def test_置き換えたら次を選ぶ(self, editor) -> None:
        editor.find_text("りんご")
        editor.replace_selection("りんご", "なし")
        assert selected(editor) == "りんご"

    def test_すべて置き換える(self, editor) -> None:
        assert editor.replace_all_text("りんご", "なし") == 3
        assert "りんご" not in editor.toPlainText()

    def test_すべて置換しても本文の他は変わらない(self, editor) -> None:
        editor.replace_all_text("りんご", "なし")
        assert editor.toPlainText() == "なし みかん なし\nぶどう なし"

    def test_見つからなければ0(self, editor) -> None:
        assert editor.replace_all_text("バナナ", "なし") == 0
        assert editor.toPlainText() == TEXT

    def test_すべて置換はUndo1回で戻る(self, editor) -> None:
        """R5 と同じ約束。1 操作 = Undo 1 段。"""
        editor.replace_all_text("りんご", "なし")
        editor.undo()
        assert editor.toPlainText() == TEXT

    def test_1件の置換もUndo1回で戻る(self, editor) -> None:
        editor.find_text("みかん")
        editor.replace_selection("みかん", "なし")
        editor.undo()
        assert editor.toPlainText() == TEXT

    def test_すべて置換で装飾が壊れない(self, editor) -> None:
        editor.setPlainText("**強調** と `コード`")
        editor.replace_all_text("強調", "太字")
        assert editor.toPlainText() == "**太字** と `コード`"

    def test_置換してもハイライトが生きている(self, editor) -> None:
        """setPlainText で入れ直すとハイライタが作り直され、
        ブロックの解析結果が消える。"""
        editor.setPlainText("# 見出し\n\nりんご\n")
        editor.replace_all_text("りんご", "なし")
        data = editor.document().findBlockByNumber(0).userData()
        assert data is not None
        assert data.info.marker_len == 2


class TestImeGuard:
    """R6: 変換中に検索の都合で本文へ触らない。"""

    def test_変換中でも置換で本文が壊れない(self, editor) -> None:
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        editor.replace_all_text("りんご", "なし")
        assert editor.toPlainText().count("なし") == 3


class TestBMP外の文字:
    """🍎 は Python では 1 文字、UTF-16（QTextCursor）では 2 単位。

    `core/search` の返す位置（Python 単位）をそのままカーソルへ渡すと、
    絵文字より後ろの一致の選択・置換が 1 ずれていた（回帰）。
    """

    def test_絵文字の後ろの一致を正しく選択する(self, editor) -> None:
        editor.setPlainText("🍎 apple")
        assert editor.find_text("apple")
        assert selected(editor) == "apple"

    def test_絵文字の後ろの一致を正しく置換する(self, editor) -> None:
        editor.setPlainText("🍎 apple")
        assert editor.replace_all_text("apple", "りんご") == 1
        assert editor.toPlainText() == "🍎 りんご"
