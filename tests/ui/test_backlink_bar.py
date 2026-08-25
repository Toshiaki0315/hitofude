"""バックリンクの帯（E-6 ③ / ADR-0011）。

**本文の下に置く。** パレットにすると探しに行った人しか見ず、右ペインに
すると幅を常に取る（0 件のノートのほうが多いのに）。

**エディタの文書に文字として入れてはいけない。** `toPlainText()` が
そのまま保存内容（R1）なので、ファイルに無い文字が混ざる。ここは
`ui/editor_pane.py` に積むただのウィジェット。
"""

from pathlib import Path

import pytest

from hitofude.ui.backlink_bar import Backlink, BacklinkBar

pytestmark = pytest.mark.gui

LINKS = [
    Backlink(title="日報", context="詳しくは [[会議メモ]] を見て", path=Path("日報.md")),
    Backlink(title="週報", context="[[会議メモ]] の続き", path=Path("週報.md")),
]


@pytest.fixture
def bar(qtbot) -> BacklinkBar:
    widget = BacklinkBar()
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestEmpty:
    def test_0件なら帯ごと消える(self, bar) -> None:
        """**大半のノートは 0 件。** 空の枠を出し続けない。"""
        bar.set_links([])
        assert bar.isHidden()

    def test_1件でも出る(self, bar) -> None:
        bar.set_links(LINKS[:1])
        assert not bar.isHidden()

    def test_0件に戻ると消える(self, bar) -> None:
        bar.set_links(LINKS)
        bar.set_links([])
        assert bar.isHidden()


class TestHeader:
    def test_件数が出る(self, bar) -> None:
        bar.set_links(LINKS)
        assert "2" in bar.header_text()

    def test_バックリンクと分かる(self, bar) -> None:
        bar.set_links(LINKS)
        assert "バックリンク" in bar.header_text()

    def test_はじめは畳んである(self, bar) -> None:
        """常に画面の下にいるので、開きっぱなしは場所を取る。件数だけ出す。"""
        bar.set_links(LINKS)
        assert bar.expanded() is False
        assert bar.list_widget().isHidden()

    def test_押すと開く(self, bar, qtbot) -> None:
        bar.set_links(LINKS)
        bar.toggle()
        assert bar.expanded() is True
        assert not bar.list_widget().isHidden()

    def test_もう一度押すと閉じる(self, bar) -> None:
        bar.set_links(LINKS)
        bar.toggle()
        bar.toggle()
        assert bar.expanded() is False

    def test_開いたまま別のノートへ移っても開いている(self, bar) -> None:
        """開閉は帯の状態で、ノートごとに戻されると煩わしい。"""
        bar.set_links(LINKS)
        bar.toggle()
        bar.set_links(LINKS[:1])
        assert bar.expanded() is True


class TestList:
    def test_題名が並ぶ(self, bar) -> None:
        bar.set_links(LINKS)
        assert bar.titles() == ["日報", "週報"]

    def test_指している行も出る(self, bar) -> None:
        """冒頭ではなく**指している行**。長いノートでは冒頭を見ても分からない。"""
        bar.set_links(LINKS)
        assert "詳しくは [[会議メモ]] を見て" in bar.item_text(0)

    def test_入れ替わる(self, bar) -> None:
        bar.set_links(LINKS)
        bar.set_links(LINKS[1:])
        assert bar.titles() == ["週報"]


class TestOpening:
    def test_押すと合図が出る(self, bar, qtbot) -> None:
        bar.set_links(LINKS)
        with qtbot.waitSignal(bar.note_activated) as blocker:
            bar.activate(0)
        assert blocker.args[0] == Path("日報.md")

    def test_無い行では何も起きない(self, bar) -> None:
        bar.set_links(LINKS)
        bar.activate(5)  # 落ちなければよい


class TestFocus:
    def test_帯はフォーカスを奪わない(self, bar) -> None:
        """奪うと本文の選択が外れる（書式ツールバーと同じ約束）。"""
        from PySide6.QtCore import Qt

        bar.set_links(LINKS)
        assert bar.header_button().focusPolicy() is Qt.FocusPolicy.NoFocus
