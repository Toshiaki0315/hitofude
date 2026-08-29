"""ノートを 2 つ並べて見る（U-1。ユーザー要望 2026-08-29）。

**まず読むだけ。** 「参照しながら書く」という目的は読めれば満たせるし、
保存の道（`save_controller` は単一ノート前提で 10 箇所が `window._note`
を握っている）に一切触れずに済む。両方を編集できるようにするのは、
保存・競合・監視を**ノートごとに持ち直す**大仕事なので分ける。

見た目は本文と同じ（同じ `MarkdownEditor` を読み取り専用で使う）。
別の描き方を用意すると、帯や折りたたみがまた 2 系統になる——今回の
一連で 3 度踏んだ形。
"""

import pytest
from PySide6.QtGui import QTextCursor

from hitofude.ui.reference_pane import ReferencePane

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> ReferencePane:
    widget = ReferencePane()
    qtbot.addWidget(widget)
    widget.resize(320, 400)
    return widget


class TestShowNote:
    def test_本文が出る(self, pane) -> None:
        pane.show_note("会議メモ", "# 会議メモ\n\n決めたこと\n")
        assert "決めたこと" in pane.editor.toPlainText()

    def test_題名が出る(self, pane) -> None:
        """**どのノートを見ているか**が分からないと参照にならない。"""
        pane.show_note("会議メモ", "# 会議メモ\n\n決めたこと\n")
        assert pane.title() == "会議メモ"

    def test_書き換えられない(self, pane) -> None:
        """**読むだけ**（保存の道に触れない）。"""
        pane.show_note("会議メモ", "# 会議メモ\n\n決めたこと\n")
        assert pane.editor.isReadOnly()

    def test_打っても変わらない(self, pane, qtbot) -> None:
        pane.show_note("会議メモ", "# 会議メモ\n\n決めたこと\n")
        before = pane.editor.toPlainText()
        cursor = pane.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        pane.editor.setTextCursor(cursor)
        qtbot.keyClick(pane.editor, "a")
        assert pane.editor.toPlainText() == before

    def test_装飾は本文と同じに出る(self, pane) -> None:
        """**別の描き方を作らない。** 同じ `MarkdownEditor` を使う。"""
        from hitofude.core.models import BlockType

        pane.show_note("見本", "# 見本\n\n```python\nprint(1)\n```\n")
        data = pane.editor.document().findBlockByNumber(3).userData()
        assert data is not None and data.info.type is BlockType.CODE_FENCE_BODY


class TestEmpty:
    def test_何も出していなければ知らせる(self, pane) -> None:
        assert pane.title() == ""
        assert pane.is_empty()

    def test_閉じると空になる(self, pane) -> None:
        pane.show_note("会議メモ", "# 会議メモ\n\n決めたこと\n")
        pane.clear()
        assert pane.is_empty()
        assert pane.editor.toPlainText() == ""


class TestCloseButton:
    """右上の「閉じる」（ユーザー要望 2026-08-29）。

    横に開いたノートを**その場で閉じられる**ようにする。表示メニューへ
    戻るのは遠い（見えているものを消すのに、見えていない場所を探させない）。

    ボタンの形は `quick_open.close_button`——**押せるものだと分かる形を
    アプリの中で 1 つに揃える**（パレットとリンクの図が既に使っている）。
    """

    def test_ボタンがある(self, pane) -> None:
        assert pane.close_button is not None

    def test_右上にある(self, pane) -> None:
        """題名の右。**本文の上ではなく、ペインの頭**に置く。"""
        pane.resize(320, 400)
        pane.show()
        button = pane.close_button
        assert button.x() > pane.width() / 2
        assert button.y() < pane.height() / 4

    def test_押すと知らせる(self, pane, qtbot) -> None:
        """**閉じるのは呼び出し側**（ペインは窓の都合を知らない）。"""
        got: list[int] = []
        pane.close_requested.connect(lambda: got.append(1))
        pane.close_button.click()
        assert got == [1]

    def test_中身も空になる(self, pane) -> None:
        """閉じたのに次に開いたとき前のノートが出ていては驚く。"""
        pane.show_note("会議メモ", "# 会議メモ\n\n本文\n")
        pane.close_button.click()
        assert pane.is_empty()
