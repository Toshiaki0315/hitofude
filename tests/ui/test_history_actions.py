"""版の履歴の断り方（ADR-0023 / カバレッジの穴を埋める 2026-08-25）。

`HistoryActions` は `MainWindow` から切り出した束（`428be40`）。通しの
流れは `test_history_flow.py` が見ているが、**断る側の分岐が 1 つも
通っていなかった**（実測 75%）——ノートを開いていないとき、版が読めない
とき。どれも「壊れたときに落ちないか」なので、通っていないと困る。
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui


def write_body(window, body: str) -> None:
    """本文だけ書き換える（`test_history_flow.py` と同じ作法）。

    **front matter は消さない。** 丸ごと入れ替えると `id` ごと消え、
    履歴の鍵が変わって別のノート扱いになる（ADR-0013）。
    """
    from hitofude.core import frontmatter

    current = window.editor.toPlainText()
    split = frontmatter.split(current)
    head = current[: len(current) - len(split.body)]
    window.editor.setPlainText(head + body)


@pytest.fixture
def opened(window):
    """版が 1 つある状態。**書き換えないと保存が空振りする**（版も残らない）。"""
    window.new_note()
    write_body(window, "# 会議メモ\n\n本文\n")
    window.flush(explicit=True)
    return window


class TestNoNoteOpen:
    """**ノートを開いていない。** 起動直後や、開いていたものを捨てた直後。"""

    def test_版を残さない(self, window) -> None:
        window._close_current()
        assert window.keep_version("本文") is None

    def test_版の一覧は空(self, window) -> None:
        window._close_current()
        assert window.note_versions() == []

    def test_戻せない(self, opened) -> None:
        """先に版を作ってから閉じる（版はあるが、戻す先が無い状態）。"""
        version = opened.note_versions()[0]
        opened._close_current()
        assert opened.restore_version(version) is False

    def test_画面を出さずに知らせる(self, window) -> None:
        window._close_current()
        assert window.build_history_dialog() is None

    def test_開いてからと伝える(self, window) -> None:
        """**押しても無反応に見せない**（`exec()` に入らない道を通す）。"""
        window._close_current()
        window.show_history()
        assert "ノートを開いて" in window.notice()


class TestUnreadableVersion:
    """**版のファイルが読めない。** 外で消された・壊れた。"""

    def test_落ちずに断る(self, opened) -> None:
        version = opened.note_versions()[0]
        Path(version.path).unlink()
        assert opened.restore_version(version) is False

    def test_本文を壊さない(self, opened) -> None:
        """**戻せないなら何もしない。** 半端に消さない。"""
        version = opened.note_versions()[0]
        Path(version.path).unlink()
        before = opened.editor.toPlainText()
        opened.restore_version(version)
        assert opened.editor.toPlainText() == before

    def test_読めない版でも一覧は出せる(self, opened) -> None:
        """**1 つ壊れても全部見えなくならない。**"""
        Path(opened.note_versions()[0].path).unlink()
        assert opened.build_history_dialog() is not None


class TestRestoreKeepsCurrent:
    """**戻す前に今の内容を 1 版残す**（取り消せない操作を増やさない）。"""

    def test_戻した後に戻る前の版がある(self, opened, qtbot) -> None:
        old = opened.note_versions()[0]
        cursor = opened.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("あとから書いた字")

        assert opened.restore_version(old) is True
        assert "あとから書いた字" not in opened.editor.toPlainText()
        # 戻す直前の内容が残っているので、やり直せる
        assert any("あとから書いた字" in v.read() for v in opened.note_versions())

    def test_戻したことを知らせる(self, opened) -> None:
        assert opened.restore_version(opened.note_versions()[0]) is True
        assert "版に戻しました" in opened.notice()
