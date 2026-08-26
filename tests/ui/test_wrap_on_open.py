"""開いた直後に折り返しが古いままになる（ユーザー報告 2026-08-26）。

「本文の幅を超えた場合に折り返さずに横スクロールしていくのが仕様ですか」
——**仕様ではない。** 折り返しは入っている（`LineWrapMode.WidgetWidth`）。

**窓を開けて最初に読み込んだノート**で、折り返しが**幅の決まる前の値**の
まま残る。左右の余白（`setViewportMargins`）が入る前・縦スクロールバーが
出る前の広い幅で折り返しているので、長い行が右へはみ出して横スクロールが
出る。**窓を 1px 動かすだけで直る**（実測: 854px → 654px、横 200 → 0）ので、
中身ではなく計算し直していないだけ。

表や記法とは関係ない。**ふつうの日本語の本文だけでも再現する。**
"""

import pytest

pytestmark = pytest.mark.gui

LINE = "これは日本語の本文です。折り返しの検査に使います。"
LONG = "\n\n".join(LINE * 3 for _ in range(40))
"""**縦スクロールが出る長さ**にする。出た瞬間に本文の幅が縮むので、
そこで計算し直さないと古い折り返しが残る。"""


def widest(editor) -> float:
    """いちばん長い行（折り返した後）の幅。"""
    found = 0.0
    block = editor.document().begin()
    while block.isValid():
        layout = block.layout()
        if layout is not None:
            for index in range(layout.lineCount()):
                found = max(found, layout.lineAt(index).naturalTextWidth())
        block = block.next()
    return found


@pytest.fixture
def shown(config, qtbot):
    """**実アプリと同じ順**で組む（ここでしか起きない）。

    `MainWindow` は**構築の途中でノートを開く**（前回のノート・使い方の
    ノート）。そのとき本文の幅はまだ決まっていない——左右の余白も
    縦スクロールバーも、窓を出してから確定する。

    **先に `show()` してから本文を入れると再現しない**（幅が確定済みに
    なるため）。最初そう書いて、試験が素通りした。
    """
    from hitofude.storage.vault import Vault
    from hitofude.ui.main_window import MainWindow

    root = config.vault_path
    vault = Vault(root)
    vault.ensure_layout()
    note = vault.create("長いノート", f"# 長いノート\n\n{LONG}\n")
    config.last_note = str(note.path.relative_to(root))

    window = MainWindow(config)
    qtbot.addWidget(window)
    window.resize(1400, 760)
    window.show()
    qtbot.waitExposed(window)
    yield window
    window.close()


class TestFirstNote:
    def test_横スクロールが出ない(self, shown) -> None:
        """**これが本題。** 折り返すのだから、横へ伸びる理由が無い。"""
        assert shown.editor.horizontalScrollBar().maximum() == 0

    def test_本文の幅に収まっている(self, shown) -> None:
        """スクロールバーだけ消しても、はみ出していたら意味が無い。"""
        editor = shown.editor
        assert widest(editor) <= editor.viewport().width()

    def test_窓を動かさなくても同じ(self, shown, qtbot) -> None:
        """**動かせば直る**のは分かっている（実測 854px → 654px）。
        動かす**前から**正しいことを見る。
        """
        before = widest(shown.editor)
        shown.resize(1401, 760)
        qtbot.wait(30)
        shown.resize(1400, 760)
        qtbot.wait(30)
        assert before == pytest.approx(widest(shown.editor), abs=1.0)


class TestOpenNote:
    """あとから開くノートでも同じ。"""

    def test_開いた直後も収まっている(self, shown, qtbot) -> None:
        note = shown._vault.create("もう 1 本", f"# もう 1 本\n\n{LONG}\n")
        shown._db.upsert_note(note, shown._vault.root)
        shown.refresh()
        shown.open_and_select(note.path)
        qtbot.wait(30)
        assert shown.editor.horizontalScrollBar().maximum() == 0


class TestStillWraps:
    """**折り返しそのものは壊さない。**"""

    def test_長い行は折り返る(self, shown, qtbot) -> None:
        editor = shown.editor
        editor.setPlainText(LINE * 20)
        qtbot.wait(30)
        block = editor.document().findBlockByNumber(0)
        assert block.layout().lineCount() > 1, "1 行のままなら折り返していない"

    def test_短い行は折り返らない(self, shown, qtbot) -> None:
        editor = shown.editor
        editor.setPlainText("短い行")
        qtbot.wait(30)
        assert editor.document().findBlockByNumber(0).layout().lineCount() == 1
