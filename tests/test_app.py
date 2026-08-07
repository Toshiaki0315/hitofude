"""QApplication のセットアップのテスト（タスク 0-B-2 / spec §5.3）。"""

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
