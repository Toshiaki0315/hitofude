"""索引の `links` とバックリンク（E-6 ②）。

「このノートを指しているのは誰か」を引くための土台。R9 のとおり
**捨ててよいキャッシュ**で、`.md` から再構築できることが条件。
"""

from pathlib import Path

import pytest

from hitofude.core.document import Note
from hitofude.storage.index_db import SCHEMA_VERSION, IndexDb
from hitofude.storage.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    target = Vault(tmp_path / "HitofudeNotes")
    target.ensure_layout()
    return target


@pytest.fixture
def db(vault: Vault) -> IndexDb:
    with IndexDb(vault.managed_dir / "index.sqlite") as found:
        yield found


def add(vault: Vault, db: IndexDb, title: str, body: str = "") -> Note:
    note = vault.create(title, f"# {title}\n\n{body}")
    db.upsert_note(note, vault.root)
    return note


class TestBacklinks:
    def test_指しているノートが出る(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "詳しくは [[会議メモ]] を見て\n")
        assert [row.title for row in db.backlinks("会議メモ")] == ["日報"]

    def test_指されていなければ空(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        assert db.backlinks("会議メモ") == []

    def test_複数から指される(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "[[会議メモ]]\n")
        add(vault, db, "週報", "[[会議メモ]]\n")
        assert {row.title for row in db.backlinks("会議メモ")} == {"日報", "週報"}

    def test_同じノートは1回だけ出る(self, vault, db) -> None:
        """3 回指しても繋がりは 1 本。一覧に 3 行出ては読めない。"""
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "[[会議メモ]] と [[会議メモ]]\n[[会議メモ]]\n")
        assert len(db.backlinks("会議メモ")) == 1

    def test_大小を無視して繋がる(self, vault, db) -> None:
        add(vault, db, "Weekly Report")
        add(vault, db, "日報", "[[weekly report]]\n")
        assert len(db.backlinks("Weekly Report")) == 1

    def test_前後の空白を無視して繋がる(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "[[ 会議メモ ]]\n")
        assert len(db.backlinks("会議メモ")) == 1

    def test_まだ無いノートも数えられる(self, vault, db) -> None:
        """リンクは**書いた時点で記録する**。行き先の有無は問わない。"""
        add(vault, db, "日報", "[[まだ無いノート]]\n")
        assert [row.title for row in db.backlinks("まだ無いノート")] == ["日報"]

    def test_コードの中は数えない(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "```\n[[会議メモ]]\n```\n")
        assert db.backlinks("会議メモ") == []

    def test_空の名前では引かない(self, vault, db) -> None:
        add(vault, db, "日報", "[[会議メモ]]\n")
        assert db.backlinks("   ") == []


class TestKeepingUp:
    """索引はファイルに追いつくこと。古い繋がりを残さない。"""

    def test_リンクを消すと繋がりも消える(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        note = add(vault, db, "日報", "[[会議メモ]]\n")

        vault.write(note.path, "# 日報\n\nもう指していない\n")
        db.upsert_note(vault.read(note.path), vault.root)
        assert db.backlinks("会議メモ") == []

    def test_ノートを消すと繋がりも消える(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        note = add(vault, db, "日報", "[[会議メモ]]\n")

        db.remove_path(vault.root, note.path)
        assert db.backlinks("会議メモ") == []

    def test_ゴミ箱のノートは出さない(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        note = add(vault, db, "日報", "[[会議メモ]]\n")
        db.upsert_note(note, vault.root, trashed=True)
        assert db.backlinks("会議メモ") == []

    def test_走査で作り直せる(self, vault, db) -> None:
        """R9: 索引を消しても `.md` から戻る。"""
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "[[会議メモ]]\n")

        db.reset()
        assert db.backlinks("会議メモ") == []
        db.sync(vault)
        assert [row.title for row in db.backlinks("会議メモ")] == ["日報"]


class TestSchemaVersion:
    """`links` は途中で増えた表。**古い索引は作り直す。**

    表だけ足しても、既にあるノートは触られるまで走査されない
    （`sync()` は mtime を見る）。繋がりが黙って空のままになる。
    """

    def test_版が記録される(self, db) -> None:
        assert db.schema_version() == SCHEMA_VERSION

    def test_古い索引は空にして作り直す(self, vault, db) -> None:
        add(vault, db, "会議メモ")
        add(vault, db, "日報", "[[会議メモ]]\n")
        path = db.path
        db._connection.execute("PRAGMA user_version = 1")
        db._connection.commit()
        db.close()

        with IndexDb(path) as reopened:
            assert reopened.notes() == []
            assert reopened.schema_version() == SCHEMA_VERSION
            reopened.sync(vault)
            assert [row.title for row in reopened.backlinks("会議メモ")] == ["日報"]
