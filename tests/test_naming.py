"""アプリ名の張り替え（Hitofude → 覚書 / OboeGaki。ユーザー決定 2026-08-27）。

表示名は「覚書」、ファイル名・フォルダ名系は「OboeGaki」。
名前は散らばるので、**決めた形をここで固定**する。
"""

from hitofude import APP_NAME, LEGACY_ORG_DOMAIN, ORG_DOMAIN, ORG_NAME
from hitofude.config import DEFAULT_VAULT_NAME
from hitofude.storage.autosave import APP_SUPPORT_NAME
from hitofude.storage.vault import LEGACY_MANAGED_DIR, MANAGED_DIR, MANUAL_TITLE
from tests.test_packaging import PROJECT_ROOT, _setup_options


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


class TestLiteBundle:
    """軽量版は `OboeGakiLite.app`（ユーザー要望 2026-08-28）。

    **ファイル名を変えるだけでは足りない。** Finder が並べるのは
    `CFBundleDisplayName` なので、そこが「覚書」のままだと**どちらの
    `.app` も同じ名前に見える**——区別を付けたいという目的を果たさない。

    **バンドル ID は変えない。** 分けると QSettings の保存先も分かれ、
    軽量版で起動したときに設定も保管フォルダの記憶も別物になる。
    これは「同じアプリの軽い作り」であって、別のアプリではない。
    """

    def names(self, *, lite: bool):
        import importlib
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            module = importlib.import_module("setup")
            return module.bundle_names(lite=lite)
        finally:
            sys.path.remove(str(PROJECT_ROOT))

    def test_通常版は今までどおり(self) -> None:
        assert self.names(lite=False) == ("OboeGaki", "覚書")

    def test_軽量版はLiteが付く(self) -> None:
        assert self.names(lite=True)[0] == "OboeGakiLite"

    def test_Finderでも見分けが付く(self) -> None:
        """**表示名も変える。** 同じだと Finder では区別できない。"""
        assert self.names(lite=False)[1] == APP_NAME
        assert self.names(lite=True)[1] == "覚書Lite"

    def test_絵も分ける(self) -> None:
        """軽量版は右下に小さく `Lite` が入った `.icns`（ユーザー要望）。"""
        import importlib
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            module = importlib.import_module("setup")
            assert module.icon_file(lite=False).name == "OboeGaki.icns"
            assert module.icon_file(lite=True).name == "OboeGakiLite.icns"
        finally:
            sys.path.remove(str(PROJECT_ROOT))

    def test_絵が両方そろっている(self) -> None:
        """**片方だけ古いまま配らない。** `make icon` は 2 つとも作る。"""
        resources = PROJECT_ROOT / "resources"
        assert (resources / "OboeGaki.icns").is_file()
        assert (resources / "OboeGakiLite.icns").is_file()

    def test_バンドルIDは分けない(self) -> None:
        """設定と保管フォルダの記憶を分断しない。"""
        options = _setup_options()["OPTIONS"]
        assert options["plist"]["CFBundleIdentifier"] == ORG_DOMAIN


class TestBundledManual:
    """同梱の使い方ノートに旧名を残さない（ユーザー指摘 2026-08-28）。

    **中身は目視でしか気づけない。** 題名（`MANUAL_TITLE`）は定数なので
    改名で直ったが、本文は文章なので取り残される。実際 `.hitofude` を
    消してよいと案内したままで、**いまは存在しないフォルダ**を指していた。
    """

    def manual(self) -> str:
        from importlib.resources import files

        return (files("hitofude.resources") / "manual.md").read_text(encoding="utf-8")

    def test_題名が今の名前(self) -> None:
        assert self.manual().splitlines()[0] == f"# {MANUAL_TITLE}"

    def test_管理フォルダの名前が今のもの(self) -> None:
        text = self.manual()
        assert LEGACY_MANAGED_DIR not in text
        assert MANAGED_DIR in text, "管理フォルダの説明そのものが消えている"

    def test_旧名を書かない(self) -> None:
        slips = [line for line in self.manual().splitlines() if "itofude" in line]
        assert slips == [], f"旧名が残っている: {slips}"
