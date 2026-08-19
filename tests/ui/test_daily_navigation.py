"""日次ノートを日付順に辿る（ユーザー要望）。

`Cmd+T` で今日は開けたが、**昨日・明日へ動けなかった**。日誌として使うなら
日付を辿る道が要る。

**既にあるものだけを辿る。** 書かなかった日にも空のノートを作ると、一覧が
空ノートで埋まる。端まで来たら知らせるだけ。
"""

from datetime import datetime

import pytest

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def make_daily(window: MainWindow, *days: str) -> None:
    for day in days:
        note = window.vault.daily_note(datetime.strptime(day, "%Y-%m-%d")).note
        window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()


def title(window: MainWindow) -> str | None:
    return window.current_note.title if window.current_note is not None else None


class TestNavigate:
    def test_前の日へ動ける(self, window) -> None:
        make_daily(window, "2026-08-10", "2026-08-12", "2026-08-14")
        window.open_daily_note(datetime(2026, 8, 14))

        assert window.open_adjacent_daily(forward=False) is True
        assert title(window) == "2026-08-12"

    def test_次の日へ動ける(self, window) -> None:
        make_daily(window, "2026-08-10", "2026-08-12")
        window.open_daily_note(datetime(2026, 8, 10))

        assert window.open_adjacent_daily(forward=True) is True
        assert title(window) == "2026-08-12"

    def test_書かなかった日は飛ばす(self, window) -> None:
        make_daily(window, "2026-01-01", "2026-08-14")
        window.open_daily_note(datetime(2026, 8, 14))

        window.open_adjacent_daily(forward=False)
        assert title(window) == "2026-01-01"

    def test_端では動かず知らせる(self, window) -> None:
        make_daily(window, "2026-08-14")
        window.open_daily_note(datetime(2026, 8, 14))

        assert window.open_adjacent_daily(forward=False) is False
        assert title(window) == "2026-08-14"
        assert window.notice()

    def test_空のノートを作らない(self, window) -> None:
        """**端で新しい日を作らない。** 書かなかった日が一覧に増える。"""
        make_daily(window, "2026-08-14")
        window.open_daily_note(datetime(2026, 8, 14))
        before = window.note_list.model().rowCount()

        window.open_adjacent_daily(forward=True)
        assert window.note_list.model().rowCount() == before

    def test_日次でないノートからは今日を基準にする(self, window) -> None:
        """ふつうのノートを見ているときに押しても、日誌へ入れる。"""
        make_daily(window, "2026-08-10")
        note = window.vault.create("会議メモ", "# 会議メモ\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)

        assert window.open_adjacent_daily(forward=False) is True
        assert title(window) == "2026-08-10"


class TestMenu:
    def labels(self, window: MainWindow) -> dict[str, str]:
        return {a.text(): a.shortcut().toString() for a in window.actions()}

    def test_メニューに入っている(self, window) -> None:
        found = self.labels(window)
        assert "前の日のノート" in found
        assert "次の日のノート" in found

    def test_キーが付いている(self, window) -> None:
        from PySide6.QtGui import QKeySequence

        found = self.labels(window)
        assert found["前の日のノート"] == QKeySequence("Ctrl+Shift+[").toString()
        assert found["次の日のノート"] == QKeySequence("Ctrl+Shift+]").toString()
