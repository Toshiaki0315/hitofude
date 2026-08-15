"""表の罫線描画と自動整形のテスト（ユーザー要望 / spec §5.2 の描画フック）。

`|` は削除せず極小化して隠し、線は `paintEvent` で描く（R4）。
キャレット位置とソースのオフセットは 1:1 のまま。
"""

import pytest

from hitofude.core.table import display_width
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

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


class TestCellPadding:
    """セルの余白（ユーザー要望）。

    文字が罫線に接していて読みにくかった。**行の高さと横位置を作るのに
    テキストは変えない**（R1）。`|` は罫線として描くので画面には出ない。
    その透明な文字に大きさと字送りを持たせて余白にする。
    """

    TABLE = "| 記法 | 書き方 |\n| ---- | ------ |\n| 強調 | 太字   |\n"

    def rows(self, editor):
        document = editor.document()
        layout = document.documentLayout()
        return [
            layout.blockBoundingRect(document.findBlockByNumber(n)).height()
            for n in range(document.blockCount())
        ]

    def pipe_x(self, editor, line: int) -> list[float]:
        # レイアウト前に `lineForTextPosition()` を叩くと落ちる。
        # 描画側と同じヘルパを通し、組み終わるまで待つ
        from PySide6.QtWidgets import QApplication

        from hitofude.editor.painter_overlay import _column_x

        QApplication.processEvents()
        block = editor.document().findBlockByNumber(line)
        return [_column_x(block, i) for i, char in enumerate(block.text()) if char == "|"]

    def test_表の行は段落より高い(self, editor) -> None:
        editor.setPlainText("ふつうの段落\n")
        plain = self.rows(editor)[0]

        editor.setPlainText(self.TABLE)
        assert self.rows(editor)[0] > plain

    def test_上下の余白は行の高さで作る(self) -> None:
        """余白を 0 にしたときより高くなること。

        **px を狙って逆算しない。** 行の高さは実際に並ぶ文字（和文か欧文か、
        フォントがその字を持つか）で決まり、計算では当たらない（実測で確認）。
        """
        import hitofude.editor.highlighter as module

        original = module.CELL_PADDING_POINTS
        try:
            module.CELL_PADDING_POINTS = 0.0
            bare = self._table_height()
            module.CELL_PADDING_POINTS = original
            padded = self._table_height()
        finally:
            module.CELL_PADDING_POINTS = original
        assert padded > bare + 5

    def test_左右の余白は字送りで作る(self, editor) -> None:
        """セルの幅が広がる＝中身が罫線から離れる。

        **同じ行どうしで比べる。** フォントが違う行と比べても分からない。
        """
        import hitofude.editor.highlighter as module

        original = module.CELL_PADDING
        try:
            module.CELL_PADDING = 0.0
            editor._highlighter._cell_pad = None
            editor.setPlainText(self.TABLE)
            editor._highlighter.rehighlight()
            bare = self.pipe_x(editor, 2)
        finally:
            module.CELL_PADDING = original
            editor._highlighter._cell_pad = None

        editor.setPlainText(self.TABLE)
        editor._highlighter.rehighlight()
        padded = self.pipe_x(editor, 2)
        assert padded[1] - padded[0] > bare[1] - bare[0]

    def test_本文は変わらない(self, editor) -> None:
        """R1: 見た目を変えてもソースは触らない。"""
        editor.setPlainText(self.TABLE)
        assert editor.toPlainText() == self.TABLE

    def test_Undoを消費しない(self, editor) -> None:
        editor.setPlainText(self.TABLE)
        editor.moveCursor(editor.textCursor().MoveOperation.End)
        editor.textCursor().insertText("追記")
        editor.undo()
        assert "追記" not in editor.toPlainText()

    def test_段落の高さは変えない(self, editor) -> None:
        editor.setPlainText("ふつうの段落\n" + self.TABLE)
        heights = self.rows(editor)
        assert heights[0] < heights[1]

    def test_本文の行どうしはずれない(self, editor) -> None:
        """余白は全行へ同じだけ足す。

        ヘッダ行だけは太字のぶん幅が違うが、それは**この変更の前からある**
        別の話（実測で確認済み）。ここでは本文の行どうしを見る。
        """
        editor.setPlainText(self.TABLE + "| 斜体 | 細字   |\n")
        assert self.pipe_x(editor, 2) == pytest.approx(self.pipe_x(editor, 3))

    def test_文字サイズを変えても余白が残る(self, editor) -> None:
        editor.setPlainText(self.TABLE)
        small = self.rows(editor)[0]
        editor.set_base_point_size(24.0)
        editor.setPlainText(self.TABLE)
        assert self.rows(editor)[0] > small

    def test_カーソルを入れても高さが変わらない(self, editor) -> None:
        """**余白は `|` ではなく隣の空白に持たせている。** パイプに持たせると、
        カーソルを入れて `|` を表示したときに余白ごと消えて行が縮む。"""
        editor.setPlainText(self.TABLE)
        before = self.rows(editor)

        block = editor.document().findBlockByNumber(2)
        cursor = editor.textCursor()
        cursor.setPosition(block.position() + 3)
        editor.setTextCursor(cursor)
        assert self.rows(editor) == before

    def _table_height(self) -> float:
        from PySide6.QtWidgets import QApplication

        from hitofude.editor.editor_widget import MarkdownEditor

        widget = MarkdownEditor()
        widget.resize(500, 200)
        widget.show()
        widget.setPlainText(self.TABLE)
        QApplication.processEvents()
        document = widget.document()
        height = document.documentLayout().blockBoundingRect(document.findBlockByNumber(2)).height()
        widget.deleteLater()
        return height


class TestColumnAlignment:
    """桁が揃うこと（C-1 / 既知の不具合）。

    **原因は文字幅の見積もりと実際の描画幅のずれ。** 整形は東アジアの文字幅
    （全角 2・半角 1）で桁を数えるが、等幅フォントに CJK が無いので代替
    フォントが使われ、実際の比は 2.00 ではない。15pt での実測:

        あ 1.66 倍 / ① 1.66 倍（見積もりは 1）/ 🍎 1.91 倍

    同じ種類の文字だけの表は偶然揃うが、行ごとに種類が混ざると崩れる。
    整形（`format_table`）は文字数で揃えるので、**画面側で字送りを足して
    合わせる**。ソースは触らない（R1）。
    """

    def pipe_positions(self, editor, line: int) -> list[float]:
        document = editor.document()
        block = document.findBlockByNumber(line)
        document.documentLayout().blockBoundingRect(block)
        layout = block.layout()
        found = layout.lineAt(0)
        return [found.cursorToX(i)[0] for i, ch in enumerate(block.text()) if ch == "|"]

    def gap(self, editor, source: str) -> float:
        from PySide6.QtGui import QTextCursor

        editor.setPlainText(source)
        editor.moveCursor(QTextCursor.MoveOperation.End)
        head = self.pipe_positions(editor, 0)
        body = self.pipe_positions(editor, 2)
        assert len(head) == len(body), f"桁数が違う: {head} / {body}"
        return max((abs(a - b) for a, b in zip(head, body, strict=True)), default=0.0)

    def test_日本語だけの表は揃う(self, editor) -> None:
        assert self.gap(editor, "| 項目 | 担当 |\n| --- | --- |\n| 設計 | 野村 |\n\n末尾\n") < 1

    def test_英数字だけの表は揃う(self, editor) -> None:
        assert self.gap(editor, "| Item | Owner |\n| --- | --- |\n| Plan | Nomura |\n\n末尾\n") < 1

    def test_矢印や丸数字が混ざっても揃う(self, editor) -> None:
        """**ずれを再現した組み合わせ。** 実測で 20px ずれていた。"""
        assert self.gap(editor, "| → 前 | ① 番 |\n| --- | --- |\n| 設計 | 野村 |\n\n末尾\n") < 2

    def test_絵文字は揃わないことがある(self, editor) -> None:
        """**既知の制限。** 🍎 の実測は半角の 2.30 倍で、空白（1 桁）を
        足し引きしても合わせようがない。整形は桁数では揃えるので、
        ずれても壊れはしない。"""
        assert self.gap(editor, "| 🍎 林檎 | 状態 |\n| --- | --- |\n| 通常 | 済み |\n\n末尾\n") < 12

    def test_英数字と日本語が混ざっても揃う(self, editor) -> None:
        assert self.gap(editor, "| ID | 名前 |\n| --- | --- |\n| あ | Nomura |\n\n末尾\n") < 2

    def test_ソースは変えない(self, editor) -> None:
        """R1。揃えるのは見た目だけ。"""
        from PySide6.QtGui import QTextCursor

        source = "| → 前 | ① 番 |\n| --- | --- |\n| 設計 | 野村 |\n\n末尾\n"
        editor.setPlainText(source)
        editor.moveCursor(QTextCursor.MoveOperation.End)
        assert editor.toPlainText().count("→") == 1
        assert "①" in editor.toPlainText()


WIDE_TABLE = (
    "| aaa          | bbb                                              | ccc        |\n"
    "| ------------ | ------------------------------------------------ | ---------- |\n"
    "| aaaaaaaaaaaa | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbcccccccccccccccccc | vvvvvvvvvv |\n"
    "\n本文\n"
)


class TestTooWide:
    """幅に収まらない表は**生の Markdown を見せる**（ユーザー報告 / ADR-0003 追記）。

    行が折り返すと「ソースの 1 行 = 画面の 1 行」が崩れ、`|` の x 座標が
    折り返し先の行の座標に戻る。実測（viewport 720px）:

        ふつうの行   : 表示 1 行  | の x = [4, 168, 331, 474]
        長いセルの行 : 表示 3 行  | の x = [4, 168, 766, 126]

    この位置に罫線を引いても意味を持たない。**描けないときは描かない**で、
    記号を出してソースとして直せるようにする（キャレットを表に入れたときと
    同じ見え方。覚えることが増えない）。
    """

    def test_縦線を隠さない(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert hidden_ranges(editor, 0) == [], "収まらないのに `|` を隠している"

    def test_区切り行も見せる(self, editor) -> None:
        """`|---|---|` を隠したままだと、表の形が読めない。"""
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert hidden_ranges(editor, 1) == []

    def test_罫線を引かない(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert DecorationKind.TABLE_RULE not in kinds(editor)

    def test_ヘッダ背景も敷かない(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert DecorationKind.TABLE_HEADER not in kinds(editor)

    def test_収まる表は今まで通り(self, editor) -> None:
        """狭い表を巻き添えにしない。"""
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert DecorationKind.TABLE_RULE in kinds(editor)
        assert hidden_ranges(editor, 0)

    def test_文字は消さない(self, editor) -> None:
        """R4: 収まらなくてもソースはそのまま。"""
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert editor.toPlainText() == WIDE_TABLE

    def test_短くすれば表に戻る(self, editor) -> None:
        """収まる幅まで縮めれば、そのまま表として描かれる。"""
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert DecorationKind.TABLE_RULE not in kinds(editor)

        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert DecorationKind.TABLE_RULE in kinds(editor)
        assert hidden_ranges(editor, 0)

    def test_ウィンドウを広げても桁数は増えない(self, editor) -> None:
        """**本文は最大 720px**（spec §5.1）。広げても本文の幅は変わらない。

        「ウィンドウを広げれば直る」と誤解しないための固定。収まらない表は
        セルを短くするしかない（実測: 720px = 71 桁）。
        """
        before = editor.table_columns()
        editor.resize(1900, 300)
        editor.show()
        assert editor.table_columns() == before
