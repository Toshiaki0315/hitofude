"""名前の張り替えに伴う引っ越し（Hitofude → OboeGaki。2026-08-27）。

**初回だけ・一方向・改名 1 回**。索引は捨ててよいが、
`.hitofude/history/` の版は作り直せない（ADR-0023）ので必ず連れて行く。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config, migrate_legacy_settings
from hitofude.storage import autosave
from hitofude.storage.vault import Vault


def make_settings(tmp_path: Path, name: str) -> QSettings:
    return QSettings(str(tmp_path / f"{name}.ini"), QSettings.Format.IniFormat)


class TestSettingsMigration:
    def test_空なら旧設定を写す(self, tmp_path) -> None:
        legacy = make_settings(tmp_path, "old")
        legacy.setValue("editor/point_size", 18)
        legacy.setValue("vault/path", "/tmp/notes")
        legacy.sync()
        settings = make_settings(tmp_path, "new")

        assert migrate_legacy_settings(settings, legacy) is True
        assert settings.value("editor/point_size") == 18
        assert settings.value("vault/path") == "/tmp/notes"

    def test_新しい側に何かあれば触らない(self, tmp_path) -> None:
        """引っ越しは初回だけ。以後は新しい側が正。"""
        legacy = make_settings(tmp_path, "old")
        legacy.setValue("editor/point_size", 18)
        legacy.sync()
        settings = make_settings(tmp_path, "new")
        settings.setValue("editor/point_size", 22)
        settings.sync()

        assert migrate_legacy_settings(settings, legacy) is False
        assert settings.value("editor/point_size") == 22

    def test_旧が無ければ何もしない(self, tmp_path) -> None:
        settings = make_settings(tmp_path, "new")
        assert migrate_legacy_settings(settings, make_settings(tmp_path, "old")) is False
        assert settings.allKeys() == []


class TestManagedDirMigration:
    def test_旧メタデータを改名して引き継ぐ(self, tmp_path) -> None:
        """履歴（ADR-0023）は作り直せない。中身ごと連れて行く。"""
        root = tmp_path / "Notes"
        (root / ".hitofude" / "history").mkdir(parents=True)
        (root / ".hitofude" / "history" / "a.md").write_text("v1", encoding="utf-8")

        vault = Vault(root)
        vault.ensure_layout()

        assert not (root / ".hitofude").exists()
        assert (root / ".OboeGaki" / "history" / "a.md").read_text(encoding="utf-8") == "v1"

    def test_両方あれば新しい側を使う(self, tmp_path) -> None:
        """新しい側を上書きしない（引っ越し済みの正を守る）。"""
        root = tmp_path / "Notes"
        (root / ".hitofude").mkdir(parents=True)
        (root / ".OboeGaki").mkdir(parents=True)
        (root / ".OboeGaki" / "x").write_text("new", encoding="utf-8")

        Vault(root).ensure_layout()

        assert (root / ".OboeGaki" / "x").read_text(encoding="utf-8") == "new"
        assert (root / ".hitofude").exists()  # 触らない（手で消せる）

    def test_旧が無ければ新しく作る(self, tmp_path) -> None:
        root = tmp_path / "Notes"
        Vault(root).ensure_layout()
        assert (root / ".OboeGaki").is_dir()


class TestRecoveryMigration:
    def test_退避の置き場も改名して引き継ぐ(self, tmp_path) -> None:
        old = tmp_path / "Library" / "Application Support" / "Hitofude"
        (old / "recovery").mkdir(parents=True)
        (old / "recovery" / "k").mkdir()

        found = autosave.recovery_root(Path("/v"), home=tmp_path)

        base = tmp_path / "Library" / "Application Support" / "OboeGaki"
        assert base.is_dir()
        assert not old.exists()
        assert str(found).startswith(str(base))


class TestDefaultVaultMigration:
    """既定の保管フォルダで使っていた人（パス未保存）を置き去りにしない。

    既定名が HitofudeNotes → OboeGakiNotes に変わった。パスを保存して
    いない既定値運用のユーザー（実機で確認——このマシンがそう）は、
    そのままだと空の新フォルダが作られ、既存ノートが見えなくなる。
    **旧の既定フォルダが在れば使い続ける**（フォルダは動かさない）。
    """

    def make_config(self, tmp_path: Path) -> Config:
        settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        return Config(settings, home=tmp_path)

    def test_旧の既定フォルダがあれば使い続ける(self, tmp_path) -> None:
        (tmp_path / "Documents" / "HitofudeNotes").mkdir(parents=True)
        config = self.make_config(tmp_path)
        assert config.vault_path == tmp_path / "Documents" / "HitofudeNotes"

    def test_無ければ新しい既定(self, tmp_path) -> None:
        config = self.make_config(tmp_path)
        assert config.vault_path == tmp_path / "Documents" / "OboeGakiNotes"

    def test_保存されたパスが最優先(self, tmp_path) -> None:
        (tmp_path / "Documents" / "HitofudeNotes").mkdir(parents=True)
        config = self.make_config(tmp_path)
        config.vault_path = tmp_path / "MyNotes"
        assert config.vault_path == tmp_path / "MyNotes"

    def test_新しい既定が既にあればそちら(self, tmp_path) -> None:
        """引っ越し済み（手で改名した等）の人を旧へ引き戻さない。"""
        (tmp_path / "Documents" / "HitofudeNotes").mkdir(parents=True)
        (tmp_path / "Documents" / "OboeGakiNotes").mkdir(parents=True)
        config = self.make_config(tmp_path)
        assert config.vault_path == tmp_path / "Documents" / "OboeGakiNotes"


class TestLockBeforeLayout:
    """起動の実順序（ロック → ensure_layout）でも履歴が移る（実機で発覚）。

    ロック（app.acquire_vault_lock）は ensure_layout より先に管理フォルダを
    作る。先に新フォルダができると「両方あるので触らない」に入り、
    履歴が旧側に取り残されていた。
    """

    def test_ロックが先でも履歴は移る(self, tmp_path) -> None:
        from hitofude.app import acquire_vault_lock

        root = tmp_path / "Notes"
        (root / ".hitofude" / "history").mkdir(parents=True)
        (root / ".hitofude" / "history" / "keep.md").write_text("v1", encoding="utf-8")

        vault = Vault(root)
        lock = acquire_vault_lock(vault.managed_dir)
        assert lock is not None
        vault.ensure_layout()

        found = root / ".OboeGaki" / "history" / "keep.md"
        assert found.read_text(encoding="utf-8") == "v1"


class TestCannotMove:
    """**動かせなくても起動は止めない**（S-4 / ADR-0030 と同じ考え）。

    `recovery_root()` は名前のとおり「場所を返す」顔をしているが、
    改名（ADR-0032）でファイルシステムを書き換えるようになった。
    `MainWindow` の組み立て（`SaveController`）から呼ばれるので、
    ここで例外が抜けると**窓が 1 つも出ない**（実測）。

    置き場を動かせなくても、**旧い置き場はそのまま使える**——
    クラッシュ直後に読み出したい版はそこにある。
    """

    @pytest.fixture
    def stuck(self, tmp_path):
        import os
        import stat

        if os.geteuid() == 0:
            pytest.skip("root は許可を無視して動かせてしまう")

        support = tmp_path / "Library" / "Application Support"
        old = support / "Hitofude" / "recovery" / "k"
        old.mkdir(parents=True)
        support.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x。改名できない
        yield tmp_path
        support.chmod(stat.S_IRWXU)

    def test_例外を上げない(self, stuck) -> None:
        """**これが本題。** ここで抜けると窓が出ない。"""
        autosave.recovery_root(Path("/v"), home=stuck)

    def test_旧い置き場を使い続ける(self, stuck) -> None:
        """動かせなくても、そこにある版は読める。"""
        found = autosave.recovery_root(Path("/v"), home=stuck)
        legacy = stuck / "Library" / "Application Support" / "Hitofude"
        assert str(found).startswith(str(legacy))


class TestUnreadableRecovery:
    """退避の置き場が読めなくても起動する（S-4）。

    `pending()` は `MainWindow.__init__` から `offer_recovery()` 経由で
    呼ばれる。`Path.is_dir()` は 3.13 で**許可エラーを飲まない**ので、
    置き場に立ち入れないと例外が抜けて**窓が 1 つも出ない**。

    退避が読めないのは我慢できる（前回のクラッシュぶんを諦めるだけ）。
    起動しないのは我慢できない（ADR-0030）。
    """

    @pytest.fixture
    def unreadable(self, tmp_path):
        import os
        import stat

        if os.geteuid() == 0:
            pytest.skip("root は許可を無視して読めてしまう")

        root = tmp_path / "recovery" / "k"
        root.mkdir(parents=True)
        root.parent.chmod(stat.S_IRUSR)  # r--。中へ立ち入れない
        yield root
        root.parent.chmod(stat.S_IRWXU)

    def test_例外を上げない(self, unreadable) -> None:
        assert autosave.pending(unreadable) == []
