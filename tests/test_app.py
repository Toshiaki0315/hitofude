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


class TestKeyRepeat:
    """押しっぱなしで文字が繰り返されるようにする（ユーザー要望）。

    macOS は既定で、母音などを押し続けるとアクセント候補を出す
    （`ApplePressAndHoldEnabled`）。文章を書くアプリでは繰り返しのほうが
    要る。**このプロセスにだけ**登録し、ユーザーの設定は書き換えない。
    """

    def test_登録できる(self) -> None:
        from hitofude.app import enable_key_repeat, key_repeat_enabled

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        assert enable_key_repeat() is True
        assert key_repeat_enabled() is True

    def test_未登録なら有効と答えない(self) -> None:
        """**`boolForKey:` は未設定でも NO を返す。** 値の有無まで見ないと、
        「まだ登録していない」を「有効」と誤って報告する（実際に踏んだ）。"""
        import subprocess

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        probe = (
            "import sys; sys.path.insert(0, '.');"
            "from hitofude.app import key_repeat_enabled; print(key_repeat_enabled())"
        )
        got = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=".")
        assert got.stdout.strip() == "False"

    def test_create_applicationで有効になる(self, qapp: QApplication) -> None:
        from hitofude.app import create_application, key_repeat_enabled

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        create_application()
        assert key_repeat_enabled() is True

    def test_macOS以外では何もしない(self, monkeypatch) -> None:
        from hitofude.app import enable_key_repeat, key_repeat_enabled

        monkeypatch.setattr(sys, "platform", "linux")
        assert enable_key_repeat() is False
        assert key_repeat_enabled() is False

    def test_objcが引けなくても落ちない(self, monkeypatch) -> None:
        import ctypes.util

        from hitofude.app import enable_key_repeat

        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        assert enable_key_repeat() is False

    def test_例外が出ても起動を止めない(self, monkeypatch) -> None:
        import ctypes.util

        from hitofude.app import create_application, enable_key_repeat

        def explode(name: str) -> str:
            raise OSError("読めない")

        monkeypatch.setattr(ctypes.util, "find_library", explode)
        assert enable_key_repeat() is False
        assert create_application() is not None

    def test_ユーザーの設定を書き換えない(self) -> None:
        """**登録するだけ。** 保存されている設定に触れると、他のアプリや
        次回以降の macOS の挙動まで変えてしまう。"""
        import subprocess

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        from hitofude.app import enable_key_repeat

        before = subprocess.run(
            ["defaults", "read", "-g", "ApplePressAndHoldEnabled"],
            capture_output=True,
            text=True,
        )
        enable_key_repeat()
        after = subprocess.run(
            ["defaults", "read", "-g", "ApplePressAndHoldEnabled"],
            capture_output=True,
            text=True,
        )
        assert (before.returncode, before.stdout) == (after.returncode, after.stdout)
