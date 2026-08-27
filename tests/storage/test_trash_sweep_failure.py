"""ゴミ箱の掃除は 1 件の不調で全部やめない（S-2）。

**同期の下では走査と `stat()` の間にファイルが消える。** iCloud /
Dropbox / 別マシンが同じ vault を触っていれば普通に起きることで、
`rglob()` が並べた時点で在っても、次の瞬間には無いことがある。

すぐ上の `sweep_temp_files` は 1 件ごとに握っている。`purge_trash` にだけ
それが無く、例外が呼び出し元（`MainWindow._prepare_vault`）まで抜けて
**「保管フォルダを開けない」に化けていた**。
"""

import time
from pathlib import Path

import pytest

from hitofude.storage.vault import Vault


@pytest.fixture
def vault(tmp_path):
    found = Vault(tmp_path / "vault")
    found.ensure_layout()
    return found


def old_trash(vault: Vault, name: str) -> Path:
    """期限を過ぎたゴミ箱の中身を 1 つ置く。"""
    path = vault.trash_dir / name
    path.write_text("x", encoding="utf-8")
    stamp = time.time() - 90 * 86400
    import os

    os.utime(path, (stamp, stamp))
    return path


class TestVanishing:
    """走査の直後に消える 1 件。"""

    @pytest.fixture
    def vanishing(self, vault, monkeypatch):
        """`同期中.md` が **`is_file()` を通った直後に**消える。

        **1 回目は通す。** `is_file()` は内部で `stat()` を呼び、失敗を
        飲んで False を返す——最初から失敗させると「無かった」ことに
        なって、本物の競合にならない。在ると見えてから消えるのが実際の
        並びで、そこで初めて `purge_trash` の裸の `stat()` に当たる。
        """
        old_trash(vault, "同期中.md")
        old_trash(vault, "古いゴミ.md")
        real = Path.stat
        seen: set[str] = set()

        def flaky(self, **kwargs):
            if self.name == "同期中.md":
                if self.name in seen:
                    raise FileNotFoundError(2, "No such file or directory", str(self))
                seen.add(self.name)
            return real(self, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky)
        return vault

    def test_例外を上げない(self, vanishing) -> None:
        """**これが本題。** 1 件の不調で掃除ごと投げ出さない。"""
        vanishing.purge_trash(30)

    def test_残りは消える(self, vanishing) -> None:
        """諦めるのは消えた 1 件だけ。"""
        removed = vanishing.purge_trash(30)
        assert [p.name for p in removed] == ["古いゴミ.md"]


class TestStillWorks:
    """ふだんの掃除は今までどおり。"""

    def test_古いものは消える(self, vault) -> None:
        old_trash(vault, "古いゴミ.md")
        removed = vault.purge_trash(30)
        assert [p.name for p in removed] == ["古いゴミ.md"]
        assert not (vault.trash_dir / "古いゴミ.md").exists()

    def test_新しいものは残る(self, vault) -> None:
        fresh = vault.trash_dir / "きのうのゴミ.md"
        fresh.write_text("x", encoding="utf-8")
        assert vault.purge_trash(30) == []
        assert fresh.exists()
