"""エディタウィジェットのテスト（タスク 2-5, 2-6 / spec §5.1, §6.4, §6.6）。"""

import pytest
from PySide6.QtGui import QTextCursor

from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.editor.highlighter import HIDDEN_POINT_SIZE

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot) -> MarkdownEditor:
    widget = MarkdownEditor()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def is_hidden(editor: MarkdownEditor, line: int, column: int) -> bool:
    block = editor.document().findBlockByNumber(line)
    for entry in block.layout().formats():
        covers = entry.start <= column < entry.start + entry.length
        if covers and entry.format.fontPointSize() == pytest.approx(HIDDEN_POINT_SIZE):
            return True
    return False


def move_to(editor: MarkdownEditor, position: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(position)
    editor.setTextCursor(cursor)


class TestConstruction:
    def test_ハイライタが付いている(self, editor) -> None:
        assert editor.highlighter.document() is editor.document()

    def test_折り返しは単語単位(self, editor) -> None:
        from PySide6.QtWidgets import QPlainTextEdit

        assert editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth


class TestSourceOfTruth:
    """R1 / spec §3.1: `toPlainText()` がそのまま保存内容。"""

    def test_打った文字がそのまま残る(self, editor, qtbot) -> None:
        source = "# 見出し\n\nこれは**強調**です #tag"
        editor.setPlainText(source)
        assert editor.toPlainText() == source

    def test_装飾されてもマーカーは消えない(self, editor, qtbot) -> None:
        qtbot.keyClicks(editor, "**bold**")
        assert editor.toPlainText() == "**bold**"


class TestReveal:
    def test_キャレットを入れるとマーカーが現れる(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        move_to(editor, 0)
        assert is_hidden(editor, 0, 3)
        move_to(editor, 5)
        assert not is_hidden(editor, 0, 3)

    def test_離れると再び隠れる(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        move_to(editor, 5)
        assert not is_hidden(editor, 0, 3)
        move_to(editor, 0)
        assert is_hidden(editor, 0, 3)

    def test_前のブロックのマーカーが隠れ直す(self, editor) -> None:
        editor.setPlainText("## 見出し\n本文")
        move_to(editor, 2)
        assert not is_hidden(editor, 0, 0)
        move_to(editor, 8)  # 次のブロックへ
        assert is_hidden(editor, 0, 0)

    def test_選択したブロックは全表示になる(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        move_to(editor, 0)
        assert is_hidden(editor, 0, 3)
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        assert not is_hidden(editor, 0, 3)

    def test_複数ブロックの選択は全ての行を現す(self, editor) -> None:
        editor.setPlainText("**一行目**\n**二行目**\n**三行目**")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        for line in range(3):
            assert not is_hidden(editor, line, 0), f"{line} 行目が隠れたまま"

    def test_ソースモードで全表示(self, editor) -> None:
        editor.setPlainText("## 見出し\n**強調**")
        move_to(editor, 0)
        editor.set_source_mode(True)
        assert not is_hidden(editor, 0, 0)
        assert not is_hidden(editor, 1, 0)
        editor.set_source_mode(False)
        assert is_hidden(editor, 1, 0)


class TestRehighlightScope:
    """R7 / spec §6.6: カーソル移動では旧/新の 2 ブロックだけを掛け直す。"""

    def test_カーソル移動で全体再ハイライトしない(self, editor, monkeypatch) -> None:
        editor.setPlainText("\n".join(f"**行{i}**" for i in range(200)))
        calls: list[int] = []
        monkeypatch.setattr(
            editor.highlighter,
            "rehighlightBlock",
            lambda block: calls.append(block.blockNumber()),
        )
        move_to(editor, 0)
        calls.clear()
        move_to(editor, editor.document().findBlockByNumber(100).position() + 3)
        assert len(calls) <= 2, f"{len(calls)} ブロックを掛け直している"

    def test_同じブロック内の移動は1ブロックだけ(self, editor, monkeypatch) -> None:
        editor.setPlainText("これは**強調**です\n別の行")
        move_to(editor, 0)
        calls: list[int] = []
        monkeypatch.setattr(
            editor.highlighter,
            "rehighlightBlock",
            lambda block: calls.append(block.blockNumber()),
        )
        move_to(editor, 5)
        assert calls == [0]

    def test_選択を伸ばしたときは差分だけ掛け直す(self, editor, monkeypatch) -> None:
        """ドラッグ中は selectionChanged のたびに呼ばれる。選択全体を
        毎回掛け直すと大選択で実質の全体再ハイライトになる（回帰）。
        旧選択にも新選択にも入っているブロックは既に全表示で変わらない。
        """
        from PySide6.QtGui import QTextCursor

        editor.setPlainText("\n".join(f"**行{i}**" for i in range(200)))
        document = editor.document()
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(
            document.findBlockByNumber(99).position() + 2, QTextCursor.MoveMode.KeepAnchor
        )
        editor.setTextCursor(cursor)

        calls: list[int] = []
        monkeypatch.setattr(
            editor.highlighter,
            "rehighlightBlock",
            lambda block: calls.append(block.blockNumber()),
        )
        cursor.setPosition(
            document.findBlockByNumber(100).position() + 2, QTextCursor.MoveMode.KeepAnchor
        )
        editor.setTextCursor(cursor)
        assert len(calls) <= 4, f"{len(calls)} ブロックを掛け直している"

    def test_選択を解除すると隠し直す(self, editor) -> None:
        """差分化しても「選択が外れた側を隠し直す」が壊れないこと。"""
        from PySide6.QtGui import QTextCursor

        editor.setPlainText("**あ**\n**い**\n**う**")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        assert not is_hidden(editor, 1, 0)  # 選択中は全表示

        cursor.setPosition(0)
        editor.setTextCursor(cursor)
        assert is_hidden(editor, 1, 0)  # 選択が外れたら隠し直す
        assert is_hidden(editor, 2, 0)


class TestNoPollution:
    """R5 の前提: リビールは編集ではない。"""

    def test_カーソル移動でmodifiedにならない(self, editor) -> None:
        editor.setPlainText("これは**強調**です")
        editor.document().setModified(False)
        move_to(editor, 5)
        move_to(editor, 0)
        assert editor.document().isModified() is False

    def test_カーソル移動でUndoスタックが汚れない(self, editor, qtbot) -> None:
        """`Cmd+Z` 1 回で直前の入力が戻ること（Phase 2 の完了条件）。"""
        qtbot.keyClicks(editor, "**bold**")
        move_to(editor, 3)
        move_to(editor, 0)
        move_to(editor, 8)
        editor.undo()
        assert editor.toPlainText() == ""


class TestLayout:
    """spec §5.1: 中央寄せ・最大幅 720px。"""

    def test_広いときは左右に余白が付く(self, editor) -> None:
        editor.resize(1200, 400)
        margins = editor.viewportMargins()
        assert margins.left() > 0
        assert margins.left() == margins.right()

    def test_狭いときは余白なし(self, editor) -> None:
        editor.resize(500, 400)
        assert editor.content_margin() == 0

    def test_本文幅は上限を超えない(self, editor) -> None:
        editor.resize(1600, 400)
        margins = editor.viewportMargins()
        content = 1600 - margins.left() - margins.right()
        assert content <= MarkdownEditor.MAX_CONTENT_WIDTH + 1


class TestTheme:
    def test_テーマ変更が反映される(self, editor) -> None:
        from hitofude.theme import DARK

        editor.setPlainText("`code`")
        editor.set_theme(DARK)
        assert editor.palette().base().color().name() == DARK.background.lower()


class TestTabWidth:
    """タブ幅（ユーザー要望）。

    Qt の既定は 80px 固定で、本文フォントだと 12 文字ぶんもあった（実測）。
    """

    def advance(self, editor, text: str) -> float:
        """**等幅フォント**での幅。タブが効くのはコードブロックの中。"""
        from PySide6.QtGui import QFont, QFontMetricsF

        font = QFont(editor.highlighter.mono_family)
        font.setPointSizeF(editor.font().pointSizeF())
        return QFontMetricsF(font).horizontalAdvance(text)

    def test_既定は4文字ぶん(self, editor) -> None:
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, "    "), abs=1)

    def test_変えられる(self, editor) -> None:
        editor.set_tab_width(2)
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, "  "), abs=1)

    def test_文字サイズを変えると追従する(self, editor) -> None:
        """px 固定で覚えると、大きい文字にしたときタブだけ狭くなる。"""
        before = editor.tabStopDistance()
        editor.set_base_point_size(30.0)
        assert editor.tabStopDistance() > before

    def test_等幅フォントを変えると追従する(self, editor) -> None:
        editor.set_tab_width(4)
        before = editor.tabStopDistance()
        editor.set_mono_family("Courier")
        # **等幅フォントの字幅に一致すること**が要件。値が変わるかは環境依存
        # （Menlo と Courier は空白幅が同じことがある。実際に踏んだ）
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, "    "), abs=1)
        assert before > 0

    def test_コードブロックの中でちょうど4文字ぶん(self, editor) -> None:
        """**ユーザー報告の回帰。** 本文フォント（Hiragino）の空白幅で
        計算していたので、等幅（Menlo）のコードブロックでは 2.2 文字ぶんに
        しか見えなかった（実測: Hiragino の空白 6.66px、Menlo は 12.03px）。"""
        editor.set_tab_width(4)
        assert editor.tabStopDistance() == pytest.approx(self.advance(editor, "    "), abs=1)

    def test_今の幅を答える(self, editor) -> None:
        editor.set_tab_width(3)
        assert editor.tab_width() == 3


class TestContentWidth:
    """本文の横幅の設定変更（I-3 / ADR-0018）。0 は「窓幅いっぱい」。"""

    def test_広めにすると本文が広がる(self, editor) -> None:
        editor.resize(1600, 400)
        editor.set_content_width(880)
        margins = editor.viewportMargins()
        content = 1600 - margins.left() - margins.right()
        assert 850 <= content <= 881

    def test_最大にすると余白が消える(self, editor) -> None:
        editor.resize(1600, 400)
        editor.set_content_width(0)
        assert editor.content_margin() == 0

    def test_標準に戻せる(self, editor) -> None:
        editor.resize(1600, 400)
        editor.set_content_width(0)
        editor.set_content_width(720)
        margins = editor.viewportMargins()
        content = 1600 - margins.left() - margins.right()
        assert content <= 721

    def test_表の幅が連動する(self, editor) -> None:
        """本文の幅を広げると、表に使える幅（px）も広がる（ADR-0029）。"""
        editor.resize(1600, 400)
        editor.show()
        before = editor._table_width
        editor.set_content_width(880)
        assert editor._table_width > before

    def test_画像の最大幅が連動する(self, editor) -> None:
        editor.resize(1600, 400)
        before = editor.image_width()
        editor.set_content_width(880)
        assert editor.image_width() > before


class TestContextMenu:
    """本文の右クリック（ユーザー要望 2026-08-22）。

    Qt の標準メニューを使う（元に戻す・切り取り…）。**日本語のカタログは
    `app.install_translations()` が当てる**が、その訳には Windows 流の
    アクセスキー（`元に戻す(&U)`）が付いている。macOS には要らない飾りなので
    落とす（Qt の cocoa 側も落とすが、**確かめられないものは自分で落とす**）。
    """

    def labels(self, editor) -> list[str]:
        menu = editor.build_context_menu()
        try:
            return [action.text() for action in menu.actions() if action.text()]
        finally:
            menu.deleteLater()

    def test_アクセスキーの飾りを出さない(self, editor) -> None:
        from PySide6.QtWidgets import QApplication

        from hitofude.app import install_translations

        install_translations(QApplication.instance())
        editor.setPlainText("本文")
        for label in self.labels(editor):
            assert "&" not in label, label
            assert "(" not in label.split("\t")[0], label

    def test_項目は今まで通り(self, editor) -> None:
        """**減らさない。** Qt が用意するものをそのまま使う。"""
        editor.setPlainText("本文")
        assert len(self.labels(editor)) >= 5
