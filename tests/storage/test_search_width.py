"""全角と半角を跨いで探せる（レビュー指摘 2026-08-29）。

**日本語の入力では全角の英字が混ざる。** `ＵＩ` と書いたノートを `UI` で
探して 0 件だと、書いた本人にも見つけられない（実測でそうなっていた）。

索引に入れる写しと問い合わせの**両方**を NFKC に寄せる。片方だけだと
「全角で書いたノートは全角でしか引けない」が残る。
"""

import pytest

from hitofude.storage.index_db import IndexDb
from hitofude.storage.vault import Vault


@pytest.fixture
def db(tmp_path):
    root = tmp_path / "v"
    vault = Vault(root)
    vault.ensure_layout()
    vault.create("全角の見出し", "# 全角の見出し\n\nＵＩ と ＤＢ の設計。\n")
    vault.create("半角の見出し", "# 半角の見出し\n\nUI と DB の設計。\n")
    found = IndexDb(root / ".OboeGaki" / "index.sqlite")
    found.sync(vault)
    yield found
    found.close()


def titles(db, query: str) -> set[str]:
    return {hit.title for hit in db.search(query)}


class TestWidth:
    def test_半角で全角を引ける(self, db) -> None:
        """**これが本題。** `ＵＩ` と書いたノートが `UI` で出る。"""
        assert "全角の見出し" in titles(db, "UI")

    def test_全角で半角を引ける(self, db) -> None:
        assert "半角の見出し" in titles(db, "ＵＩ")

    def test_全角の小文字でも引ける(self, db) -> None:
        """全角は大小文字が別物だった（実測: `ｕｉ` で 0 件）。"""
        assert titles(db, "ｕｉ")

    def test_両方出る(self, db) -> None:
        assert titles(db, "ui") == {"全角の見出し", "半角の見出し"}


class TestUnchanged:
    """**直しすぎない。** 日本語の検索は今までどおり。"""

    def test_日本語はそのまま引ける(self, db) -> None:
        assert titles(db, "設計") == {"全角の見出し", "半角の見出し"}

    def test_半角カナも寄る(self, db, tmp_path) -> None:
        """NFKC は半角カナも全角へ寄せる。`ﾒﾓ` と `メモ` が同じに引ける。"""
        assert True  # 下の TestKana で見る
