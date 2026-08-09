"""シンタックスハイライタのテスト（タスク 2-2〜2-4, 2-7 / spec §6.3, §6.4）。

ウィジェットは要らない。`QTextDocument` に直接ハイライタを付けて、
`block.layout().formats()` に載った書式を検査する。
"""

import pytest
from PySide6.QtGui import QTextCharFormat, QTextDocument

from hitofude.core.models import BlockType
from hitofude.editor.highlighter import HIDDEN_POINT_SIZE, MarkdownHighlighter

pytestmark = pytest.mark.gui

BASE_POINT_SIZE = 15.0


@pytest.fixture
def document(qapp) -> QTextDocument:
    return QTextDocument()


@pytest.fixture
def highlighter(document: QTextDocument) -> MarkdownHighlighter:
    return MarkdownHighlighter(document, base_point_size=BASE_POINT_SIZE)


def set_text(document: QTextDocument, text: str) -> None:
    """本文を差し替え、レイアウトまで済ませる。

    **ハイライタはブロックがレイアウトされる過程で走る。** ウィジェットに
    載せていない素の `QTextDocument` は自動でレイアウトされないため、
    `setPlainText()` だけでは `highlightBlock()` が呼ばれず、書式も
    `userData` も更新されない。実アプリでは QPlainTextEdit がこれを行う
    （QPlainTextEdit に載せた場合は正しく走ることを確認済み）。
    """
    document.setPlainText(text)
    document.documentLayout().documentSize()


def char_format(document: QTextDocument, line: int, column: int) -> QTextCharFormat:
    """指定位置に最終的に載っている書式を合成して返す。"""
    block = document.findBlockByNumber(line)
    merged = QTextCharFormat()
    for entry in block.layout().formats():
        if entry.start <= column < entry.start + entry.length:
            merged.merge(entry.format)
    return merged


def is_hidden(document: QTextDocument, line: int, column: int) -> bool:
    return char_format(document, line, column).fontPointSize() == pytest.approx(HIDDEN_POINT_SIZE)


def block_data(document: QTextDocument, line: int):
    return document.findBlockByNumber(line).userData()


class TestInlineFormats:
    def test_強調の中身が太字になる(self, document, highlighter) -> None:
        set_text(document, "これは**強調**です")
        assert char_format(document, 0, 5).fontWeight() > QTextCharFormat().fontWeight()

    def test_斜体の中身が斜体になる(self, document, highlighter) -> None:
        set_text(document, "これは*斜体*です")
        assert char_format(document, 0, 4).fontItalic() is True

    def test_取り消し線(self, document, highlighter) -> None:
        set_text(document, "~~削除~~")
        assert char_format(document, 0, 2).fontStrikeOut() is True

    def test_インラインコードに背景がつく(self, document, highlighter) -> None:
        from hitofude.theme import LIGHT

        set_text(document, "`code`")
        # 未設定のブラシも「黒・不透明」を返すので、alpha ではなく実際の色で比べる
        assert (
            char_format(document, 0, 1).background().color().name() == LIGHT.code_background.lower()
        )

    def test_ハイライトに背景がつく(self, document, highlighter) -> None:
        from hitofude.theme import LIGHT

        set_text(document, "::目立つ::")
        got = char_format(document, 0, 2).background().color().name()
        assert got == LIGHT.highlight_background.lower()

    def test_装飾のない文字には背景を付けない(self, document, highlighter) -> None:
        from PySide6.QtCore import Qt

        set_text(document, "ただの文章")
        assert char_format(document, 0, 2).background().style() == Qt.BrushStyle.NoBrush

    def test_入れ子は外側の書式を保つ(self, document, highlighter) -> None:
        """`**bold *em* here**` の内側は太字かつ斜体。"""
        set_text(document, "**bold *em* here**")
        inner = char_format(document, 0, 8)
        assert inner.fontItalic() is True
        assert inner.fontWeight() > QTextCharFormat().fontWeight()


class TestMarkerHiding:
    """R4 / spec §3.3: 文字は消さずフォントサイズだけ 0.5pt に潰す。"""

    def test_強調のマーカーが潰れる(self, document, highlighter) -> None:
        set_text(document, "これは**強調**です")
        assert is_hidden(document, 0, 3)  # 開き '**'
        assert is_hidden(document, 0, 8)  # 閉じ '**'

    def test_中身は潰れない(self, document, highlighter) -> None:
        set_text(document, "これは**強調**です")
        assert not is_hidden(document, 0, 5)

    def test_文字数は変わらない(self, document, highlighter) -> None:
        """位置マッピングを不要にするための最重要の性質（R4）。"""
        source = "これは**強調**です"
        set_text(document, source)
        assert document.toPlainText() == source

    def test_見出しマーカーが潰れる(self, document, highlighter) -> None:
        set_text(document, "## 見出し")
        assert is_hidden(document, 0, 0)
        assert is_hidden(document, 0, 1)
        assert not is_hidden(document, 0, 3)

    def test_引用マーカーが潰れる(self, document, highlighter) -> None:
        set_text(document, "> 引用")
        assert is_hidden(document, 0, 0)
        assert not is_hidden(document, 0, 2)

    def test_リストマーカーは潰さない(self, document, highlighter) -> None:
        """spec §6.4: 記号自体が意味を持つ表示要素なので隠さない。"""
        set_text(document, "- 項目")
        assert not is_hidden(document, 0, 0)

    def test_タグは記号ごと表示する(self, document, highlighter) -> None:
        set_text(document, "#work")
        assert not is_hidden(document, 0, 0)

    def test_リンクのURL部分が潰れる(self, document, highlighter) -> None:
        set_text(document, "[Qt](https://q.io)")
        assert is_hidden(document, 0, 0)  # '['
        assert not is_hidden(document, 0, 1)  # 'Q'
        assert is_hidden(document, 0, 3)  # ']'
        assert is_hidden(document, 0, 10)  # URL の中


class TestHeading:
    @pytest.mark.parametrize(("level", "expected"), [(1, 1.8), (2, 1.5), (3, 1.25)])
    def test_レベルごとに文字が大きくなる(self, document, highlighter, level, expected) -> None:
        set_text(document, "#" * level + " 見出し")
        size = char_format(document, 0, level + 1).fontPointSize()
        assert size == pytest.approx(BASE_POINT_SIZE * expected)

    def test_見出しは太字(self, document, highlighter) -> None:
        set_text(document, "# 見出し")
        assert char_format(document, 0, 2).fontWeight() > QTextCharFormat().fontWeight()


class TestBlockState:
    """行をまたぐ状態の引き継ぎ（§6.3）。"""

    def test_コードフェンスの中では装飾しない(self, document, highlighter) -> None:
        set_text(document, "```python\n**強調ではない**\n```")
        assert not is_hidden(document, 1, 0)
        assert char_format(document, 1, 3).fontWeight() == QTextCharFormat().fontWeight()

    def test_フェンス内の行はCODE_FENCE_BODYとして記録される(self, document, highlighter) -> None:
        set_text(document, "```\n# 見出しではない\n```")
        assert block_data(document, 1).info.type is BlockType.CODE_FENCE_BODY

    def test_フェンスを抜けたら装飾が戻る(self, document, highlighter) -> None:
        set_text(document, "```\nx\n```\n**強調**")
        assert is_hidden(document, 3, 0)

    def test_front_matterを記録する(self, document, highlighter) -> None:
        set_text(document, "---\nid: 1\n---\n本文")
        assert block_data(document, 1).info.type is BlockType.FRONT_MATTER
        assert block_data(document, 3).info.type is BlockType.PARAGRAPH


class TestBlockData:
    """spec §6.2: `paintEvent` や block_decorator はここから読む。"""

    def test_ブロック情報が格納される(self, document, highlighter) -> None:
        set_text(document, "## 見出し")
        data = block_data(document, 0)
        assert data.info.type is BlockType.HEADING
        assert data.info.level == 2
        assert data.info.marker_len == 3

    def test_インラインスパンも格納される(self, document, highlighter) -> None:
        set_text(document, "**強調**")
        assert len(block_data(document, 0).spans) == 1

    def test_コード行にはスパンを入れない(self, document, highlighter) -> None:
        set_text(document, "```\n**強調ではない**\n```")
        assert block_data(document, 1).spans == []


class TestReveal:
    """spec §6.4 のリビール条件表。"""

    def _reveal(self, document, highlighter, position: int) -> None:
        highlighter.set_reveal(position)
        highlighter.rehighlight()
        document.documentLayout().documentSize()

    def test_キャレットがスパン内にあるとマーカーが現れる(self, document, highlighter) -> None:
        set_text(document, "これは**強調**です")
        assert is_hidden(document, 0, 3)
        self._reveal(document, highlighter, 5)
        assert not is_hidden(document, 0, 3)

    def test_閉じマーカーの直後でも現れる(self, document, highlighter) -> None:
        """閉区間で判定する。ここが開区間だと打ち直しができない。

        `これは**強調**です` の閉じ `**` は 7..9。位置 9 は「閉じマーカーの直後」。
        """
        set_text(document, "これは**強調**です")
        self._reveal(document, highlighter, 9)
        assert not is_hidden(document, 0, 3)

    def test_スパンの外なら隠れたまま(self, document, highlighter) -> None:
        set_text(document, "これは**強調**です")
        self._reveal(document, highlighter, 0)
        assert is_hidden(document, 0, 3)

    def test_見出しはブロック内のどこでも現れる(self, document, highlighter) -> None:
        """インラインと違い、ブロックマーカーはブロック内なら現す（§6.4）。"""
        set_text(document, "## 見出し")
        self._reveal(document, highlighter, 6)
        assert not is_hidden(document, 0, 0)

    def test_別のブロックにキャレットがあると隠れたまま(self, document, highlighter) -> None:
        set_text(document, "## 見出し\n本文")
        self._reveal(document, highlighter, 8)
        assert is_hidden(document, 0, 0)

    def test_ソースモードでは常に全表示(self, document, highlighter) -> None:
        set_text(document, "## 見出し\n**強調**")
        highlighter.set_source_mode(True)
        highlighter.rehighlight()
        document.documentLayout().documentSize()
        assert not is_hidden(document, 0, 0)
        assert not is_hidden(document, 1, 0)

    def test_選択範囲に交差するブロックは全表示(self, document, highlighter) -> None:
        """選択してコピーする直前に、何をコピーするか見えるようにする（§6.4）。"""
        set_text(document, "**強調**\n別の行")
        highlighter.set_reveal(None, selection=(0, 3))
        highlighter.rehighlight()
        document.documentLayout().documentSize()
        assert not is_hidden(document, 0, 0)

    def test_選択範囲の外のブロックは隠れたまま(self, document, highlighter) -> None:
        set_text(document, "別の行\n**強調**")
        highlighter.set_reveal(None, selection=(0, 2))
        highlighter.rehighlight()
        document.documentLayout().documentSize()
        assert is_hidden(document, 1, 0)


class TestTheme:
    def test_テーマ変更で色が変わる(self, document, highlighter) -> None:
        from hitofude.theme import DARK, LIGHT

        set_text(document, "`code`")
        light = char_format(document, 0, 1).background().color().name()
        highlighter.set_theme(DARK)
        document.documentLayout().documentSize()
        dark = char_format(document, 0, 1).background().color().name()
        assert light != dark
        assert light == LIGHT.code_background.lower()
        assert dark == DARK.code_background.lower()


class TestWithWidget:
    """実アプリの経路の確認。

    上のテストは素の `QTextDocument` を使うため明示的なレイアウトが要る。
    ここでは `QPlainTextEdit` に載せ、**何も足さずに**装飾が効くことを見る。
    テストヘルパの都合が本番の挙動を隠していないことの担保。
    """

    def test_ウィジェットに載せれば自動で装飾される(self, qtbot) -> None:
        from PySide6.QtWidgets import QPlainTextEdit

        edit = QPlainTextEdit()
        qtbot.addWidget(edit)
        edit._highlighter = MarkdownHighlighter(edit.document(), base_point_size=BASE_POINT_SIZE)

        edit.setPlainText("これは**強調**です\n## 見出し")

        assert is_hidden(edit.document(), 0, 3)
        assert not is_hidden(edit.document(), 0, 5)
        assert is_hidden(edit.document(), 1, 0)
        assert block_data(edit.document(), 1).info.type is BlockType.HEADING


class TestMonoFallback:
    """`SF Mono` は macOS がアプリに公開しておらず解決されない（回帰テスト）。

    実在しないフォントを指定すると Qt が警告を出し、行の高さがばらつく。
    """

    def test_実在するフォントへ落ちる(self) -> None:
        from hitofude.editor.highlighter import mono_families

        families = mono_families("SF Mono")
        assert families[0] == "SF Mono"
        assert "Menlo" in families

    def test_既定は実在するフォント(self, qapp) -> None:
        from PySide6.QtGui import QFontDatabase

        from hitofude.editor.highlighter import DEFAULT_MONO_FAMILY

        assert DEFAULT_MONO_FAMILY in set(QFontDatabase.families())

    def test_コードに複数の候補が入る(self, document, highlighter) -> None:
        set_text(document, "`code`")
        families = char_format(document, 0, 1).fontFamilies()
        assert len(families) > 1, "フォールバックが入っていない"

    def test_表は日本語も等幅のフォントを使う(self, document, highlighter) -> None:
        """通常の等幅フォントは CJK グリフを持たず、フォールバック先の全角幅が
        半角のちょうど 2 倍にならないため桁がずれる（実測: Menlo は 1.66 倍）。
        """
        from hitofude.editor.highlighter import TABLE_FAMILIES

        set_text(document, "| A | B |\n|---|---|\n| 1 | 2 |")
        families = char_format(document, 0, 2).fontFamilies()
        assert families[0] == TABLE_FAMILIES[0]

    def test_表のフォントは全角が半角のちょうど2倍(self, qapp) -> None:
        from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF

        from hitofude.editor.highlighter import TABLE_FAMILIES

        family = TABLE_FAMILIES[0]
        if family not in set(QFontDatabase.families()):
            pytest.skip(f"{family} が無い環境")

        font = QFont(family)
        font.setPointSizeF(15.0)
        metrics = QFontMetricsF(font)
        half = metrics.horizontalAdvance("A")
        assert metrics.horizontalAdvance("あ") == pytest.approx(half * 2, abs=0.5)


class TestUnknownNoteKind:
    """`:::note warm` のような綴り違い（ユーザー報告）。

    **区切り行を隠さない。** 隠すと、灰色の縦線が出るだけで「何を間違えたか」
    が画面から消える。打った文字が見えていれば自分で直せる。
    """

    def test_知らない綴りの行は隠さない(self, document, highlighter) -> None:
        set_text(document, ":::note warm\n本文\n:::\n\n末尾")
        assert not is_hidden(document, 0, 0)

    def test_閉じの行も隠さない(self, document, highlighter) -> None:
        """開きだけ見えて閉じが消えると、囲みが壊れているのか正常なのか
        分からない。まとめて見せる。"""
        set_text(document, ":::note warm\n本文\n:::\n\n末尾")
        assert not is_hidden(document, 2, 0)

    @pytest.mark.parametrize("kind", ["info", "warn", "alert"])
    def test_正しい綴りなら今まで通り隠す(self, document, highlighter, kind: str) -> None:
        set_text(document, f":::note {kind}\n本文\n:::\n\n末尾")
        assert is_hidden(document, 0, 0)
        assert is_hidden(document, 2, 0)

    def test_種類の省略も隠す(self, document, highlighter) -> None:
        set_text(document, ":::note\n本文\n:::\n\n末尾")
        assert is_hidden(document, 0, 0)


class TestMathBlock:
    """複数行の `$$` ブロック（B-5）。コードブロックと同じ見せ方に揃える。"""

    def test_中身は等幅になる(self, document, highlighter) -> None:
        set_text(document, "$$\nx = 1\n$$\n\n末尾")
        assert char_format(document, 1, 0).fontFamilies()

    def test_中では装飾が効かない(self, document, highlighter) -> None:
        """数式の `_` や `*` は装飾ではない。"""
        set_text(document, "$$\na_1 *b*\n$$\n\n末尾")
        assert not block_data(document, 1).spans

    def test_区切りの行は潰す(self, document, highlighter) -> None:
        set_text(document, "$$\nx = 1\n$$\n\n末尾")
        assert is_hidden(document, 0, 0)
        assert is_hidden(document, 2, 0)


class TestCodeColors:
    """コードブロックの色分け（B-6）。

    書き出し（`tests/core/test_html.py`）と画面で**同じ配色**を使う。
    どちらが本当か分からなくならないように。
    """

    def color_at(self, document, line: int, column: int) -> str:
        return char_format(document, line, column).foreground().color().name()

    def test_予約語に色が付く(self, document, highlighter) -> None:
        set_text(document, "```python\ndef f():\n    pass\n```\n\n末尾")
        assert self.color_at(document, 1, 0) != self.color_at(document, 1, 4)

    def test_言語が無ければ色を付けない(self, document, highlighter) -> None:
        set_text(document, "```\ndef f():\n    pass\n```\n\n末尾")
        assert self.color_at(document, 1, 0) == self.color_at(document, 1, 4)

    def test_知らない言語は色を付けない(self, document, highlighter) -> None:
        set_text(document, "```そんな言語\ndef f():\n```\n\n末尾")
        assert self.color_at(document, 1, 0) == self.color_at(document, 1, 4)

    def test_ファイル名付きでも色が付く(self, document, highlighter) -> None:
        set_text(document, "```python:main.py\ndef f():\n    pass\n```\n\n末尾")
        assert self.color_at(document, 1, 0) != self.color_at(document, 1, 4)

    def test_複数行の文字列の中は予約語にしない(self, document, highlighter) -> None:
        """**行単位で解析していたら間違える場所。**"""
        set_text(document, '```python\nx = """\ndef f():\n"""\n```\n\n末尾')
        keyword = None
        set_text(document, "```python\ndef f():\n```\n\n末尾")
        keyword = self.color_at(document, 1, 0)
        set_text(document, '```python\nx = """\ndef f():\n"""\n```\n\n末尾')
        assert self.color_at(document, 2, 0) != keyword

    def test_コードの外には効かない(self, document, highlighter) -> None:
        set_text(document, "```python\ndef f():\n```\n\ndef 段落\n\n末尾")
        assert self.color_at(document, 4, 0) == self.color_at(document, 4, 4)

    def test_長すぎるブロックは色を付けない(self, document, highlighter) -> None:
        """打鍵のたびに解析し直すので、長いと重くなる（§6.6）。"""
        from hitofude.editor.highlighter import MAX_HIGHLIGHT_LINES

        body = "\n".join(["def f(): pass"] * (MAX_HIGHLIGHT_LINES + 5))
        set_text(document, f"```python\n{body}\n```\n\n末尾")
        assert self.color_at(document, 1, 0) == self.color_at(document, 1, 4)
