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


class TestPaletteRoles:
    """ボタン系の色も流し込む（ユーザー報告）。

    ダークにすると設定の「テーマ」欄が読みにくかった。ネイティブの
    ポップアップボタンは `Button` / `ButtonText` で描かれるのに、そこだけ
    システムの明るい既定（`#ececec` / `#000000`）が残っていた。
    """

    @pytest.mark.parametrize("mode", [LIGHT, DARK])
    def test_ボタンの色がテーマに合う(self, qapp: QApplication, mode) -> None:
        from PySide6.QtGui import QPalette

        apply_theme(qapp, mode)
        palette = qapp.palette()
        assert palette.color(QPalette.ColorRole.Button).name() == mode.background.lower()
        assert palette.color(QPalette.ColorRole.ButtonText).name() == mode.foreground.lower()

    def test_ダークでボタンの文字が背景と違う(self, qapp: QApplication) -> None:
        """同じ色になると読めない。"""
        from PySide6.QtGui import QPalette

        apply_theme(qapp, DARK)
        palette = qapp.palette()
        assert palette.color(QPalette.ColorRole.ButtonText) != palette.color(
            QPalette.ColorRole.Button
        )

    def test_無効な項目は控えめな色になる(self, qapp: QApplication) -> None:
        """既定のままだと、暗い背景に黒い「無効」文字が乗って消える。"""
        from PySide6.QtGui import QPalette

        apply_theme(qapp, DARK)
        palette = qapp.palette()
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            disabled = palette.color(QPalette.ColorGroup.Disabled, role)
            assert disabled.name() == DARK.muted_foreground.lower()

    @pytest.mark.parametrize("mode", [LIGHT, DARK])
    def test_主要な役割が全部テーマ由来になる(self, qapp: QApplication, mode) -> None:
        """1 つでもシステムの既定が残ると、そこだけ浮いて読めなくなる。"""
        from PySide6.QtGui import QPalette

        apply_theme(qapp, mode)
        palette = qapp.palette()
        allowed = {
            mode.background.lower(),
            mode.foreground.lower(),
            mode.code_background.lower(),
            mode.muted_foreground.lower(),
            mode.selection_background.lower(),
            mode.accent.lower(),
        }
        for role in (
            QPalette.ColorRole.Window,
            QPalette.ColorRole.Base,
            QPalette.ColorRole.Button,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            assert palette.color(role).name() in allowed, f"{role} が浮いている"


class TestMacOSAppearance:
    """アプリの外観そのものを macOS へ伝える（ユーザー報告）。

    `QPalette` を暗くしても、ネイティブの部品（設定のポップアップ
    ボタンなど）は **OS が明るい chrome のまま描く**。文字だけがこちらの
    明るい色になり、白地に薄いグレーで読めなくなっていた。

    パレットで塗り替えるのではなく、**アプリが暗い外観だと OS に伝える**
    のが筋。ネイティブ部品がまとめて追従する。
    """

    def test_ダークにできる(self, qapp: QApplication) -> None:
        from hitofude.app import macos_appearance, set_macos_appearance

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        assert set_macos_appearance(dark=True) is True
        assert macos_appearance() == "NSAppearanceNameDarkAqua"

    def test_ライトへ戻せる(self, qapp: QApplication) -> None:
        from hitofude.app import macos_appearance, set_macos_appearance

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")
        set_macos_appearance(dark=True)
        set_macos_appearance(dark=False)
        assert macos_appearance() == "NSAppearanceNameAqua"

    def test_macOS以外では何もしない(self, monkeypatch) -> None:
        from hitofude.app import macos_appearance, set_macos_appearance

        monkeypatch.setattr(sys, "platform", "linux")
        assert set_macos_appearance(dark=True) is False
        assert macos_appearance() is None

    def test_例外が出ても止まらない(self, monkeypatch) -> None:
        """外観が変わらないだけ。アプリを落とす理由にはならない。"""
        import ctypes.util

        from hitofude.app import set_macos_appearance

        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
        assert set_macos_appearance(dark=True) is False

    def test_テーマ設定に追従する(self, qtbot, tmp_path) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.app import macos_appearance
        from hitofude.config import Config
        from hitofude.theme import ThemeMode
        from hitofude.ui.main_window import MainWindow

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")

        settings = QSettings(str(tmp_path / "look.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "LookVault"
        config.theme_mode = ThemeMode.DARK

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert macos_appearance() == "NSAppearanceNameDarkAqua"
            window.theme_watcher.set_mode(ThemeMode.LIGHT)
            assert macos_appearance() == "NSAppearanceNameAqua"
        finally:
            window.close()


class TestFollowingTheSystem:
    """システムのダークモード切り替えに追従する（ユーザー報告 / spec §5.3）。

    **起動中は追従せず、再起動するとダークで立ち上がっていた。**

    原因は「アプリの外観を macOS へ伝える」（ADR-0006）のやりすぎ。
    Qt の `styleHints().colorScheme()` は **OS の設定ではなく NSApp の
    外観**を読む（実測）:

        起動直後      : Light | NSApp: None
        ダークに固定後: Dark  | NSApp: NSAppearanceNameDarkAqua

    起動時に外観を固定すると、以後 Qt が見るのは自分で固定した値になり、
    OS が変わっても `colorSchemeChanged` が飛ばない。再起動したときだけ、
    まだ固定していない一瞬に正しい値を読めていた。

    **「システムに合わせる」ときは固定しない**のが正しい。固定しなければ
    ネイティブ部品も OS に付いていくので、ADR-0006 の目的も損なわれない。
    """

    def test_システムに合わせるときは外観を固定しない(self, qtbot, tmp_path) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.app import macos_appearance
        from hitofude.config import Config
        from hitofude.theme import ThemeMode
        from hitofude.ui.main_window import MainWindow

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")

        settings = QSettings(str(tmp_path / "follow.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "FollowVault"
        config.theme_mode = ThemeMode.SYSTEM

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert macos_appearance() is None
        finally:
            window.close()

    def test_明示的に選んだときは固定する(self, qtbot, tmp_path) -> None:
        """OS と違う外観を選べること（ADR-0006 の本来の目的）。"""
        from PySide6.QtCore import QSettings

        from hitofude.app import macos_appearance
        from hitofude.config import Config
        from hitofude.theme import ThemeMode
        from hitofude.ui.main_window import MainWindow

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")

        settings = QSettings(str(tmp_path / "pin.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "PinVault"
        config.theme_mode = ThemeMode.DARK

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert macos_appearance() == "NSAppearanceNameDarkAqua"
            # 「システムに合わせる」へ戻したら固定を解く
            window.theme_watcher.set_mode(ThemeMode.SYSTEM)
            assert macos_appearance() is None
        finally:
            window.close()

    def test_固定を解ける(self, qapp) -> None:
        from hitofude.app import macos_appearance, set_macos_appearance

        if sys.platform != "darwin":
            pytest.skip("macOS 専用")

        set_macos_appearance(dark=True)
        assert set_macos_appearance(dark=None) is True
        assert macos_appearance() is None

    def test_OSが変わったら配色も変わる(self, qtbot, tmp_path) -> None:
        """`colorSchemeChanged` の受け口が繋がっていること。

        OS の設定そのものは動かせないので、Qt が出す合図で確かめる。
        """
        from PySide6.QtCore import QSettings, Qt

        from hitofude.config import Config
        from hitofude.theme import ThemeMode
        from hitofude.ui.main_window import MainWindow

        settings = QSettings(str(tmp_path / "signal.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "SignalVault"
        config.theme_mode = ThemeMode.SYSTEM

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            watcher = window.theme_watcher
            watcher._on_qt_scheme_changed(Qt.ColorScheme.Dark)
            assert watcher.colors.is_dark is True
            watcher._on_qt_scheme_changed(Qt.ColorScheme.Light)
            assert watcher.colors.is_dark is False
        finally:
            window.close()


class TestVaultLock:
    """vault 単位の二重起動ロック（H-1 層 2 / spec §6.1）。"""

    def test_取れたらロックを返す(self, qapp, tmp_path) -> None:
        from hitofude.app import acquire_vault_lock

        lock = acquire_vault_lock(tmp_path / ".OboeGaki")
        assert lock is not None
        lock.unlock()

    def test_二重には取れない(self, qapp, tmp_path) -> None:
        from hitofude.app import acquire_vault_lock

        first = acquire_vault_lock(tmp_path / ".OboeGaki")
        assert acquire_vault_lock(tmp_path / ".OboeGaki") is None
        first.unlock()

    def test_解放すれば取り直せる(self, qapp, tmp_path) -> None:
        from hitofude.app import acquire_vault_lock

        first = acquire_vault_lock(tmp_path / ".OboeGaki")
        first.unlock()
        second = acquire_vault_lock(tmp_path / ".OboeGaki")
        assert second is not None
        second.unlock()

    def test_vaultごとに独立している(self, qapp, tmp_path) -> None:
        """別の vault なら同時に開ける。"""
        from hitofude.app import acquire_vault_lock

        first = acquire_vault_lock(tmp_path / "a" / ".hitofude")
        second = acquire_vault_lock(tmp_path / "b" / ".hitofude")
        assert first is not None and second is not None
        first.unlock()
        second.unlock()


class TestQtJapanese:
    """Qt が出す言葉も日本語にする（ユーザー要望 2026-08-22）。

    本文の右クリックは **Qt の標準メニュー**（Undo / Cut / Paste …）で、
    アプリの言葉と混ざって英語で出ていた。翻訳のカタログ（`qtbase_ja.qm`）は
    PySide6 に同梱されているので、読み込むだけでよい。
    """

    def test_カタログが同梱されている(self) -> None:
        from pathlib import Path

        from PySide6.QtCore import QLibraryInfo

        found = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        assert (found / "qtbase_ja.qm").is_file()

    def test_本文の右クリックが日本語(self, qapp) -> None:
        """**Qt の言葉を直に読む。** 実際にメニューを作って確かめる。"""
        from PySide6.QtWidgets import QPlainTextEdit

        from hitofude.app import install_translations

        install_translations(qapp)
        editor = QPlainTextEdit()
        menu = editor.createStandardContextMenu()
        try:
            labels = [action.text() for action in menu.actions() if action.text()]
        finally:
            menu.deleteLater()
            editor.deleteLater()
        assert any("取り消す" in label or "元に戻す" in label for label in labels), labels
        assert not any(label.startswith("Undo") for label in labels), labels

    # **`(&U)` の飾りは自動では見られない。** 動作の文字列には常に入って
    # いて（実測: `元に戻す(&U)`）、macOS の cocoa が**描くときに外す**。
    # offscreen では外れないので、ここで見ると必ず落ちる。手動チェックのまま。

    def test_ダイアログのボタンも日本語(self, qapp) -> None:
        """**「はい / いいえ」も Qt の言葉。** 本文のメニューだけ直しても、
        確認のダイアログが Yes / No のままだと混ざる（手動チェックの項目）。
        """
        from PySide6.QtWidgets import QMessageBox

        from hitofude.app import install_translations

        install_translations(qapp)
        box = QMessageBox()
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        try:
            labels = [button.text() for button in box.buttons()]
        finally:
            box.deleteLater()
        assert not any(label.replace("&", "") in {"Yes", "No"} for label in labels), labels

    def test_二度読み込んでも増えない(self, qapp) -> None:
        """設定を触るたびに呼ばれても、翻訳が積み上がらない。"""
        from hitofude.app import install_translations

        first = install_translations(qapp)
        second = install_translations(qapp)
        assert first is second
