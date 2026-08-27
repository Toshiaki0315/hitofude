"""エントリポイントの結線（H-1 層 2）。

二重起動の検出はここが唯一の入口。ウィンドウとイベントループは
差し替えて、ロックの取り回しだけを見る。
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

import hitofude.__main__ as entry
from hitofude.app import acquire_vault_lock
from hitofude.config import Config
from hitofude.storage.vault import Vault

pytestmark = pytest.mark.gui


class FakeWindow:
    """MainWindow の代役。作られたことと show() だけ覚える。"""

    instances: "list[FakeWindow]" = []  # noqa: RUF012  テストごとに fixture で入れ替える

    def __init__(self, config: Config | None = None) -> None:
        self.config = config
        self.shown = False
        type(self).instances.append(self)

    def show(self) -> None:
        self.shown = True


@pytest.fixture
def stubbed(monkeypatch, qapp):
    """ウィンドウとイベントループを差し替える。

    `exec` は**インスタンス側**に差し込む（test_entrypoint.py と同じ作法）。
    クラス側への差し替えは、先行テストがインスタンス側を差し替えて戻した
    後だと効かないことがある（実際に全体実行でだけハングした）。
    """
    FakeWindow.instances = []
    monkeypatch.setattr(entry, "MainWindow", FakeWindow)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    return FakeWindow


@pytest.fixture
def managed_dir() -> Path:
    return Vault(Config().vault_path).managed_dir


class TestSingleInstance:
    def test_二重起動なら窓を作らずに知らせて終わる(
        self, stubbed, managed_dir, monkeypatch
    ) -> None:
        notices: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox, "information", staticmethod(lambda *a, **k: notices.append(a))
        )
        holder = acquire_vault_lock(managed_dir)  # 1 個目のアプリの代役
        assert holder is not None
        try:
            assert entry.main([]) == 0
        finally:
            holder.unlock()

        assert notices, "知らせが出ていない"
        assert stubbed.instances == []  # ウィンドウは作らない

    def test_通常起動は窓を開きロックを持つ(self, stubbed, managed_dir) -> None:
        assert entry.main([]) == 0
        assert len(stubbed.instances) == 1
        assert stubbed.instances[0].shown is True

    def test_終了後はロックが解放されている(self, stubbed, managed_dir) -> None:
        entry.main([])
        again = acquire_vault_lock(managed_dir)
        assert again is not None  # 解放されていなければ取れない
        again.unlock()


class TestLockedVault:
    """保管フォルダを開けなくても起動する（ADR-0030 / S-1）。

    **`MainWindow` だけ守っても足りない。** ADR-0030 の「起動しないのは
    我慢できない」は `tests/ui/test_locked_vault.py` が担保していたが、
    そこが見ているのは窓の組み立てだけで、**実際の入口はその手前**に
    ある。macOS が書類フォルダへの立ち入りを尋ねて断られると、ロックを
    置きにいった時点で `PermissionError` が抜け、窓に辿り着かない
    （`.app` では何も出ずに終わる）。

    ロックを置けないなら**守るものが無い**——中を読み書きできないの
    だから、二重に開いても壊れるものがない。窓を出して設定へ辿り着かせる。
    """

    @pytest.fixture
    def locked(self):
        """中身のある保管フォルダを**読めなく**する。"""
        import os
        import stat

        if os.geteuid() == 0:
            pytest.skip("root は許可を無視して読めてしまう")

        root = Config().vault_path
        root.mkdir(parents=True, exist_ok=True)
        (root / "会議メモ.md").write_text("# 会議メモ\n\n本文\n", encoding="utf-8")
        (root / ".hitofude").mkdir(exist_ok=True)  # 旧名（改名の引っ越し対象）
        root.chmod(0o000)
        yield root
        root.chmod(stat.S_IRWXU)

    @pytest.fixture
    def silent(self, monkeypatch):
        """知らせを黙らせ、**出たことを記録する**。

        塞がないと退行のときにモーダルが開いて**テスト一式が止まる**
        （Q-4 と同じ罠）。落ちるべきところは落ちて終わらせる。
        """
        notices: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox, "information", staticmethod(lambda *a, **k: notices.append(a))
        )
        return notices

    def test_窓は出る(self, stubbed, locked, silent) -> None:
        """**これが本題。** 落ちずに窓まで辿り着く。"""
        assert entry.main([]) == 0
        assert len(stubbed.instances) == 1
        assert stubbed.instances[0].shown is True

    def test_二重起動だと嘘をつかない(self, stubbed, locked, silent) -> None:
        """ロックを置けないのは、誰かが開いているのとは別のこと。"""
        entry.main([])
        assert silent == [], "開いていないのに「別のウィンドウで開いています」と出た"

    def test_ロックの代わりを返す(self, locked) -> None:
        """`None`（＝他の窓が持っている）と区別が付くこと。"""
        lock = acquire_vault_lock(Vault(locked).managed_dir)
        assert lock is not None
        lock.unlock()  # 後始末は呼べる（`main` の finally が呼ぶ）

    @pytest.fixture
    def readonly_managed(self):
        """管理フォルダは在るが**書けない**（読み取り専用の場所に置いた等）。"""
        import os
        import stat

        if os.geteuid() == 0:
            pytest.skip("root は許可を無視して書けてしまう")

        managed = Vault(Config().vault_path).managed_dir
        managed.mkdir(parents=True, exist_ok=True)
        managed.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x。錠前を置けない
        yield managed
        managed.chmod(stat.S_IRWXU)

    def test_置けないだけなら二重起動ではない(self, readonly_managed) -> None:
        """`tryLock` の失敗を**理由で見分ける**。

        フォルダは在るので `mkdir` は通る。錠前を置けないのは書けないから
        であって、**誰かが持っているからではない**。`None` を返すと
        「別のウィンドウで開いています」と嘘をつき、そこで終わってしまう。
        """
        lock = acquire_vault_lock(readonly_managed)
        assert lock is not None, "書けないだけなのに二重起動として扱った"
        lock.unlock()
