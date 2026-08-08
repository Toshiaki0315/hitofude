"""競合ダイアログのテスト（タスク 4-9 / spec §7.5）。"""

from pathlib import Path

import pytest

from hitofude.ui.conflict_dialog import ConflictDialog, Resolution

pytestmark = pytest.mark.gui


@pytest.fixture
def dialog(qtbot) -> ConflictDialog:
    widget = ConflictDialog(Path("/vault/会議メモ.md"))
    qtbot.addWidget(widget)
    return widget


class TestConflictDialog:
    def test_ファイル名を表示する(self, dialog) -> None:
        from PySide6.QtWidgets import QLabel

        texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert "会議メモ.md" in texts

    def test_既定は何もしない(self, dialog) -> None:
        assert dialog.resolution is Resolution.CANCEL

    def test_既定のボタンは両方残す(self, dialog) -> None:
        """押し間違いで書いた内容が消えないよう、破壊的でない選択を既定にする。"""
        assert dialog._keep_both.isDefault() is True

    def test_選択肢が3つある(self, dialog) -> None:
        """spec §7.5: 外部の変更を採用 / 自分の版を採用 / 両方残す。"""
        from PySide6.QtWidgets import QDialogButtonBox

        box = dialog.findChild(QDialogButtonBox)
        labels = {button.text() for button in box.buttons()}
        assert "両方残す" in labels
        assert "外部の変更を採用" in labels
        assert "自分の版を採用" in labels

    @pytest.mark.parametrize(
        ("attribute", "expected"),
        [
            ("_keep_both", Resolution.KEEP_BOTH),
            ("_take_external", Resolution.TAKE_EXTERNAL),
            ("_take_mine", Resolution.TAKE_MINE),
        ],
    )
    def test_押したボタンが結果になる(self, dialog, qtbot, attribute, expected) -> None:
        getattr(dialog, attribute).click()
        assert dialog.resolution is expected

    def test_押すとダイアログが閉じる(self, dialog) -> None:
        dialog._keep_both.click()
        assert dialog.result() == ConflictDialog.DialogCode.Accepted

    def test_キャンセルすると何もしない(self, dialog) -> None:
        dialog.reject()
        assert dialog.resolution is Resolution.CANCEL
