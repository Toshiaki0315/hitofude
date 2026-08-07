"""検索インデックスのテスト（タスク 4-5〜4-7 / spec §7.3, R9）。

日本語検索が成立するかがこの層の存在意義。trigram の 3 文字制約と、
そこから漏れる 2 文字クエリの扱いを重点的に見る。
"""

from pathlib import Path

import pytest

from hitofude.core.document import Note
from hitofude.storage.index_db import IndexDb, rebuild
from hitofude.storage.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    target = Vault(tmp_path / "HitofudeNotes")
    target.ensure_layout()
    return target


@pytest.fixture
def db(vault: Vault) -> IndexDb:
    with IndexDb(vault.managed_dir / "index.sqlite") as database:
        yield database


def add(vault: Vault, db: IndexDb, title: str, body: str = "") -> Note:
    note = vault.create(title, f"# {title}\n\n{body}\n")
    db.upsert_note(note, vault.root)
    return note


class TestSchema:
    def test_ファイルが作られる(self, db, vault) -> None:
        assert (vault.managed_dir / "index.sqlite").is_file()

    def test_WALモードになっている(self, db) -> None:
        """spec §7.3: 読み書きの並行性のため。"""
        mode = db._connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_二度開いても壊れない(self, vault) -> None:
        path = vault.managed_dir / "index.sqlite"
        with IndexDb(path):
            pass
        with IndexDb(path) as db:
            assert db.notes() == []


class TestUpsert:
    def test_ノートが入る(self, db, vault) -> None:
        add(vault, db, "会議メモ", "本文です")
        rows = db.notes()
        assert len(rows) == 1
        assert rows[0].title == "会議メモ"

    def test_同じノートを入れ直しても増えない(self, db, vault) -> None:
        note = add(vault, db, "会議メモ")
        db.upsert_note(note, vault.root)
        db.upsert_note(note, vault.root)
        assert len(db.notes()) == 1

    def test_パスは相対で持つ(self, db, vault) -> None:
        """vault ごと移動しても索引が無効にならないように。"""
        add(vault, db, "会議メモ")
        assert db.notes()[0].path == Path("会議メモ.md")

    def test_front_matterが無いノートも入る(self, db, vault) -> None:
        """外部エディタで作られたノートには id が無い。"""
        path = vault.root / "外部.md"
        path.write_text("# 外部で作った\n\n本文\n", encoding="utf-8")
        db.upsert_note(Note.read(path), vault.root)
        assert db.notes()[0].title == "外部で作った"

    def test_ピン留めが反映される(self, db, vault) -> None:
        path = vault.root / "重要.md"
        path.write_text("---\npinned: true\n---\n# 重要\n", encoding="utf-8")
        db.upsert_note(Note.read(path), vault.root)
        assert db.notes()[0].pinned is True

    def test_ピン留めが先頭に来る(self, db, vault) -> None:
        add(vault, db, "普通のメモ")
        path = vault.root / "重要.md"
        path.write_text("---\npinned: true\n---\n# 重要\n", encoding="utf-8")
        db.upsert_note(Note.read(path), vault.root)
        assert db.notes()[0].title == "重要"

    def test_ゴミ箱のノートは既定で出ない(self, db, vault) -> None:
        note = add(vault, db, "消したメモ")
        db.upsert_note(note, vault.root, trashed=True)
        assert db.notes() == []
        assert len(db.notes(include_trashed=True)) == 1


class TestRemove:
    def test_パスを指定して消せる(self, db, vault) -> None:
        note = add(vault, db, "会議メモ")
        db.remove_path(vault.root, note.path)
        assert db.notes() == []

    def test_無い行を消しても壊れない(self, db, vault) -> None:
        db.remove_path(vault.root, vault.root / "存在しない.md")
        assert db.notes() == []

    def test_消すと検索にも出なくなる(self, db, vault) -> None:
        note = add(vault, db, "会議メモ", "特徴的な文字列")
        db.remove_path(vault.root, note.path)
        assert db.search("特徴的な文字列") == []


class TestTags:
    def test_タグを取り出せる(self, db, vault) -> None:
        add(vault, db, "メモ", "本文 #work")
        assert [t.tag for t in db.tag_tree()] == ["work"]

    def test_階層タグは祖先も数える(self, db, vault) -> None:
        """spec §5.1 のサイドバーは親ノードにも件数を出す。"""
        add(vault, db, "メモ", "本文 #work/会議")
        counts = {t.tag: t.count for t in db.tag_tree()}
        assert counts == {"work": 1, "work/会議": 1}

    def test_親の件数は子を合算する(self, db, vault) -> None:
        add(vault, db, "会議のメモ", "本文 #work/会議")
        add(vault, db, "企画のメモ", "本文 #work/企画")
        counts = {t.tag: t.count for t in db.tag_tree()}
        assert counts["work"] == 2
        assert counts["work/会議"] == 1

    def test_タグで絞り込める(self, db, vault) -> None:
        add(vault, db, "仕事のメモ", "本文 #work")
        add(vault, db, "私用のメモ", "本文 #private")
        assert [r.title for r in db.notes_with_tag("work")] == ["仕事のメモ"]

    def test_親タグで子のノートも引ける(self, db, vault) -> None:
        add(vault, db, "会議のメモ", "本文 #work/会議")
        assert [r.title for r in db.notes_with_tag("work")] == ["会議のメモ"]

    def test_タグを消したら索引からも消える(self, db, vault) -> None:
        note = add(vault, db, "メモ", "本文 #work")
        vault.write(note.path, "# メモ\n\nタグを消した本文\n")
        db.upsert_note(Note.read(note.path), vault.root)
        assert db.tag_tree() == []

    def test_ラベルは末端の名前(self, db, vault) -> None:
        add(vault, db, "メモ", "本文 #work/会議")
        labels = {t.tag: t.label for t in db.tag_tree()}
        assert labels["work/会議"] == "会議"


class TestSearch:
    def test_3文字以上の日本語を引ける(self, db, vault) -> None:
        """trigram の本領。形態素解析なしで部分一致する。"""
        add(vault, db, "会議メモ", "来期の予算について話した")
        assert [h.title for h in db.search("予算について")] == ["会議メモ"]

    def test_単語の途中からでも引ける(self, db, vault) -> None:
        add(vault, db, "会議メモ", "来期の予算について話した")
        assert len(db.search("期の予算")) == 1

    def test_英数字も引ける(self, db, vault) -> None:
        add(vault, db, "技術メモ", "PySide6 を使う")
        assert len(db.search("PySide6")) == 1

    def test_2文字の日本語も引ける(self, db, vault) -> None:
        """spec §7.3 / R5: trigram では引けないので LIKE に落とす。

        「人事」「経費」のような 2 文字語は日常的に検索される。
        ここが空振りすると検索が使い物にならない。
        """
        add(vault, db, "人事の件", "本文")
        assert [h.title for h in db.search("人事")] == ["人事の件"]

    def test_2文字検索はプレビューにも当たる(self, db, vault) -> None:
        add(vault, db, "打ち合わせ", "経費の精算について")
        assert len(db.search("経費")) == 1

    def test_一致しなければ空(self, db, vault) -> None:
        add(vault, db, "会議メモ", "本文")
        assert db.search("存在しない語") == []

    def test_空のクエリは空(self, db, vault) -> None:
        add(vault, db, "会議メモ")
        assert db.search("") == []
        assert db.search("   ") == []

    @pytest.mark.parametrize("query", ['"', "AND", "OR", "*", "a*b", "NEAR(", "^", "-"])
    def test_記号を打っても落ちない(self, db, vault, query: str) -> None:
        """FTS5 の演算子をユーザーが打つと構文エラーになる。引用符で囲んで防ぐ。"""
        add(vault, db, "会議メモ", "本文")
        db.search(query)  # 例外が出ないこと

    def test_ゴミ箱のノートは出ない(self, db, vault) -> None:
        note = add(vault, db, "消したメモ", "特徴的な文字列")
        db.upsert_note(note, vault.root, trashed=True)
        assert db.search("特徴的な文字列") == []

    def test_スニペットが返る(self, db, vault) -> None:
        add(vault, db, "会議メモ", "来期の予算について話した")
        assert db.search("予算について")[0].snippet


class TestSync:
    """spec §7.3 の起動時同期。差分だけを取り込む。"""

    def test_新規を取り込む(self, db, vault) -> None:
        vault.create("メモ1")
        vault.create("メモ2")
        result = db.sync(vault)
        assert len(result.added) == 2
        assert len(db.notes()) == 2

    def test_変更が無ければ何もしない(self, db, vault) -> None:
        vault.create("メモ")
        db.sync(vault)
        result = db.sync(vault)
        assert result.changed == 0

    def test_更新を取り込む(self, db, vault) -> None:
        note = vault.create("メモ")
        db.sync(vault)
        vault.write(note.path, "# メモ\n\n書き換えた\n")
        result = db.sync(vault)
        assert result.updated == [note.path]

    def test_消えたノートを索引から外す(self, db, vault) -> None:
        note = vault.create("メモ")
        db.sync(vault)
        note.path.unlink()
        result = db.sync(vault)
        assert result.removed == [note.path]
        assert db.notes() == []

    def test_ゴミ箱へ移すと索引から外れる(self, db, vault) -> None:
        note = vault.create("メモ")
        db.sync(vault)
        vault.trash(note.path)
        db.sync(vault)
        assert db.notes() == []

    def test_触っていないファイルは開かない(self, db, vault, monkeypatch) -> None:
        """5,000 ノートで全件読み直すと起動が数秒かかる（§7.3）。"""
        vault.create("メモ")
        db.sync(vault)

        opened: list[Path] = []
        original = Note.read

        def spy(path: Path) -> Note:
            opened.append(path)
            return original(path)

        monkeypatch.setattr(Note, "read", staticmethod(spy))
        db.sync(vault)
        assert opened == []


class TestRebuild:
    """R9 / spec §7.1: 索引は捨ててよいキャッシュ。"""

    def test_消しても完全に復元できる(self, vault) -> None:
        db_path = vault.managed_dir / "index.sqlite"
        with IndexDb(db_path) as db:
            vault.create("会議メモ", "# 会議メモ\n\n予算について #work/会議\n")
            vault.create("読書メモ", "# 読書メモ\n\n第3章まで #private\n")
            db.sync(vault)
            before_notes = [(r.title, r.path) for r in db.notes()]
            before_tags = {t.tag: t.count for t in db.tag_tree()}

        db_path.unlink()
        assert not db_path.exists()

        rebuild(db_path, vault)
        with IndexDb(db_path) as db:
            assert [(r.title, r.path) for r in db.notes()] == before_notes
            assert {t.tag: t.count for t in db.tag_tree()} == before_tags
            assert len(db.search("予算について")) == 1


@pytest.mark.slow
class TestPerformance:
    """spec §6.6 / G4: 5,000 ノートの vault で全文検索 200ms 以内。"""

    def test_5000ノートの検索が200ミリ秒以内(self, vault) -> None:
        import time

        db_path = vault.managed_dir / "index.sqlite"
        with IndexDb(db_path) as db:
            for index in range(5000):
                path = vault.root / f"メモ{index:04d}.md"
                path.write_text(
                    f"# メモ{index:04d}\n\n来期の予算について話した記録 #work/会議\n",
                    encoding="utf-8",
                )
            db.sync(vault)

            started = time.perf_counter()
            hits = db.search("予算について", limit=50)
            elapsed = (time.perf_counter() - started) * 1000

            assert hits
            assert elapsed < 200, f"全文検索に {elapsed:.0f}ms"


class TestIdChange:
    """front matter が失われても索引が壊れないこと（回帰テスト）。"""

    def test_front_matterを消されても更新できる(self, db, vault) -> None:
        note = add(vault, db, "メモ", "本文")
        assert note.id is not None

        # 外部エディタで front matter ごと書き換えられた状況
        vault.write(note.path, "# メモ\n\n書き換えた本文\n")
        db.upsert_note(Note.read(note.path), vault.root)

        rows = db.notes()
        assert len(rows) == 1, "同じパスの行が二重に入っている"
        assert rows[0].path == Path("メモ.md")

    def test_front_matterを消しても検索できる(self, db, vault) -> None:
        note = add(vault, db, "メモ", "古い本文")
        vault.write(note.path, "# メモ\n\n新しい本文\n")
        db.upsert_note(Note.read(note.path), vault.root)
        assert len(db.search("新しい本文")) == 1
        assert db.search("古い本文") == []
