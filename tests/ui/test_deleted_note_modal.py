"""外で消されたノートの聞き方（テストが止まる件。2026-08-26）。

**`make cov` が 10 分で打ち切られていた。** 常設した faulthandler が
居場所を出した——監視が「開いているノートが外で消された」を**遅れて**
届け、`pytestqt` の `_process_events`（テストの合間）でモーダルが開き、
**答える人がいないので止まる**。

```
main_window.py:_on_note_deleted     ← QMessageBox.question（モーダル）
main_window.py:_on_external_change
storage/watcher.py:poll
pytestqt/plugin.py:_process_events  ← テストの合間
```

**聞くこと自体は正しい。** 「いいえ」は本文ごと閉じる（＝打ちかけを
捨てる）ので、黙って決めてよい話ではない。直したのは**聞ける状態か**の
見極めと、試験の場では**必ず答えが返る**ようにしたこと。
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from hitofude.storage.watcher import ChangeKind

pytestmark = pytest.mark.gui


@pytest.fixture
def opened(window):
    note = window._vault.create("会議メモ", "# 会議メモ\n\n本文\n")
    window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(note.path)
    return window


class TestAsksWhenItCan:
    """ふだんは今までどおり聞く。"""

    def test_聞いてくる(self, opened, asked) -> None:
        path = opened.current_note.path
        path.unlink()
        opened._on_external_change(ChangeKind.DELETED, path)
        assert asked, "何も聞かずに決めた"

    def test_いいえなら閉じる(self, opened, asked) -> None:
        """既定の答えは「作り直さない」。**勝手に書き戻さない。**"""
        path = opened.current_note.path
        path.unlink()
        opened._on_external_change(ChangeKind.DELETED, path)
        assert opened.current_note is None

    def test_はいなら作り直す(self, opened, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        path = opened.current_note.path
        path.unlink()
        opened._on_external_change(ChangeKind.DELETED, path)
        assert path.is_file()


class TestClosing:
    """**閉じている最中は聞かない**（`closeEvent` が既に守っている作法）。

    終了の途中でモーダルを開くとアプリが終了できなくなる。同じ理由で、
    監視から遅れて届いた削除でも開かない。
    """

    def test_聞かない(self, opened, asked) -> None:
        path = opened.current_note.path
        path.unlink()
        opened._closing = True
        opened._on_external_change(ChangeKind.DELETED, path)
        assert asked == []

    def test_本文を捨てない(self, opened, asked) -> None:
        """**聞けないときに壊れるほうを選ばない。** 打ちかけを残す。"""
        opened.editor.setPlainText("# 会議メモ\n\nまだ保存していない字\n")
        path = opened.current_note.path
        path.unlink()
        opened._closing = True
        opened._on_external_change(ChangeKind.DELETED, path)
        assert "まだ保存していない字" in opened.editor.toPlainText()


class TestNeverBlocks:
    """**試験の場では必ず答えが返る**（`asked` フィクスチャが差し替える）。

    ここが無いと、監視が遅れて届けた削除でモーダルが開き、
    `_process_events` の中で止まる。止まると faulthandler が出るまで
    何も分からない。
    """

    def test_差し替えられている(self) -> None:
        assert QMessageBox.question.__module__ != "PySide6.QtWidgets"

    def test_答えは作り直さない(self, opened, asked) -> None:
        path = opened.current_note.path
        path.unlink()
        opened._on_external_change(ChangeKind.DELETED, path)
        assert asked[0][0] == "ファイルが削除されました"


class TestOtherPaths:
    """削除でも**開いていないノート**なら聞かない（今までどおり）。"""

    def test_別のノートなら聞かない(self, opened, asked) -> None:
        other = opened._vault.create("別のノート", "# 別のノート\n\n本文\n")
        other.path.unlink()
        opened._on_external_change(ChangeKind.DELETED, Path(other.path))
        assert asked == []
        assert opened.current_note is not None
