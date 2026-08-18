"""ショートカット一覧（C-7 / ユーザー提案）。

今はメニューを開かないと分からない。**メニューから作る**ので二重管理に
ならない（追加したのに一覧へ載せ忘れる、が起きない）。
"""

import pytest

from hitofude.ui.shortcut_sheet import ShortcutSheet, shortcut_rows

pytestmark = pytest.mark.gui


class TestRows:
    def test_メニューから作る(self, window) -> None:
        assert shortcut_rows(window)

    def test_メニューごとにまとまる(self, window) -> None:
        groups = {group for group, _, _ in shortcut_rows(window)}
        assert {"ファイル", "編集", "表示"} <= groups

    def test_名前とキーが揃う(self, window) -> None:
        rows = shortcut_rows(window)
        assert all(label and keys for _, label, keys in rows)

    def test_キーの無い項目は載せない(self, window) -> None:
        """「Hitofude について」のようなものは一覧に要らない。"""
        labels = [label for _, label, _ in shortcut_rows(window)]
        assert not any("について" in label for label in labels)

    def test_主なものが載る(self, window) -> None:
        labels = [label for _, label, _ in shortcut_rows(window)]
        assert "新規ノート" in labels
        assert "見出しへ飛ぶ" in labels

    def test_Macの記号で見せる(self, window) -> None:
        """`Ctrl+N` ではなく `⌘N`。画面のキーと同じ表記にする。"""
        keys = [keys for _, _, keys in shortcut_rows(window)]
        assert any("⌘" in entry for entry in keys)


class TestSheet:
    def test_開ける(self, window, qtbot) -> None:
        sheet = ShortcutSheet(window)
        qtbot.addWidget(sheet)
        assert sheet.row_count() > 0

    def test_見出しと本文が入る(self, window, qtbot) -> None:
        sheet = ShortcutSheet(window)
        qtbot.addWidget(sheet)
        assert "新規ノート" in sheet.text()

    def test_ウィンドウから開ける(self, window) -> None:
        window.show_shortcuts()
        assert window.findChild(ShortcutSheet) is not None
