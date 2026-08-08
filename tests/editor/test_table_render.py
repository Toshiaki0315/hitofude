"""表の罫線描画と自動整形のテスト（ユーザー要望 / spec §5.2 の描画フック）。

`|` は削除せず極小化して隠し、線は `paintEvent` で描く（R4）。
キャレット位置とソースのオフセットは 1:1 のまま。
"""

import pytest

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations
from hitofude.editor.table import display_width

pytestmark = pytest.mark.gui

TABLE = "| 用語 | 解説 |\n|---|---|\n| クレート | Rust のパッケージ |\n| HAL | 橋渡し役 |\n\n本文\n"


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(760, 300)
    widget.show()
    return widget


def move_to(editor: MarkdownEditor, line: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(line).position())
    editor.setTextCursor(cursor)


def kinds(editor: MarkdownEditor) -> list[DecorationKind]:
    return [decoration.kind for decoration in visible_decorations(editor)]


def hidden_ranges(editor: MarkdownEditor, line: int) -> list[tuple[int, int]]:
    block = editor.document().findBlockByNumber(line)
    return [
        (entry.start, entry.length)
        for entry in block.layout().formats()
        if entry.format.fontPointSize() == pytest.approx(0.5)
    ]


class TestAutoFormat:
    """行を離れたら揃える。打っている最中は動かさない。"""

    def test_表の行を離れると揃う(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)

        lines = editor.toPlainText().split("\n")[:4]
        assert len({display_width(line) for line in lines}) == 1, lines

    def test_表の中を移動するだけでは動かさない(self, editor) -> None:
        """打っている最中に揃うとキャレットが飛んで書けない。"""
        editor.setPlainText(TABLE)
        move_to(editor, 0)
        before = editor.toPlainText()
        move_to(editor, 2)
        assert editor.toPlainText() == before

    def test_表の外を移動しても何も起きない(self, editor) -> None:
        editor.setPlainText("本文\n\nもう一行\n")
        before = editor.toPlainText()
        move_to(editor, 0)
        move_to(editor, 2)
        assert editor.toPlainText() == before

    def test_整形してもキャレットは今いる場所に残る(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)
        assert editor.textCursor().blockNumber() == 5

    def test_変換中は整形しない(self, editor) -> None:
        """R6: IME 変換中に本文を書き換えると変換が壊れる。"""
        from PySide6.QtGui import QInputMethodEvent
        from PySide6.QtWidgets import QApplication

        editor.setPlainText(TABLE)
        move_to(editor, 2)
        QApplication.sendEvent(editor, QInputMethodEvent("にほんご", []))
        before = editor.toPlainText()
        move_to(editor, 5)
        assert editor.toPlainText() == before


class TestHiding:
    def test_縦線の文字を隠す(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert len(hidden_ranges(editor, 0)) == 3  # `|` が 3 本

    def test_区切り行は丸ごと隠す(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert hidden_ranges(editor, 1), "区切り行が見えたまま"

    def test_文字は消さない(self, editor) -> None:
        """R4: 隠すだけ。ソースとキャレット位置は 1:1 のまま。"""
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert "|" in editor.toPlainText()
        assert editor.toPlainText().count("|") >= 12

    def test_カーソルを入れると縦線が現れる(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert hidden_ranges(editor, 0)
        move_to(editor, 0)
        assert hidden_ranges(editor, 0) == []


class TestGrid:
    def test_罫線とヘッダ背景を描く(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        found = kinds(editor)
        assert DecorationKind.TABLE_RULE in found
        assert DecorationKind.TABLE_HEADER in found

    def test_縦線は列の数だけ引く(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        rules = [d for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_RULE]
        vertical = [d for d in rules if d.rect.width() < d.rect.height()]
        assert len(vertical) == 3

    def test_表の中にいる間は線を引かない(self, editor) -> None:
        """編集中はソースが揃っておらず、線が本文とずれる。"""
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        assert DecorationKind.TABLE_RULE not in kinds(editor)

    def test_表が無ければ描かない(self, editor) -> None:
        editor.setPlainText("本文だけ\n")
        assert DecorationKind.TABLE_RULE not in kinds(editor)

    def test_1行だけでは表にしない(self, editor) -> None:
        editor.setPlainText("| これは表ではない |\n\n本文\n")
        move_to(editor, 2)
        assert DecorationKind.TABLE_RULE not in kinds(editor)


class TestHeaderStyle:
    def test_ヘッダ行は太字(self, editor) -> None:
        from PySide6.QtGui import QFont

        editor.setPlainText(TABLE)
        move_to(editor, 5)
        block = editor.document().findBlockByNumber(0)
        weights = [entry.format.fontWeight() for entry in block.layout().formats()]
        assert any(weight >= QFont.Weight.Bold for weight in weights)

    def test_本体行は太字にしない(self, editor) -> None:
        from PySide6.QtGui import QFont

        editor.setPlainText(TABLE)
        move_to(editor, 5)
        block = editor.document().findBlockByNumber(2)
        weights = [entry.format.fontWeight() for entry in block.layout().formats()]
        assert all(weight < QFont.Weight.Bold for weight in weights)


class TestSourceIntegrity:
    """R1: ソース文字列が唯一の真実。"""

    def test_整形しても内容は変わらない(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)
        text = editor.toPlainText()
        for word in ("用語", "解説", "クレート", "HAL", "橋渡し役"):
            assert word in text

    def test_Undoで元のソースに戻る(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)
        assert editor.toPlainText() != TABLE
        editor.undo()
        assert editor.toPlainText() == TABLE


class TestGridBounds:
    """罫線が表の幅に収まること（回帰テスト）。

    ブロックの矩形は**表示領域の全幅**なので、そのまま使うと横線が画面の
    端まで伸びる。実際そうなっていた。
    """

    def _rules(self, editor):
        return [d for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_RULE]

    def test_横線が表の幅に収まる(self, editor) -> None:
        editor.setPlainText("| aaa | bbb |\n|---|---|\n| ddd | eee |\n\n本文\n")
        move_to(editor, 4)

        rules = self._rules(editor)
        horizontal = [d for d in rules if d.rect.width() > d.rect.height()]
        assert horizontal
        widest = max(d.rect.width() for d in horizontal)
        assert widest < editor.viewport().width() * 0.5, f"横線が長すぎる: {widest}"

    def test_ヘッダ背景も表の幅に収まる(self, editor) -> None:
        editor.setPlainText("| aaa | bbb |\n|---|---|\n| ddd | eee |\n\n本文\n")
        move_to(editor, 4)

        header = [d for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_HEADER]
        assert header
        assert header[0].rect.width() < editor.viewport().width() * 0.5

    def test_横線の右端が右の縦線と一致する(self, editor) -> None:
        editor.setPlainText("| aaa | bbb |\n|---|---|\n| ddd | eee |\n\n本文\n")
        move_to(editor, 4)

        rules = self._rules(editor)
        vertical = [d for d in rules if d.rect.width() <= d.rect.height()]
        horizontal = [d for d in rules if d.rect.width() > d.rect.height()]
        rightmost = max(d.rect.left() for d in vertical)
        assert horizontal[0].rect.right() == pytest.approx(rightmost + 1, abs=1.5)

    def test_1列の表も描ける(self, editor) -> None:
        """閉じの `|` が無くても整形が補うので、1 列でも表として成立する。"""
        editor.setPlainText("| aaa\n|---\n| ddd\n\n本文\n")
        move_to(editor, 4)

        assert editor.toPlainText().startswith("| aaa |")
        vertical = [d for d in self._rules(editor) if d.rect.width() <= d.rect.height()]
        assert len(vertical) == 2  # 左端と右端
