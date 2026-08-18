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
