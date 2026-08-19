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


class TestExistingTitle:
    """**題名が日付でも、ファイル名が同じとは限らない**（ユーザー報告）。

    「日次」テンプレートから作ると、ファイルは `日次-2.md` のままで題名だけ
    `2026-08-20` になる。ここで日付からファイル名を組み直すと、既にある
    ノートを見つけられず**同じ日のノートがもう 1 つできる**。

    索引が見つけたノートを、その**パスのまま**開くこと。
    """

    def make_titled(self, window: MainWindow, title: str, filename: str):
        note = window.vault.create(filename, f"# {title}\n\n#日次\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        return note

    def test_辿った先で複製を作らない(self, window) -> None:
        make_daily(window, "2026-08-19")
        self.make_titled(window, "2026-08-20", "日次-2")
        window.open_daily_note(datetime(2026, 8, 19))
        before = window.note_list.model().rowCount()

        window.open_adjacent_daily(forward=True)

        assert window.note_list.model().rowCount() == before
        assert title(window) == "2026-08-20"

    def test_辿った先は既にあるファイル(self, window) -> None:
        make_daily(window, "2026-08-19")
        existing = self.make_titled(window, "2026-08-20", "日次-2")
        window.open_daily_note(datetime(2026, 8, 19))

        window.open_adjacent_daily(forward=True)
        assert window.current_note.path == existing.path

    def test_今日のノートも複製を作らない(self, window) -> None:
        """`Cmd+T` も同じ穴を持っていた（ファイル名だけで探していた）。"""
        today = datetime.now()
        existing = self.make_titled(window, today.strftime("%Y-%m-%d"), "日次-2")
        before = window.note_list.model().rowCount()

        window.open_daily_note()

        assert window.note_list.model().rowCount() == before
        assert window.current_note.path == existing.path


class TestSelection:
    """**開いたら一覧の選択も動く**（ユーザー報告）。

    移動はできても一覧の帯が前のノートに残ると、今どれを見ているのかが
    画面から読めない。`_open_created` の docstring が警告していた
    「select 漏れ」を、既にあるノートを開く経路でやってしまっていた。
    """

    def selected(self, window: MainWindow):
        return window.note_list.current_path()

    def test_次の日で選択が動く(self, window) -> None:
        make_daily(window, "2026-08-19", "2026-08-20")
        window.open_daily_note(datetime(2026, 8, 19))

        window.open_adjacent_daily(forward=True)
        assert self.selected(window) == window.current_note.path.relative_to(window.vault.root)

    def test_前の日でも選択が動く(self, window) -> None:
        make_daily(window, "2026-08-19", "2026-08-20")
        window.open_daily_note(datetime(2026, 8, 20))

        window.open_adjacent_daily(forward=False)
        assert self.selected(window) == window.current_note.path.relative_to(window.vault.root)

    def test_今日のノートでも選択が動く(self, window) -> None:
        """既にあるノートを開く経路（題名で見つけたとき）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        note = window.vault.create("日次-2", f"# {today}\n\n#日次\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()

        window.open_daily_note()
        assert self.selected(window) == note.path.relative_to(window.vault.root)


class TestHistorySelection:
    """`Cmd+[`（直前のノートへ戻る）にも同じ穴があった。

    戻れているのに一覧の帯が前のノートに残る。**開く経路が増えるたびに
    select 漏れが起きる**ので、受け口を 1 つに寄せた（`open_and_select`）。
    """

    def test_戻ると選択も動く(self, window) -> None:
        paths = []
        for name in ("あ", "い"):
            note = window.vault.create(name, f"# {name}\n")
            window.vault_index.upsert_note(note, window.vault.root)
            paths.append(note.path)
        window.refresh()
        window.open_and_select(paths[0])
        window.open_and_select(paths[1])

        window.open_previous_note()

        assert window.current_note.path == paths[0]
        assert window.note_list.current_path() == paths[0].relative_to(window.vault.root)
