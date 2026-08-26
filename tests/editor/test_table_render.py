"""表の罫線描画と自動整形のテスト（ユーザー要望 / spec §5.2 の描画フック）。

`|` は削除せず極小化して隠し、線は `paintEvent` で描く（R4）。
キャレット位置とソースのオフセットは 1:1 のまま。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

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

    def test_整形をundoしたら離れても再整形しない(self, editor) -> None:
        """整形は見た目の都合。Redo の待ちがあるうちに本文へ触ると Redo
        スタックが消え、Cmd+Z で戻した整形をやり直せなくなる（回帰）。"""
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)
        formatted = editor.toPlainText()

        editor.undo()
        original = editor.toPlainText()
        assert original != formatted  # 整形が 1 手で戻っている

        move_to(editor, 2)
        move_to(editor, 5)
        assert editor.toPlainText() == original  # 再整形で Redo を消さない

    def test_undoした整形はredoで戻せる(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)
        formatted = editor.toPlainText()

        editor.undo()
        move_to(editor, 2)
        move_to(editor, 5)
        editor.redo()
        assert editor.toPlainText() == formatted

    def test_undoの後でも編集すれば整形は再開する(self, editor) -> None:
        """Redo 保全のガードが掛かりっぱなしにならないこと。"""
        from PySide6.QtGui import QTextCursor

        editor.setPlainText(TABLE)
        move_to(editor, 2)
        move_to(editor, 5)
        editor.undo()

        # 表のセルを編集する（Redo の待ちはここで消える）
        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(2).position())
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        editor.setTextCursor(cursor)
        editor.textCursor().insertText(" 追記")

        move_to(editor, 5)
        lines = editor.toPlainText().split("\n")[:4]
        assert len({display_width(line) for line in lines}) == 1, lines


class TestHiding:
    def test_表の行は丸ごと隠す(self, editor) -> None:
        """描画側が本文フォントで組む（ADR-0029）ので、ソースの行は隠れる。"""
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert hidden_ranges(editor, 0), "表の行が生のまま見えている"

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

    def test_カーソルを入れると生のMarkdownに戻る(self, editor) -> None:
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
        vertical = {round(d.rect.x(), 1) for d in rules if d.rect.width() < d.rect.height()}
        assert len(vertical) == 3  # 2 列 = 縦線 3 本（行ごとに引くので x で数える）

    def test_キャレットの行には文字を描かない(self, editor) -> None:
        """リビールは行単位（ADR-0017 / 0029）。生の Markdown が見えている
        行の上に、描いた文字を重ねない。他の行は表のまま読める。"""
        editor.setPlainText(TABLE)
        move_to(editor, 2)
        rules = [d for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_RULE]
        assert rules, "表全体の線が消えている"
        block = editor.document().findBlockByNumber(2)
        geometry = editor.blockBoundingGeometry(block)
        texts = [
            d
            for d in visible_decorations(editor)
            if d.kind in (DecorationKind.TABLE_TEXT, DecorationKind.TABLE_TEXT_HEADER)
        ]
        overlapping = [d for d in texts if geometry.top() <= d.rect.top() < geometry.bottom()]
        assert overlapping == [], "キャレットの行に文字を重ねている"

    def test_表が無ければ描かない(self, editor) -> None:
        editor.setPlainText("本文だけ\n")
        assert DecorationKind.TABLE_RULE not in kinds(editor)

    def test_1行だけでは表にしない(self, editor) -> None:
        editor.setPlainText("| これは表ではない |\n\n本文\n")
        move_to(editor, 2)
        assert DecorationKind.TABLE_RULE not in kinds(editor)


class TestIncompleteTable:
    """区切り行が来るまでは表として成立していない（ユーザー報告 2026-08-26）。

    成立前の行を隠すと、painter は区切り行の無い並びを描かないため、
    書きかけの 1 行目が丸ごと消える。成立するまでは生のまま見せる。
    """

    def test_書きかけの1行目は隠さない(self, editor) -> None:
        editor.setPlainText("|aaa|bbb|ccc|\n\n本文\n")
        move_to(editor, 2)
        assert hidden_ranges(editor, 0) == [], "区切り行が無いのに隠している"

    def test_区切り行が先頭でも表にしない(self, editor) -> None:
        """ヘッダの無い並びは GFM でも表にならない。"""
        editor.setPlainText("|---|---|\n|aaa|bbb|\n\n本文\n")
        move_to(editor, 3)
        assert hidden_ranges(editor, 0) == []
        assert hidden_ranges(editor, 1) == []

    def test_区切り行が揃えば隠して描く(self, editor) -> None:
        editor.setPlainText("|aaa|bbb|ccc|\n|---|---|---|\n\n本文\n")
        move_to(editor, 3)
        assert hidden_ranges(editor, 0)
        assert DecorationKind.TABLE_RULE in kinds(editor)

    def test_打ちながら作っても1行目は消えない(self, editor, qtbot) -> None:
        """ユーザーの再現手順そのまま: ヘッダ → Enter → 区切り行 → Enter。"""
        editor.setPlainText("")
        qtbot.keyClicks(editor, "|aaa|bbb|ccc|")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert hidden_ranges(editor, 0) == [], "ヘッダ行が一旦消える"
        qtbot.keyClicks(editor, "|---|---|---|")
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert hidden_ranges(editor, 0), "区切り行を確定しても表として組まれない"
        assert DecorationKind.TABLE_RULE in kinds(editor)


class TestHeaderStyle:
    """ヘッダの太字は描画側の仕事になった（ADR-0029）。

    ソースの行は隠れているので、文字書式ではなく**描く種類**で見る。
    """

    def test_ヘッダ行はヘッダとして描く(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        found = kinds(editor)
        assert DecorationKind.TABLE_TEXT_HEADER in found

    def test_本体行は本体として描く(self, editor) -> None:
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        found = kinds(editor)
        assert DecorationKind.TABLE_TEXT in found


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
        vertical = {
            round(d.rect.x(), 1) for d in self._rules(editor) if d.rect.width() <= d.rect.height()
        }
        assert len(vertical) == 2  # 左端と右端（行ごとに引くので x で数える）


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

    def test_上下の余白は予約の高さで作る(self) -> None:
        """余白を 0 にしたときより高くなること（ADR-0029: 描画行の高さは
        本文の行送り + WRAP_CELL_PADDING×2 で予約する）。"""
        import hitofude.editor.highlighter as module

        original = module.WRAP_CELL_PADDING
        try:
            module.WRAP_CELL_PADDING = 0.0
            bare = self._table_height()
            module.WRAP_CELL_PADDING = original
            padded = self._table_height()
        finally:
            module.WRAP_CELL_PADDING = original
        assert padded > bare + 5

    def test_左右の余白は描画の定数で作る(self, editor) -> None:
        """文字の矩形が縦線（列の左端）から CELL_PAD ぶん離れている（ADR-0029）。"""
        from hitofude.editor.painter_overlay import CELL_PAD, DecorationKind, visible_decorations

        editor.setPlainText(self.TABLE)
        move_to(editor, 5)
        rules = [d for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_RULE]
        lefts = sorted({d.rect.x() for d in rules if d.rect.width() < d.rect.height()})
        texts = [
            d
            for d in visible_decorations(editor)
            if d.kind in (DecorationKind.TABLE_TEXT, DecorationKind.TABLE_TEXT_HEADER)
        ]
        first_column = min(d.rect.x() for d in texts)
        assert first_column == pytest.approx(lefts[0] + 1 + CELL_PAD, abs=0.6)

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
        """列の左端は全行で同じ（描画側が同じ列幅で組む。ADR-0029）。"""
        from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

        editor.setPlainText(self.TABLE + "| 斜体 | 細字   |\n")
        move_to(editor, 5)
        texts = [d for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_TEXT]
        xs = sorted({round(d.rect.x(), 1) for d in texts})
        assert len(xs) == 2  # 2 列 = 左端は 2 種類だけ（行ごとにずれない）

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
        ずれても壊れはしない。

        罫線は実在する `|` の位置（UTF-16 変換後）に描くようになった。
        以前は絵文字の後ろの罫線が 1 文字ぶん左へずれて描かれ、整形の
        ずれと偶然打ち消し合って見かけの差が小さかった。今は整形由来の
        ずれ（0.30 倍 × 絵文字数）が線の位置に素直に出る。"""
        assert self.gap(editor, "| 🍎 林檎 | 状態 |\n| --- | --- |\n| 通常 | 済み |\n\n末尾\n") < 20

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
    """幅に収まらない表は**セルを折り返して描く**（ADR-0017）。

    以前は生の Markdown へ落としていた（ADR-0003 追記）。ソースの行が
    折り返すと「ソースの 1 行 = 画面の 1 行」が崩れ、`|` の x 座標に線を
    引けなかったため。折り返し表示は列の位置を桁数から決め直すので、
    この制約を受けない。キャレットを入れた行だけ生に戻るのは今まで通り。
    """

    def test_縦線ごと行を隠す(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert hidden_ranges(editor, 0), "折り返し表示なのに生の行が見えている"

    def test_区切り行も隠す(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert hidden_ranges(editor, 1)

    def test_罫線を引く(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert DecorationKind.TABLE_RULE in kinds(editor)

    def test_ヘッダ背景も敷く(self, editor) -> None:
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert DecorationKind.TABLE_HEADER in kinds(editor)

    def test_収まる表も同じ仕組みで描く(self, editor) -> None:
        """描き方は 1 つだけ（ADR-0029）。狭い表も描画側が組む。"""
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        assert DecorationKind.TABLE_RULE in kinds(editor)
        assert hidden_ranges(editor, 0)

    def test_文字は消さない(self, editor) -> None:
        """R4: 収まらなくてもソースはそのまま。"""
        editor.setPlainText(WIDE_TABLE)
        move_to(editor, 4)
        assert editor.toPlainText() == WIDE_TABLE

    def test_収まる表は折り返さない(self, editor) -> None:
        """描き方は 1 つでも、収まる表のセルは 1 行のまま（自然幅で組む）。"""
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        block = editor.document().findBlockByNumber(0)
        wrapped = getattr(block.userData(), "wrapped", None)
        assert wrapped is not None
        assert wrapped.lines == 1

    def test_列幅は自然幅より広げない(self, editor) -> None:
        """使える幅が余っていても、列は中身の最長ぶんだけ（間延びさせない）。"""
        from PySide6.QtGui import QFontMetricsF

        editor.setPlainText(TABLE)
        move_to(editor, 5)
        wrapped = editor.document().findBlockByNumber(0).userData().wrapped
        metrics = QFontMetricsF(editor.font())
        natural = max(
            metrics.horizontalAdvance(cell.strip())
            for line in TABLE.splitlines()
            if line.startswith("|") and "---" not in line
            for cell in line.split("|")[1:-1]
        )
        assert max(wrapped.col_widths) <= natural + 1


class TestMultipleTables:
    """**画面に表が 2 つ見えるとき**（ユーザー報告）。

    1 つ目を描いたあと、桁数を入れておいた変数に縦線の x 座標を入れて
    しまっていた。2 つ目の幅の判定が `fits(文字列, 座標の一覧)` になり、
    `paintEvent` の中で `TypeError` が飛ぶ。**例外が出ると本文ごと
    描かれない**ので、スクロールした先が真っ白になった。

    表を 2 つ入れるだけでは足りない。**同時に見えていること**が要る
    （窓が小さいと 1 つしか走査されず、素通りする）。
    """

    @pytest.fixture
    def tall(self, qtbot) -> MarkdownEditor:
        widget = MarkdownEditor()
        qtbot.addWidget(widget)
        widget.resize(760, 900)  # 表が 2 つとも入る高さ
        widget.show()
        return widget

    def test_2つ目の表にも罫線が引かれる(self, tall) -> None:
        tall.setPlainText(TABLE + "\n" + TABLE)
        move_to(tall, tall.document().blockCount() - 1)

        rules = [d for d in visible_decorations(tall) if d.kind is DecorationKind.TABLE_RULE]
        tops = sorted({round(d.rect.top()) for d in rules})
        assert len(tops) >= 2
        # 2 つ目の表は 1 つ目よりずっと下にある
        assert max(tops) - min(tops) > 100

    def test_表が2つでも本文の飾りが消えない(self, tall) -> None:
        """例外は `visible_decorations` 全体を巻き添えにする。"""
        tall.setPlainText(TABLE + "> 引用\n\n" + TABLE)
        move_to(tall, tall.document().blockCount() - 1)

        assert DecorationKind.QUOTE_BAR in kinds(tall)


class TestScrollRepaint:
    """**スクロールしたら画面全体を描き直す**（ユーザー報告）。

    Qt は新しく出た帯だけを塗り直す。ふつうはそれで足りるが、飾りは
    **画面の外の行にも依存する**。表のヘッダの帯は区切り行（`|---|`）が
    見えて初めて決まるので、区切り行が下から入ってきた時点では、
    ヘッダ行はもう帯の外にある。塗られないまま白く残り、それが
    スクロールに合わせて上へずれていく。

    カーソルキーで動かすと直るのは、キャレット移動が別途
    塗り直しを起こすため。
    """

    def test_スクロールすると画面全体が塗り直される(self, qtbot) -> None:
        rects: list[tuple[int, int]] = []

        class Probe(MarkdownEditor):
            def paintEvent(self, event) -> None:
                rects.append((event.rect().top(), event.rect().height()))
                super().paintEvent(event)

        editor = Probe()
        qtbot.addWidget(editor)
        editor.resize(760, 900)  # 1 行ぶんが画面に対して十分小さい高さ
        editor.show()
        editor.setPlainText("本文\n" * 200)
        QApplication.processEvents()

        rects.clear()
        editor.verticalScrollBar().setValue(1)
        QApplication.processEvents()

        height = editor.viewport().height()
        assert rects, "スクロールで再描画が起きていない"
        assert all(top == 0 and h >= height for top, h in rects), rects


class TestManualFits:
    """**同梱のマニュアルの表は、幅に収まっていること。**

    収まらない表は罫線を描かず生の Markdown で出す（ADR-0003 追記）。
    仕様どおりの動きだが、**アプリ自身の見本がそう表示されるのは困る**。
    実際、ショートカットの表は 76 桁あって罫線が出ていなかった。

    ここが赤くなったら、表の中身を削るか列を減らすこと。桁を広げる方向は
    採らない（本文の幅は読みやすさのために 720px で決めてある）。
    """

    def test_マニュアルの表はすべて罫線が出る(self, qtbot) -> None:
        from pathlib import Path

        from hitofude.core.table import display_width, fits

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        editor.resize(1370, 900)
        editor.show()

        manual = Path("hitofude/resources/manual.md").read_text(encoding="utf-8")
        editor.setPlainText(manual)

        # 描画は幅に依らず組める（ADR-0029）ので、これは**ソースの行儀**の
        # 検査。生の .md を他所で開いても読める幅（標準の本文幅 ≒ 69 桁）に
        # 収めておく
        columns = 69
        over = [
            line for line in manual.split("\n") if line.startswith("|") and not fits(line, columns)
        ]
        assert not over, [f"{display_width(line)} 桁 > {columns}: {line[:40]}" for line in over[:3]]


WIDE_CELLS = (
    "| 項目 | 説明 |\n| --- | --- |\n| 短い | " + "長い説明が続きます " * 12 + "|\n\n末尾\n"
)


class TestWrappedTable:
    """収まらない表はセルを折り返して描く（案 B / ADR-0017）。

    以前は生の Markdown へ落としていた。ソースは触らず（R1）、
    画像と同じ手口（ADR-0004: 先頭 1 文字の拡大で行高を予約し、
    絵は paintEvent で描く）で表示だけを折り返す。
    カーソルが入った行は今まで通り生で編集できる。
    """

    def wrapped_of(self, editor: MarkdownEditor, line: int):
        data = editor.document().findBlockByNumber(line).userData()
        return getattr(data, "wrapped", None)

    def test_収まらない行は隠して高さを予約する(self, editor) -> None:
        editor.setPlainText(WIDE_CELLS)
        move_to(editor, 4)  # 表の外へ

        block = editor.document().findBlockByNumber(2)
        formats = block.layout().formats()
        base = editor.font().pointSizeF()
        assert any(f.format.fontPointSize() == pytest.approx(0.5) for f in formats)  # 隠し
        assert any(f.format.fontPointSize() > base * 1.5 for f in formats)  # 高さの予約

    def test_行の高さが折り返しぶん高くなる(self, editor) -> None:
        editor.setPlainText(WIDE_CELLS)
        move_to(editor, 4)

        normal = editor.blockBoundingGeometry(editor.document().findBlockByNumber(4)).height()
        wrapped = editor.blockBoundingGeometry(editor.document().findBlockByNumber(2)).height()
        assert wrapped > normal * 2  # 少なくとも 2 行ぶんは折り返している

    def test_BlockDataに折り返しの中身が載る(self, editor) -> None:
        editor.setPlainText(WIDE_CELLS)
        move_to(editor, 4)

        wrapped = self.wrapped_of(editor, 2)
        assert wrapped is not None
        assert "短い" in wrapped.cells[0][0]
        assert len(wrapped.cells[1]) >= 2  # 長いセルは複数行に折れている

    def test_カーソルを入れると生の行に戻る(self, editor) -> None:
        editor.setPlainText(WIDE_CELLS)
        move_to(editor, 4)
        move_to(editor, 2)  # 折り返し行へ

        block = editor.document().findBlockByNumber(2)
        formats = block.layout().formats()
        assert not any(f.format.fontPointSize() == pytest.approx(0.5) for f in formats)
        assert self.wrapped_of(editor, 2) is None

    def test_収まる表も描画側が組む(self, editor) -> None:
        """描き方は 1 つだけ（ADR-0029）。収まる表もセルは 1 行で高さは低いまま。"""
        editor.setPlainText(TABLE)
        move_to(editor, 5)
        block = editor.document().findBlockByNumber(2)
        wrapped = getattr(block.userData(), "wrapped", None)
        assert wrapped is not None and wrapped.lines == 1

    def test_Rawでは生のまま(self, editor) -> None:
        editor.setPlainText(WIDE_CELLS)
        editor.set_source_mode(True)
        move_to(editor, 4)
        assert self.wrapped_of(editor, 2) is None

    def test_折り返したセルの文字が描かれる(self, editor) -> None:
        from hitofude.editor.painter_overlay import DecorationKind, visible_decorations

        editor.setPlainText(WIDE_CELLS)
        move_to(editor, 4)

        texts = [d.text for d in visible_decorations(editor) if d.kind is DecorationKind.TABLE_TEXT]
        assert any("短い" in t for t in texts)
        assert any("長い説明" in t for t in texts)


class TestForcedBreakInEditor:
    """セル内の `<br>`（ユーザー要望 2026-08-25 / ADR-0028）。

    幅に収まる表でも、`<br>` があれば折り返し描画に入る（行の高さを
    変えるには ADR-0017 の予約機構が要る）。列幅は自然幅のままなので、
    見た目は「行が高くなる」だけ。
    """

    NOTE = "| 項目 | 中身 |\n| --- | --- |\n| 上<br>下 | x |\n\n末尾\n"

    def wrapped_of(self, editor: MarkdownEditor, line: int):
        data = editor.document().findBlockByNumber(line).userData()
        return getattr(data, "wrapped", None)

    def test_収まる表でも折り返し表示に入る(self, editor) -> None:
        editor.setPlainText(self.NOTE)
        move_to(editor, 4)
        wrapped = self.wrapped_of(editor, 2)
        assert wrapped is not None
        assert wrapped.cells[0] == ("上", "下")
        assert wrapped.lines == 2

    def test_brの記号は描く中身に出ない(self, editor) -> None:
        editor.setPlainText(self.NOTE)
        move_to(editor, 4)
        wrapped = self.wrapped_of(editor, 2)
        assert all("<br" not in piece for cell in wrapped.cells for piece in cell)

    def test_行の高さが2行ぶんになる(self, editor) -> None:
        editor.setPlainText(self.NOTE)
        move_to(editor, 4)
        plain = editor.blockBoundingGeometry(editor.document().findBlockByNumber(4)).height()
        tall = editor.blockBoundingGeometry(editor.document().findBlockByNumber(2)).height()
        # 表の行送りは本文より小さい（等幅・詰め）ので、2 行でも本文の
        # 2 倍にはならない。1.4 倍あれば 2 行ぶん予約されている
        assert tall > plain * 1.4

    def test_brの無い収まる表は1行のまま(self, editor) -> None:
        editor.setPlainText("| A | B |\n| --- | --- |\n| a | b |\n\n末尾\n")
        move_to(editor, 4)
        wrapped = self.wrapped_of(editor, 2)
        assert wrapped is not None and wrapped.lines == 1

    def test_キャレットを入れた行は生に戻る(self, editor) -> None:
        editor.setPlainText(self.NOTE)
        move_to(editor, 2)
        assert self.wrapped_of(editor, 2) is None  # 生の Markdown で編集できる


class TestHiddenSourceIsInvisible:
    """隠したソース文字列を描かせない（ユーザー報告 2026-08-25）。

    0.5pt に潰しただけだと色が本文色のままで、潰れた文字がベースライン上に
    **灰色のヘアライン**として残る。折り返し表示のセルの空き（末尾の
    `<br>` や、高さの違うセルの下）で露出していた。
    """

    def test_隠した文字は透明(self, editor) -> None:
        editor.setPlainText("| 項目 | 中身 |\n| --- | --- |\n| 上<br>下 | x |\n\n末尾\n")
        move_to(editor, 4)
        block = editor.document().findBlockByNumber(2)
        # format ラッパは formats() のリストと寿命を共にする。リスト内包で
        # 抜き出すと C++ 側が先に消える（PySide の所有権）ので、その場で見る
        seen = 0
        for piece in block.layout().formats():
            if piece.format.fontPointSize() != pytest.approx(0.5):
                continue
            seen += 1
            assert piece.format.foreground().color().alpha() == 0, (
                "隠した文字に色が残っている（ベースラインにヘアラインが出る）"
            )
        assert seen, "隠し書式が無い"
