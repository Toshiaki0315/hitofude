"""版を選んで戻す画面（提案 6 / ADR-0023）。

**中身を見てから戻す。** 日時だけでは、どれが探している版か分からない。
"""

from datetime import datetime, timedelta

import pytest

from hitofude.storage.history import Version
from hitofude.ui.history_dialog import HistoryDialog

pytestmark = pytest.mark.gui

NOW = datetime(2026, 8, 20, 10, 0, 0)


def make_versions(tmp_path) -> list[Version]:
    found = []
    for index, minutes in enumerate((0, 30, 60)):
        path = tmp_path / f"{index}.md"
        path.write_text(f"# 版 {index}\n\n本文 {index}\n", encoding="utf-8")
        found.append(
            Version(path=path, saved_at=NOW - timedelta(minutes=minutes), title=f"版 {index}")
        )
    return found


@pytest.fixture
def dialog(qtbot, tmp_path) -> HistoryDialog:
    widget = HistoryDialog(make_versions(tmp_path))
    qtbot.addWidget(widget)
    return widget


class TestList:
    def test_版が並ぶ(self, dialog) -> None:
        assert dialog.row_count() == 3

    def test_新しい順(self, dialog) -> None:
        """**直近の状態ほど戻したくなる。** 上から新しい順に並べる。"""
        assert "10:00" in dialog.row_label(0)
        assert "09:00" in dialog.row_label(2)

    def test_その時の題名も出す(self, dialog) -> None:
        """日時だけでは、どれが探している版か見当が付かない。"""
        assert "版 0" in dialog.row_label(0)

    def test_選ぶと中身が出る(self, dialog) -> None:
        dialog.select_row(1)
        assert "本文 1" in dialog.preview_text()

    def test_最初から1つ目を選んでおく(self, dialog) -> None:
        """開いた瞬間に何も出ていないと、壊れているように見える。"""
        assert "本文 0" in dialog.preview_text()

    def test_front_matterは出さない(self, qtbot, tmp_path) -> None:
        """ADR-0013 で「書く人には出さない」と決めたもの。ここだけ出すと、
        本文で見えないものが履歴で見えることになる。"""
        path = tmp_path / "meta.md"
        path.write_text(
            "---\nid: 01ABC\nmodified: 2026-08-20T10:00:00+09:00\n---\n# 題名\n\n本文\n",
            encoding="utf-8",
        )
        widget = HistoryDialog([Version(path=path, saved_at=NOW, title="題名")])
        qtbot.addWidget(widget)

        assert "01ABC" not in widget.preview_text()
        assert "# 題名" in widget.preview_text()

    def test_閉じるボタンは日本語(self, dialog) -> None:
        """Qt の既定は英語（`Close`）。画面の言葉を揃える。"""
        assert dialog.close_button.text() == "閉じる"

    def test_中身は読むだけ(self, dialog) -> None:
        """**ここでは直せない。** 直すなら戻してから本文で直す。"""
        assert dialog.preview_is_read_only() is True


class TestChoose:
    def test_戻すと選んだ版を返す(self, dialog, qtbot) -> None:
        dialog.select_row(2)
        with qtbot.waitSignal(dialog.restore_requested, timeout=1000) as blocker:
            dialog.restore()
        assert blocker.args[0].title == "版 2"

    def test_閉じても何も起きない(self, dialog) -> None:
        dialog.reject()
        assert dialog.result() == 0


class TestEmpty:
    def test_版が無ければ案内を出す(self, qtbot) -> None:
        widget = HistoryDialog([])
        qtbot.addWidget(widget)
        assert widget.row_count() == 0
        assert widget.empty_notice_visible() is True

    def test_版が無ければ戻せない(self, qtbot) -> None:
        widget = HistoryDialog([])
        qtbot.addWidget(widget)
        assert widget.restore_button.isEnabled() is False
