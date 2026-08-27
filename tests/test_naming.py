"""アプリ名の張り替え（Hitofude → 覚書 / OboeGaki。ユーザー決定 2026-08-27）。

表示名は「覚書」、ファイル名・フォルダ名系は「OboeGaki」。
名前は散らばるので、**決めた形をここで固定**する。
"""

from hitofude import APP_NAME, LEGACY_ORG_DOMAIN, ORG_DOMAIN, ORG_NAME
from hitofude.config import DEFAULT_VAULT_NAME
from hitofude.storage.autosave import APP_SUPPORT_NAME
from hitofude.storage.vault import LEGACY_MANAGED_DIR, MANAGED_DIR, MANUAL_TITLE
from tests.test_packaging import _setup_options


class TestNames:
    def test_表示名は覚書(self) -> None:
        assert APP_NAME == "覚書"

    def test_ファイル名とフォルダ名はOboeGaki(self) -> None:
        assert ORG_NAME == "OboeGaki"
        assert DEFAULT_VAULT_NAME == "OboeGakiNotes"
        assert MANAGED_DIR == ".OboeGaki"
        assert APP_SUPPORT_NAME == "OboeGaki"

    def test_使い方のノートも新しい名前(self) -> None:
        assert MANUAL_TITLE == "覚書の使い方"

    def test_旧名は引っ越し用に残る(self) -> None:
        assert LEGACY_MANAGED_DIR == ".hitofude"
        assert LEGACY_ORG_DOMAIN == "app.hitofude.editor"

    def test_バンドルIDと設定の保存先が揃う(self) -> None:
        """ずれると QSettings が Info.plist と別の場所に書く。"""
        assert ORG_DOMAIN == "app.oboegaki.editor"
        options = _setup_options()["OPTIONS"]
        assert options["plist"]["CFBundleIdentifier"] == ORG_DOMAIN
        assert options["plist"]["CFBundleName"] == "OboeGaki"
        assert options["plist"]["CFBundleDisplayName"] == APP_NAME
