"""QApplication のセットアップのテスト（タスク 0-B-2 / spec §5.3）。"""

import sys

import pytest
from PySide6.QtWidgets import QApplication

from hitofude.app import APP_NAME, ORG_DOMAIN, apply_theme, create_application
from hitofude.theme import DARK, LIGHT

pytestmark = pytest.mark.gui


def test_create_applicationは既存インスタンスを再利用する(qapp: QApplication) -> None:
    """QApplication は 1 プロセスに 1 つしか作れない。二重生成は即クラッシュする。"""
    assert create_application() is qapp
    assert create_application() is qapp


def test_アプリのメタ情報が設定される(qapp: QApplication) -> None:
    """QSettings の保存先がこの 3 つで決まる（spec §4）。"""
    create_application()
    assert qapp.applicationName() == APP_NAME
    assert qapp.organizationDomain() == ORG_DOMAIN
    assert qapp.applicationVersion()


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=["light", "dark"])
def test_apply_themeがパレットに反映される(qapp: QApplication, theme) -> None:
    apply_theme(qapp, theme)
    palette = qapp.palette()
    assert palette.window().color().name().lower() == theme.background.lower()
    assert palette.windowText().color().name().lower() == theme.foreground.lower()


class TestMacOSAppName:
    """メニューバー先頭に出る名前（ユーザー報告: "Python" と出る）。

    `python -m hitofude` で動かすと主バンドルが Python.framework の
    `Python.app` になり、Qt はその `CFBundleName`（= "Python"）を読む。
    メニューバーそのものは offscreen では作られないので、**Qt が読む口**
    である `CFBundleGetValueForInfoDictionaryKey()` の値を検査する。
    """

    def test_バンドル名を差し替えられる(self) -> None:
        from hitofude.app import macos_app_name, set_macos_app_name

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        assert set_macos_app_name("Hitofude") is True
        assert macos_app_name() == "Hitofude"

    def test_create_applicationがアプリ名を名乗らせる(self, qapp: QApplication) -> None:
        from hitofude import APP_NAME
        from hitofude.app import create_application, macos_app_name, set_macos_app_name

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        set_macos_app_name("差し替え前")
        create_application()
        assert macos_app_name() == APP_NAME

    def test_macOS以外では何もしない(self, monkeypatch) -> None:
        from hitofude.app import macos_app_name, set_macos_app_name

        monkeypatch.setattr(sys, "platform", "linux")
        assert set_macos_app_name("Hitofude") is False
        assert macos_app_name() is None

    def test_CoreFoundationが引けなくても落ちない(self, monkeypatch) -> None:
        """名前が変わらないだけ。起動を止める理由にはならない。"""
        import ctypes.util

        from hitofude.app import macos_app_name, set_macos_app_name

        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        assert set_macos_app_name("Hitofude") is False
        assert macos_app_name() is None

    def test_例外が出ても起動を止めない(self, monkeypatch) -> None:
        import ctypes.util

        from hitofude.app import create_application, set_macos_app_name

        def explode(name: str) -> str:
            raise OSError("読めない")

        monkeypatch.setattr(ctypes.util, "find_library", explode)
        assert set_macos_app_name("Hitofude") is False
        assert create_application() is not None
