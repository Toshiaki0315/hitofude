"""環境設定のテスト（タスク 5-7 / spec §5.4）。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.theme import ThemeMode
from hitofude.ui.preferences import PreferencesDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    return config


@pytest.fixture
def dialog(qtbot, config: Config) -> PreferencesDialog:
    widget = PreferencesDialog(config)
    qtbot.addWidget(widget)
    return widget


class TestInitialValues:
    def test_現在のフォントを出す(self, dialog, config) -> None:
        assert dialog._font.currentText() == config.font_family

    def test_現在の文字サイズを出す(self, dialog, config) -> None:
        assert dialog._size.value() == pytest.approx(config.font_point_size)

    def test_現在のテーマを出す(self, dialog, config) -> None:
        assert dialog.selected_theme is config.theme_mode

    def test_現在の保管フォルダを出す(self, dialog, config) -> None:
        assert str(config.vault_path) in dialog._vault_label.text()

    def test_現在の保持日数を出す(self, dialog, config) -> None:
        assert dialog._trash_days.value() == config.trash_days


class TestApply:
    def test_文字サイズを保存する(self, dialog, config) -> None:
        dialog._size.setValue(18.0)
        dialog.apply()
        assert config.font_point_size == pytest.approx(18.0)

    def test_テーマを保存する(self, dialog, config) -> None:
        dialog._theme.setCurrentIndex(dialog._theme.findData(ThemeMode.DARK))
        dialog.apply()
        assert config.theme_mode is ThemeMode.DARK

    def test_保持日数を保存する(self, dialog, config) -> None:
        dialog._trash_days.setValue(7)
        dialog.apply()
        assert config.trash_days == 7

    def test_保管フォルダを保存する(self, dialog, config, tmp_path) -> None:
        target = tmp_path / "別の保管フォルダ"
        dialog.set_vault(target)
        dialog.apply()
        assert config.vault_path == target

    def test_変えなければ保管フォルダはそのまま(self, dialog, config) -> None:
        before = config.vault_path
        dialog.apply()
        assert config.vault_path == before

    def test_適用したことを知らせる(self, dialog, qtbot) -> None:
        with qtbot.waitSignal(dialog.applied, timeout=1000):
            dialog.apply()

    def test_OKで書き込まれて閉じる(self, dialog, config) -> None:
        dialog._trash_days.setValue(14)
        dialog.accept()
        assert config.trash_days == 14
        assert dialog.result() == PreferencesDialog.DialogCode.Accepted

    def test_キャンセルでは書き込まない(self, dialog, config) -> None:
        before = config.trash_days
        dialog._trash_days.setValue(3)
        dialog.reject()
        assert config.trash_days == before


class TestRestartNotice:
    """保管フォルダを変えても索引と監視は再起動まで切り替わらない。"""

    def test_最初は出ていない(self, dialog) -> None:
        assert dialog._restart_note.isVisible() is False

    def test_フォルダを変えると出る(self, dialog, tmp_path) -> None:
        dialog.show()
        dialog.set_vault(tmp_path / "別の保管フォルダ")
        assert dialog._restart_note.isVisible() is True

    def test_同じフォルダを選び直したら出ない(self, dialog, config) -> None:
        dialog.show()
        dialog.set_vault(config.vault_path)
        assert dialog._restart_note.isVisible() is False


class TestBounds:
    def test_文字サイズの下限と上限がある(self, dialog) -> None:
        """設定画面からは壊れた値を入れられないようにする。"""
        from hitofude.config import MAX_POINT_SIZE, MIN_POINT_SIZE

        assert dialog._size.minimum() == pytest.approx(MIN_POINT_SIZE)
        assert dialog._size.maximum() == pytest.approx(MAX_POINT_SIZE)

    def test_保持日数は1日以上(self, dialog) -> None:
        assert dialog._trash_days.minimum() >= 1
