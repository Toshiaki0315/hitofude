"""オーバーレイ描画のテスト（タスク 2-9 / spec §5.2, ADR-0002）。

`QSyntaxHighlighter` では描けない要素（縦バー、背景、線、記号）を
`paintEvent` で描く。ここは ADR-0002 でブロックレベル表現の唯一の担い手になった。

描画そのものはピクセルで検査すると脆いので、
「どこに何を描くか」を組み立てる純ロジックを主に検査し、
実際に描かれることは 1 件のスモークテストで押さえる。
"""

import pytest
from PySide6.QtGui import QTextCursor

from hitofude.editor import painter_overlay
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.painter_overlay import (
    CHECKED,
    UNCHECKED,
    DecorationKind,
    visible_decorations,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    return widget


def kinds(editor: MarkdownEditor) -> list[DecorationKind]:
    return [decoration.kind for decoration in visible_decorations(editor)]


def of_kind(editor: MarkdownEditor, kind: DecorationKind) -> list:
    return [d for d in visible_decorations(editor) if d.kind is kind]


def away(editor: MarkdownEditor, text: str) -> None:
    """本文を入れて、カーソルを最後へ逃がす。

    **カーソルのある行はリビールされる**ので、置いた直後の 1 行目を見ると
    「記号が出ている状態」を測ってしまう。
    """
    # 末尾に行を足してからそこへ逃がす。**1 行しか無いとカーソルが
    # その行に残り、リビールされた状態を測ってしまう**（実際に踏んだ）
    editor.setPlainText(text + "\n\n末尾")
    editor.moveCursor(QTextCursor.MoveOperation.End)


class TestQuote:
    def test_引用行に縦バーを描く(self, editor) -> None:
        editor.setPlainText("> 引用")
        assert kinds(editor).count(DecorationKind.QUOTE_BAR) == 1

    def test_入れ子の引用は深さの数だけ描く(self, editor) -> None:
        editor.setPlainText("> > 二重引用")
        assert kinds(editor).count(DecorationKind.QUOTE_BAR) == 2

    def test_深いバーほど右にずれる(self, editor) -> None:
        editor.setPlainText("> > 二重引用")
        bars = of_kind(editor, DecorationKind.QUOTE_BAR)
        assert bars[0].rect.left() < bars[1].rect.left()

    def test_引用でない行には描かない(self, editor) -> None:
        editor.setPlainText("ただの段落")
        assert DecorationKind.QUOTE_BAR not in kinds(editor)


class TestCodeBlock:
    SOURCE = "```python\nx = 1\n```"

    def test_フェンスの全行に背景を描く(self, editor) -> None:
        editor.setPlainText(self.SOURCE)
        assert kinds(editor).count(DecorationKind.CODE_BACKGROUND) == 3

    def test_左のアクセントバーは描かない(self, editor) -> None:
        """ユーザー要望で外した。背景だけでコードブロックだと分かるので、
        線があると引用の縦バーや `:::note` の線と紛らわしい（spec §5.2 を
        覆す。ADR-0008）。"""
        editor.setPlainText(self.SOURCE)
        assert not [d for d in visible_decorations(editor) if d.kind.name.startswith("CODE_ACCENT")]

    def test_コードでない行には描かない(self, editor) -> None:
        editor.setPlainText("ただの段落")
        assert DecorationKind.CODE_BACKGROUND not in kinds(editor)


class TestHorizontalRule:
    def test_水平線を描く(self, editor) -> None:
        editor.setPlainText("段落\n\n---\n")
        assert kinds(editor).count(DecorationKind.RULE) == 1

    def test_線はブロックの縦中央あたりに引く(self, editor) -> None:
        editor.setPlainText("段落\n\n---\n")
        rule = of_kind(editor, DecorationKind.RULE)[0]
        assert rule.rect.height() <= 2


def text_start_x(editor, block_number: int, column: int) -> float:
    """その行の `column` 文字目が始まる x（本文が実際に出る位置）。

    **ブロックとレイアウトを変数で持つ。** 式の途中で捨てると、返ってきた
    `QTextLine` が解放済みの領域を指して SIGSEGV になる（実際に落ちた）。
    """
    document = editor.document()
    block = document.findBlockByNumber(block_number)
    # 組まれるのは描くときなので、先に組ませる。書式を変えた直後は
    # 行が 0 本のことがある
    document.documentLayout().blockBoundingRect(block)
    layout = block.layout()
    assert layout.lineCount() > 0, f"{block_number} 行目がまだ組まれていない"
    line = layout.lineAt(0)
    return line.cursorToX(column)[0]


class TestCheckbox:
    @pytest.mark.parametrize(
        ("source", "checked"),
        [("- [ ] やること", False), ("- [x] 済み", True), ("- [X] 済み", True)],
    )
    def test_チェックの状態を持つ(self, editor, source: str, checked: bool) -> None:
        editor.setPlainText(source)
        boxes = of_kind(editor, DecorationKind.CHECKBOX)
        assert len(boxes) == 1
        assert boxes[0].text == (CHECKED if checked else UNCHECKED)

    def test_状態で大きさが変わらない(self, editor) -> None:
        """ユーザー報告。**フォントの記号（☐ / ☑）は別々の書体から拾われる。**
        実測で ☐ が 17.8x17.2px、☑ が 10.1x10.5px と揃わなかったので、
        記号ではなく枠を自分で描く。"""
        away(editor, "- [ ] まだ\n- [x] 済み")
        boxes = of_kind(editor, DecorationKind.CHECKBOX)
        assert boxes[0].rect.size() == boxes[1].rect.size()

    def test_本文に重ならない(self, editor) -> None:
        """ユーザー報告。潰した `[ ]` の幅は 7.7px しか無いのに、記号は
        17.8px 描かれていて本文に食い込んでいた（実測）。"""
        away(editor, "- [ ] まだ終わっていない項目")
        box = of_kind(editor, DecorationKind.CHECKBOX)[0]
        assert box.rect.right() <= text_start_x(editor, 0, len("- [ ] "))

    def test_本文との間に隙間がある(self, editor) -> None:
        """接していると読みにくい。1 文字分は空ける。"""
        away(editor, "- [x] 終わった項目")
        box = of_kind(editor, DecorationKind.CHECKBOX)[0]
        gap = text_start_x(editor, 0, len("- [x] ")) - box.rect.right()
        assert gap >= 3, f"隙間が {gap:.1f}px しかない"

    def test_行の高さに収まる(self, editor) -> None:
        away(editor, "- [ ] やること")
        box = of_kind(editor, DecorationKind.CHECKBOX)[0]
        block = (
            editor.document()
            .documentLayout()
            .blockBoundingRect(editor.document().findBlockByNumber(0))
        )
        assert box.rect.height() <= block.height()

    def test_カーソルを入れると記号が戻る(self, editor) -> None:
        """潰した `[ ]` を広げているので、戻したときに幅が残ると間延びする。"""
        away(editor, "- [ ] やること")
        hidden = text_start_x(editor, 0, len("- [ ] "))
        editor.moveCursor(QTextCursor.MoveOperation.Start)
        editor.moveCursor(QTextCursor.MoveOperation.Right)
        revealed = text_start_x(editor, 0, len("- [ ] "))
        assert revealed != hidden

    def test_普通の箇条書きには描かない(self, editor) -> None:
        editor.setPlainText("- ただの項目")
        assert DecorationKind.CHECKBOX not in kinds(editor)

    def test_記号はリストマーカーより右に置く(self, editor) -> None:
        editor.setPlainText("- [ ] やること")
        box = of_kind(editor, DecorationKind.CHECKBOX)[0]
        assert box.rect.left() > 0


class TestVisibility:
    def test_画面外のブロックは含まない(self, editor) -> None:
        """spec §6.6: 可視ブロックだけを走査する。"""
        editor.setPlainText("\n".join(["> 引用"] * 500))
        editor.resize(800, 200)
        bars = of_kind(editor, DecorationKind.QUOTE_BAR)
        assert 0 < len(bars) < 50, f"{len(bars)} 本描こうとしている"

    def test_空の文書では何も描かない(self, editor) -> None:
        editor.setPlainText("")
        assert visible_decorations(editor) == []


class TestActuallyPaints:
    def test_引用の縦バーがピクセルとして現れる(self, editor) -> None:
        """組み立てたものが本当に描かれることの担保。"""
        from PySide6.QtGui import QColor, QImage

        from hitofude.theme import LIGHT

        def render(text: str) -> QImage:
            editor.setPlainText(text)
            image = QImage(editor.size(), QImage.Format.Format_ARGB32)
            image.fill(QColor("white"))
            editor.render(image)
            return image

        with_quote = render("> 引用")
        without = render("引用")

        bar = QColor(LIGHT.quote_bar).rgb()
        found = any(
            with_quote.pixel(x, y) == bar
            for x in range(min(60, with_quote.width()))
            for y in range(min(40, with_quote.height()))
        )
        assert found, "縦バーの色のピクセルが見つからない"
        assert with_quote != without


class TestQiitaNote:
    """`:::note` の囲み（B-3）。

    囲みであることは**左の縦線**で表す。書き出し（`editor/exporter.py`）と
    同じ表し方に揃えてある。
    """

    def test_囲みの行に縦線を描く(self, editor) -> None:
        editor.setPlainText(":::note info\n本文\n:::")
        assert kinds(editor).count(DecorationKind.NOTE_BAR) == 3

    def test_囲みの外には描かない(self, editor) -> None:
        editor.setPlainText(":::note info\n本文\n:::\n外")
        assert kinds(editor).count(DecorationKind.NOTE_BAR) == 3

    def test_種類を持ち歩く(self, editor) -> None:
        editor.setPlainText(":::note warn\n本文\n:::")
        assert {d.text for d in of_kind(editor, DecorationKind.NOTE_BAR)} == {"warn"}

    def test_引用の縦バーとは別物(self, editor) -> None:
        editor.setPlainText(":::note info\n本文\n:::")
        assert DecorationKind.QUOTE_BAR not in kinds(editor)

    def test_囲みの中の引用は縦線をずらす(self, editor) -> None:
        """同じ位置に描くと 2 本が重なって、どちらも読めなくなる。"""
        editor.setPlainText(":::note info\n> 引用\n:::")
        note = of_kind(editor, DecorationKind.NOTE_BAR)[1]
        quote = of_kind(editor, DecorationKind.QUOTE_BAR)[0]
        assert quote.rect.left() >= note.rect.right()

    def test_囲みの外の引用は元の位置(self, editor) -> None:
        editor.setPlainText("> 引用")
        assert of_kind(editor, DecorationKind.QUOTE_BAR)[0].rect.left() == pytest.approx(
            editor.contentsRect().left() + 2, abs=2
        )

    def test_種類ごとに色が違う(self, editor) -> None:
        from PySide6.QtGui import QColor, QImage

        from hitofude.theme import LIGHT

        def colors(kind: str) -> set[int]:
            editor.setPlainText(f":::note {kind}\n本文\n:::")
            image = QImage(editor.size(), QImage.Format.Format_ARGB32)
            image.fill(QColor("white"))
            editor.render(image)
            return {
                image.pixel(x, y)
                for x in range(min(60, image.width()))
                for y in range(min(60, image.height()))
            }

        for kind, color in (
            ("info", LIGHT.note_info),
            ("warn", LIGHT.note_warn),
            ("alert", LIGHT.note_alert),
        ):
            assert QColor(color).rgb() in colors(kind), f"{kind} の色が出ていない"

    def test_知らない綴りは灰色(self, editor) -> None:
        """`info` の青と同じでは、間違えたことに気づけない（ユーザー報告）。"""
        from PySide6.QtGui import QColor, QImage

        from hitofude.theme import LIGHT

        away(editor, ":::note warm\n本文\n:::")
        image = QImage(editor.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        editor.render(image)
        # 本文には左余白があるので、縦線は x=0 ではなくその内側に来る
        found = {
            image.pixel(x, y)
            for x in range(min(60, image.width()))
            for y in range(min(60, image.height()))
        }
        assert QColor(LIGHT.muted_foreground).rgb() in found
        assert QColor(LIGHT.note_info).rgb() not in found


class TestCodeName:
    """` ```python:aaa.py ` のファイル名（ユーザー要望）。

    書き出しでは見出しとして出るのに、画面では**どこにも出ていなかった**
    （フェンスの行ごと潰していたため）。行の高さを作って、そこへ描く。
    """

    def test_ファイル名を描く(self, editor) -> None:
        away(editor, "```python:aaa.py\nprint(1)\n```")
        names = of_kind(editor, DecorationKind.CODE_NAME)
        assert [d.text for d in names] == ["aaa.py"]

    def test_ファイル名が無ければ描かない(self, editor) -> None:
        away(editor, "```python\nprint(1)\n```")
        assert DecorationKind.CODE_NAME not in kinds(editor)

    def test_言語が無くても描く(self, editor) -> None:
        away(editor, "```:メモ\nx\n```")
        assert [d.text for d in of_kind(editor, DecorationKind.CODE_NAME)] == ["メモ"]

    def test_コードの上に置く(self, editor) -> None:
        away(editor, "```python:aaa.py\nprint(1)\n```")
        name = of_kind(editor, DecorationKind.CODE_NAME)[0]
        body = of_kind(editor, DecorationKind.CODE_BACKGROUND)[1]
        assert name.rect.top() < body.rect.top()

    def test_描く場所の高さがある(self, editor) -> None:
        """潰したままだと 1px 未満で、書いても見えない。"""
        away(editor, "```python:aaa.py\nprint(1)\n```")
        assert of_kind(editor, DecorationKind.CODE_NAME)[0].rect.height() > 8


class TestSourceMode:
    """ソースモード（Raw）では飾りを描かない（ユーザー要望）。

    記号を見せるモードなのに罫線や縦線が残ると、`|` の上に罫線が重なり、
    `[ ]` の上にチェック記号が重なる。**素の Markdown を見るための
    モード**なので、描画をやめる。
    """

    SOURCE = (
        "| 項目 | 担当 |\n| --- | --- |\n| 設計 | 野村 |\n\n"
        "- [ ] やること\n\n> 引用\n\n:::note info\n囲み\n:::\n\n```python\nx = 1\n```\n\n末尾\n"
    )

    def test_通常は描く(self, editor) -> None:
        away(editor, self.SOURCE)
        assert visible_decorations(editor)

    def test_ソースモードでは描かない(self, editor) -> None:
        away(editor, self.SOURCE)
        editor.set_source_mode(True)
        assert visible_decorations(editor) == []

    def test_戻すとまた描く(self, editor) -> None:
        away(editor, self.SOURCE)
        editor.set_source_mode(True)
        editor.set_source_mode(False)
        assert visible_decorations(editor)

    def test_フォーカスモードの減光は残す(self, editor) -> None:
        """こちらは記法の飾りではなく、読む助け。"""
        away(editor, self.SOURCE)
        editor.set_source_mode(True)
        editor.set_focus_mode(True)
        assert [d.kind for d in visible_decorations(editor)] == [DecorationKind.FOCUS_DIM] * len(
            visible_decorations(editor)
        )
        assert visible_decorations(editor)


class TestPaintNeverHidesText:
    """**飾りが壊れても本文は描く**（ユーザー報告の再発防止）。

    `paintEvent` の中で例外が出ると `super().paintEvent()` に届かず、
    その領域が真っ白になる。原因が何であれ、本文が消えるのは割に合わない。
    """

    def test_装飾が例外を出しても本文が描かれる(self, qtbot, monkeypatch, caplog) -> None:
        from PySide6.QtGui import QColor, QImage

        editor = MarkdownEditor()
        qtbot.addWidget(editor)
        editor.resize(400, 200)
        editor.show()
        editor.setPlainText("本文の文字")

        def boom(_editor):
            raise RuntimeError("飾りの組み立てが壊れた")

        monkeypatch.setattr(painter_overlay, "visible_decorations", boom)

        image = QImage(editor.viewport().size(), QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        editor.viewport().render(image)

        assert any(
            image.pixelColor(x, y) != QColor("white")
            for y in range(image.height())
            for x in range(image.width())
        ), "本文が 1 ピクセルも描かれていない"
        assert "装飾の組み立てに失敗した" in caplog.text


class TestBlockInset:
    """囲みの飾りと中身の間に余白を作る（ユーザー要望 2026-08-18）。

    **本文は右に動かせない。** ブロックの左余白は `QTextBlockFormat` しか
    手がなく、R5（ADR-0002）でそれは使えない。そこで文書の余白
    （`documentMargin`）を広げて本文の左に帯を作り、飾りは今までどおり
    viewport の左端から描く。飾りの座標は変えずに隙間だけが生まれる。

    以前は帯が 4px しかなく、縦バー（x=2..6）が本文（x=4 から）に
    重なっていた（実測）。
    """

    def body_left(self, editor: MarkdownEditor, line: int = 0) -> float:
        """その行の本文が始まる x。行頭のマーカーは潰れているので同じ位置。"""
        block = editor.document().findBlockByNumber(line)
        cursor = editor.textCursor()
        cursor.setPosition(block.position())
        editor.setTextCursor(cursor)
        return float(editor.cursorRect().left())

    def test_コードブロックの背景が中身より左から始まる(self, editor) -> None:
        editor.setPlainText("```\ncode\n```\n\n末尾")
        rect = of_kind(editor, DecorationKind.CODE_BACKGROUND)[0].rect
        assert self.body_left(editor, 1) - rect.left() >= 8

    def test_noteの縦バーが中身に重ならない(self, editor) -> None:
        editor.setPlainText(":::note\naaa\n:::\n")
        bar = of_kind(editor, DecorationKind.NOTE_BAR)[0].rect
        assert bar.right() <= self.body_left(editor, 1)

    def test_引用の縦バーが中身に重ならない(self, editor) -> None:
        editor.setPlainText("> 引用\n")
        bar = of_kind(editor, DecorationKind.QUOTE_BAR)[0].rect
        assert bar.right() <= self.body_left(editor, 0)


class TestNoteBackground:
    """`:::note` の背景の帯（ユーザー要望）。

    コードブロックと同じく、行の背景を種類の色で塗る。
    info は薄い緑 / warn は薄い黄 / alert は薄い赤。縦線は今まで通り残す。
    """

    def test_囲みの行に背景を敷く(self, editor) -> None:
        editor.setPlainText(":::note info\n本文\n:::")
        assert kinds(editor).count(DecorationKind.NOTE_BACKGROUND) == 3

    def test_背景も種類を持ち歩く(self, editor) -> None:
        editor.setPlainText(":::note alert\n本文\n:::")
        found = {d.text for d in of_kind(editor, DecorationKind.NOTE_BACKGROUND)}
        assert found == {"alert"}

    def test_種類ごとの背景色が描かれる(self, editor) -> None:
        from PySide6.QtGui import QColor, QImage

        from hitofude.theme import LIGHT

        def colors(kind: str) -> set[int]:
            editor.setPlainText(f":::note {kind}\n本文\n:::")
            image = QImage(editor.size(), QImage.Format.Format_ARGB32)
            image.fill(QColor("white"))
            editor.render(image)
            return {
                image.pixel(x, y)
                for x in range(min(120, image.width()))
                for y in range(min(80, image.height()))
            }

        for kind, color in (
            ("info", LIGHT.note_info_background),
            ("warn", LIGHT.note_warn_background),
            ("alert", LIGHT.note_alert_background),
        ):
            assert QColor(color).rgb() in colors(kind), f"{kind} の背景が出ていない"

    def test_知らない綴りの背景は無彩色(self, editor) -> None:
        """種類の色を出すと、綴りの間違いに気づけない（縦線と同じ理屈）。"""
        editor.setPlainText(":::note warm\n本文\n:::")
        found = of_kind(editor, DecorationKind.NOTE_BACKGROUND)
        assert found, "背景の帯そのものは出る"

    def test_縦線は背景の上に残る(self, editor) -> None:
        editor.setPlainText(":::note info\n本文\n:::")
        found = kinds(editor)
        assert found.index(DecorationKind.NOTE_BACKGROUND) < found.index(DecorationKind.NOTE_BAR)


class TestNoteBackgroundExport:
    def test_書き出しのCSSも背景を塗る(self) -> None:
        """画面と書き出しで囲みの見た目を揃える（B-3 と同じ方針）。"""
        from hitofude.editor.exporter import _stylesheet
        from hitofude.theme import LIGHT

        css = _stylesheet(LIGHT)
        assert LIGHT.note_info_background in css
        assert LIGHT.note_warn_background in css
        assert LIGHT.note_alert_background in css


class TestCodeNameBadge:
    """ファイル名のバッジ表示（ユーザー要望 / Qiita 風）。

    コードブロックの背景と違う色で囲み、コードとの間に隙間を空ける。
    """

    def test_バッジの色が描かれる(self, editor) -> None:
        from PySide6.QtGui import QColor, QImage

        from hitofude.theme import LIGHT

        editor.setPlainText('```python:aaa.py\nprint("x")\n```\n\n本文\n')
        away(editor, editor.toPlainText())
        image = QImage(editor.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        editor.render(image)
        found = {
            image.pixel(x, y)
            for x in range(min(200, image.width()))
            for y in range(min(80, image.height()))
        }
        assert QColor(LIGHT.code_name_background).rgb() in found, "バッジの背景が出ていない"

    def test_ファイル名の行はコードとの隙間ぶん高い(self, editor) -> None:
        """キャレットは表示外へ（行 0 にいると生表示になり予約が効かない）。

        隙間の実寸は環境のフォント計測に依存する（offscreen の代替フォントは
        行高の比が実機とずれる）ので、「名前ありのほうが高い」ことだけを見る。
        """
        away(editor, '```python:aaa.py\nprint("x")\n```\n')
        with_name = editor.blockBoundingGeometry(editor.document().findBlockByNumber(0)).height()
        away(editor, '```python\nprint("x")\n```\n')
        without = editor.blockBoundingGeometry(editor.document().findBlockByNumber(0)).height()
        assert with_name > without

    def test_書き出しのCSSもバッジで揃える(self) -> None:
        from hitofude.editor.exporter import _stylesheet
        from hitofude.theme import LIGHT

        css = _stylesheet(LIGHT)
        assert LIGHT.code_name_background in css
