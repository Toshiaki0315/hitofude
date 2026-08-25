"""検索インデックスのテスト（タスク 4-5〜4-7 / spec §7.3, R9）。

日本語検索が成立するかがこの層の存在意義。trigram の 3 文字制約と、
そこから漏れる 2 文字クエリの扱いを重点的に見る。
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from hitofude.core.document import Note, note_key
from hitofude.storage.index_db import SCHEMA_VERSION, IndexDb, SortOrder, rebuild
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

    def test_同じidの複製が両方一覧に出る(self, db, vault) -> None:
        """Finder でコピーすると同じ ULID の 2 ファイルができる（回帰）。

        id を奪い合うと、複製を取り込んだ時点で元ノートの行が上書きされ、
        次の sync では逆向きに上書きされて、同期のたびに見える側が
        入れ替わっていた。
        """
        note = vault.create("元ノート")
        db.sync(vault)
        copy = note.path.with_name("元ノート のコピー.md")
        copy.write_bytes(note.path.read_bytes())

        db.sync(vault)
        assert len(db.notes()) == 2

    def test_複製があっても同期のたびに入れ替わらない(self, db, vault) -> None:
        note = vault.create("元ノート")
        db.sync(vault)
        note.path.with_name("元ノート のコピー.md").write_bytes(note.path.read_bytes())

        db.sync(vault)
        first = sorted(row.path for row in db.notes())
        db.sync(vault)
        second = sorted(row.path for row in db.notes())
        assert first == second
        assert len(first) == 2

    def test_改名は今まで通りidを引き継ぐ(self, db, vault) -> None:
        """複製対策が改名・移動（元ファイルが消えている）を巻き込まないこと。"""
        note = vault.create("旧名")
        old_id = db.sync(vault) and db.notes()[0].id
        target = note.path.with_name("新名.md")
        note.path.replace(target)

        db.sync(vault)
        rows = db.notes()
        assert len(rows) == 1
        assert rows[0].id == old_id

    def test_壊れたファイルが混ざっていても他のノートは索引される(self, db, vault) -> None:
        """1 ファイルの故障で索引更新全体を止めない（回帰）。

        非 UTF-8 の `.md`（Shift-JIS で書き出したファイル等）が 1 つあると
        UnicodeDecodeError で sync 全体が失敗し、取り除くまで索引が
        一切更新されなくなっていた。
        """
        vault.create("正常なメモ")
        broken = vault.root / "壊れたメモ.md"
        broken.write_bytes("# シフトJISのメモ\n".encode("shift-jis"))

        result = db.sync(vault)

        assert len(result.added) == 1
        assert result.skipped == [broken]
        assert len(db.notes()) == 1

    def test_読めないファイルは索引の既存行を残す(self, db, vault) -> None:
        """一度索引されたノートが壊れても、行を消さずに古いまま残す。

        消すと一覧から見えなくなり、ユーザーが気づく手段を失う。
        """
        note = vault.create("メモ")
        db.sync(vault)
        note.path.write_bytes("後から壊れた\n".encode("shift-jis"))

        result = db.sync(vault)

        assert result.skipped == [note.path]
        assert result.removed == []
        assert len(db.notes()) == 1

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


class TestRenameOnDisk:
    """Finder でファイル名を変えたとき（ユーザーからの指摘）。

    **題名はファイル名ではなく本文から来る**（spec §7.2: 最初の H1 →
    最初の非空行 → ファイル名）。ファイル名は題名の写しであって、
    題名の出どころではない（ADR-0005）。

    リネームは索引が壊れやすい操作で、**パスは変わるが `id` は変わらない**。
    取り違えると旧名の行が残って一覧が二重になる。
    """

    def test_一覧が二重にならない(self, db, vault) -> None:
        note = add(vault, db, "会議メモ")
        note.path.replace(vault.root / "打ち合わせ.md")
        db.sync(vault)
        assert len(db.notes()) == 1

    def test_題名は変わらない(self, db, vault) -> None:
        """本文に見出しがあるかぎり、ファイル名を変えても表示は動かない。"""
        note = add(vault, db, "会議メモ")
        note.path.replace(vault.root / "打ち合わせ.md")
        db.sync(vault)
        assert db.notes()[0].title == "会議メモ"

    def test_新しいパスを指す(self, db, vault) -> None:
        note = add(vault, db, "会議メモ")
        note.path.replace(vault.root / "打ち合わせ.md")
        db.sync(vault)
        assert str(db.notes()[0].path) == "打ち合わせ.md"

    def test_同じノートのまま(self, db, vault) -> None:
        """`id` は front matter にあるので、リネームで別物にならない。"""
        note = add(vault, db, "会議メモ")
        before = db.notes()[0].id
        note.path.replace(vault.root / "打ち合わせ.md")
        db.sync(vault)
        assert db.notes()[0].id == before

    def test_本文が空なら改名しても題名は無題のまま(self, db, vault) -> None:
        """題名の出どころは本文だけ（ADR-0015）。

        以前はファイル名に落としていたが、ファイル名はタイトルの写し
        （ADR-0005）なので、本文を全部消しても直前のタイトルが残って
        見えていた。
        """
        note = vault.create("メモ帳", "")
        db.upsert_note(note, vault.root)
        note.path.replace(vault.root / "新しい名前.md")
        db.sync(vault)
        assert db.notes()[0].title == "無題"

    def test_タグも繋がりも付いてくる(self, db, vault) -> None:
        add(vault, db, "会議メモ")
        note = add(vault, db, "日報", "#仕事 と [[会議メモ]]\n")
        note.path.replace(vault.root / "きょうの記録.md")
        db.sync(vault)

        assert [row.title for row in db.notes_with_tag("仕事")] == ["日報"]
        assert [row.title for row in db.backlinks("会議メモ")] == ["日報"]


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


class TestSearchAcrossMarkers:
    """装飾をまたぐ検索（回帰テスト）。

    ソースをそのまま索引すると `**予算**について` で 1 つの文字列になり、
    `予算について` で引けない。書いた人にとって装飾は文章の一部ではない。
    """

    def test_強調をまたいで引ける(self, db, vault) -> None:
        add(vault, db, "会議メモ", "来期の**予算**について話した")
        assert len(db.search("予算について")) == 1

    def test_リンクの本文で引ける(self, db, vault) -> None:
        """角括弧が外れるので、リンクの表示文そのままで引ける。"""
        add(vault, db, "技術メモ", "[Qt のドキュメント](https://doc.qt.io/) を読む")
        assert len(db.search("Qt のドキュメント")) == 1

    def test_URLでも引ける(self, db, vault) -> None:
        add(vault, db, "技術メモ", "[Qt](https://doc.qt.io/) を読む")
        assert len(db.search("doc.qt.io")) == 1

    def test_見出しマーカーをまたいで引ける(self, db, vault) -> None:
        add(vault, db, "メモ", "## 来期の計画\n\n本文")
        assert len(db.search("来期の計画")) == 1

    def test_コードの記号は残す(self, db, vault) -> None:
        """コードは記号ごと検索できたほうがよい。"""
        add(vault, db, "技術メモ", "```python\nx = a ** b\n```")
        assert len(db.search("a ** b")) == 1

    def test_ソース側は変わらない(self, db, vault) -> None:
        """R1: 索引用の写しを作るだけで、保存内容には触れない。"""
        note = add(vault, db, "会議メモ", "来期の**予算**について")
        assert "**予算**" in note.path.read_text(encoding="utf-8")


class TestSortOrder:
    """一覧の並び順（C-3 / ユーザー提案）。

    既定は「ピン → 更新順」。**ピン留めは常に先頭**で、並び順を変えても
    そこは動かさない。ピン留めは「上に置いておきたい」という明示の意思なので。
    """

    def rows(self, db, vault, order) -> list[str]:
        return [row.title for row in db.notes(order=order)]

    @pytest.fixture
    def filled(self, db, vault):
        """日時を明示して置く。

        **`sleep` では差が付かない。** front matter の日時は秒単位なので、
        続けて作ると同じ値になり、並び順を検査できない（実際に踏んだ）。
        """
        stamps = (
            ("さくら", "2026-08-01T10:00:00+09:00", "2026-08-01T10:00:00+09:00"),
            ("あんず", "2026-08-02T10:00:00+09:00", "2026-08-02T10:00:00+09:00"),
            ("もみじ", "2026-08-03T10:00:00+09:00", "2026-08-03T10:00:00+09:00"),
        )
        for title, created, modified in stamps:
            note = vault.create(title, f"# {title}\n")
            text = note.path.read_text(encoding="utf-8")
            text = text.replace(note.meta["created"], created).replace(
                note.meta["modified"], modified
            )
            note.path.write_text(text, encoding="utf-8")
            db.upsert_note(Note.read(note.path), vault.root)
        return db

    def test_既定は更新順(self, filled, vault) -> None:
        assert self.rows(filled, vault, SortOrder.MODIFIED) == ["もみじ", "あんず", "さくら"]

    def test_作成順にできる(self, filled, vault) -> None:
        assert self.rows(filled, vault, SortOrder.CREATED) == ["もみじ", "あんず", "さくら"]

    def test_名前順にできる(self, filled, vault) -> None:
        assert self.rows(filled, vault, SortOrder.TITLE) == ["あんず", "さくら", "もみじ"]

    def test_どの並びでもピン留めが先頭(self, filled, vault) -> None:
        rows = filled.notes()
        target = next(row for row in rows if row.title == "さくら")
        filled.upsert_note(vault.set_pinned(vault.root / target.path, True), vault.root)
        for order in SortOrder:
            assert self.rows(filled, vault, order)[0] == "さくら", order

    def test_タグで絞っても並び順が効く(self, db, vault) -> None:
        for title in ("う", "い", "あ"):
            note = vault.create(title, f"# {title}\n\n#共通\n")
            db.upsert_note(note, vault.root)
        titles = [row.title for row in db.notes_with_tag("共通", order=SortOrder.TITLE)]
        assert titles == ["あ", "い", "う"]


class TestShortQueryEscaping:
    """短いクエリは LIKE フォールバック（§7.3）。記号もそのまま探す。"""

    def test_パーセントはワイルドカードにしない(self, db, vault) -> None:
        """`%` が LIKE のワイルドカードとして効き、1〜2 文字の検索で
        全件が引っかかっていた（回帰）。"""
        vault.create("進捗", "# 進捗\n\n達成率は 5% です\n")
        vault.create("別のメモ", "# 別のメモ\n\n記号は含まない\n")
        db.sync(vault)

        assert [hit.title for hit in db.search("%")] == ["進捗"]

    def test_アンダースコアもそのまま探す(self, db, vault) -> None:
        vault.create("識別子", "# 識別子\n\nmy_var を使う\n")
        vault.create("ほか", "# ほか\n\nmyxvar ではない\n")
        db.sync(vault)

        assert [hit.title for hit in db.search("_v")] == ["識別子"]


class TestSearchWithTags:
    """タグで絞る検索（提案 3）。

    `#仕事 予算` のように、**本文と同じ書き方**で絞れるようにする。
    索引のタグ表は先祖まで展開済みなので、`#仕事` で `#仕事/会議` も当たる。
    """

    @pytest.fixture
    def filled(self, db, vault):
        add(db=db, vault=vault, title="仕事の予算", body="来期の予算を決める\n\n#仕事")
        add(db=db, vault=vault, title="私用の予算", body="旅行の予算を決める\n\n#私用")
        add(db=db, vault=vault, title="会議の記録", body="来期の予算の話\n\n#仕事/会議")
        add(db=db, vault=vault, title="無関係", body="今日の天気\n\n#仕事")
        return db

    def test_タグと言葉の両方で絞る(self, filled) -> None:
        titles = {hit.title for hit in filled.search("予算", tags=("仕事",))}
        assert titles == {"仕事の予算", "会議の記録"}

    def test_親のタグで子も当たる(self, filled) -> None:
        """索引は先祖まで展開して入れている（`ancestors`）。"""
        titles = {hit.title for hit in filled.search("予算", tags=("仕事/会議",))}
        assert titles == {"会議の記録"}

    def test_複数のタグは全部満たす(self, filled) -> None:
        assert filled.search("予算", tags=("仕事", "私用")) == []

    def test_タグだけでも引ける(self, filled) -> None:
        """言葉が無いときは、そのタグのノートを並べる。"""
        titles = {hit.title for hit in filled.search("", tags=("仕事",))}
        assert titles == {"仕事の予算", "会議の記録", "無関係"}

    def test_短い言葉でも絞れる(self, filled) -> None:
        """2 文字以下は FTS を諦めて LIKE に落ちる経路（既存）。そこでも効く。"""
        titles = {hit.title for hit in filled.search("予算", tags=("私用",))}
        assert titles == {"私用の予算"}

    def test_ゴミ箱は出ない(self, filled, vault) -> None:
        note = vault.create("捨てる予算", "# 捨てる予算\n\n#仕事\n")
        filled.upsert_note(note, vault.root, trashed=True)
        titles = {hit.title for hit in filled.search("予算", tags=("仕事",))}
        assert "捨てる予算" not in titles

    def test_タグが無ければ今まで通り(self, filled) -> None:
        titles = {hit.title for hit in filled.search("予算")}
        assert titles == {"仕事の予算", "私用の予算", "会議の記録"}


class TestSearchWithDates:
    """期間で絞る検索（案 A）。**その日を含む。**"""

    @pytest.fixture
    def dated(self, db, vault):
        for title, day in (
            ("古い記録", "2026-07-01"),
            ("先月の記録", "2026-08-01"),
            ("今月の記録", "2026-08-20"),
        ):
            note = vault.create(title, f"# {title}\n\n予算の話\n")
            path = note.path
            text = path.read_text(encoding="utf-8").replace(
                note.meta["modified"], f"{day}T10:00:00+09:00"
            )
            path.write_text(text, encoding="utf-8")
            db.upsert_note(vault.read(path), vault.root)
        return db

    def test_開始日で絞る(self, dated) -> None:
        titles = {hit.title for hit in dated.search("予算", after=date(2026, 8, 1))}
        assert titles == {"先月の記録", "今月の記録"}

    def test_終了日で絞る(self, dated) -> None:
        titles = {hit.title for hit in dated.search("予算", before=date(2026, 8, 1))}
        assert titles == {"古い記録", "先月の記録"}

    def test_両端を含む(self, dated) -> None:
        """**区切りとして打つ日付は含む。** 含まないほうが驚く。"""
        titles = {
            hit.title
            for hit in dated.search("予算", after=date(2026, 8, 1), before=date(2026, 8, 1))
        }
        assert titles == {"先月の記録"}

    def test_タグと混ぜられる(self, dated, vault) -> None:
        note = vault.create("仕事の記録", "# 仕事の記録\n\n予算の話\n\n#仕事\n")
        dated.upsert_note(note, vault.root)
        titles = {hit.title for hit in dated.search("予算", tags=("仕事",), after=date(2026, 1, 1))}
        assert titles == {"仕事の記録"}

    def test_言葉なしでも絞れる(self, dated) -> None:
        titles = {hit.title for hit in dated.search("", after=date(2026, 8, 15))}
        assert titles == {"今月の記録"}

    def test_短い言葉でも絞れる(self, dated) -> None:
        titles = {hit.title for hit in dated.search("予算", after=date(2026, 8, 15))}
        assert titles == {"今月の記録"}


class TestDateFallback:
    """front matter の無いノートの日付（コードレビュー指摘）。

    外部エディタで作ったノートは modified が無い。空文字で格納すると
    文字列比較の after: に永遠に掛からず、before: には常に掛かる。
    ファイルの mtime へフォールバックする。
    """

    def make_external(self, tmp_path, body: str = "外部エディタのノート\n"):
        import os
        from datetime import datetime

        from hitofude.core.document import Note

        path = tmp_path / "外部.md"
        path.write_text(body, encoding="utf-8")
        stamp = datetime(2026, 8, 10, 12, 0, 0).timestamp()
        os.utime(path, (stamp, stamp))
        return Note.read(path)

    def test_mtimeが日付として入る(self, db, tmp_path) -> None:
        note = self.make_external(tmp_path)
        db.upsert_note(note, tmp_path)
        row = db.notes()[0]
        assert row.modified_at.startswith("2026-08-10")

    def test_afterで引ける(self, db, tmp_path) -> None:
        note = self.make_external(tmp_path)
        db.upsert_note(note, tmp_path)
        from datetime import date

        found = db.search("", after=date(2026, 8, 1))
        assert [hit.title for hit in found] == [note.title]

    def test_beforeで正しく除外される(self, db, tmp_path) -> None:
        from datetime import date

        note = self.make_external(tmp_path)
        db.upsert_note(note, tmp_path)
        assert db.search("", before=date(2020, 1, 1)) == []


class TestTitles:
    """題名だけの一覧（コードレビュー指摘）。

    [[ の補完は打鍵ごとに候補を引く。notes()（SELECT * + NoteRow 構築）
    では 5,000 ノートの vault で 16ms 予算を食うので、題名だけの列を返す。
    """

    def test_ゴミ箱以外の題名が返る(self, db, vault) -> None:
        for name in ("会議メモ", "日報"):
            note = vault.create(name, f"# {name}\n")
            db.upsert_note(note, vault.root)
        trashed = vault.create("捨てる", "# 捨てる\n")
        db.upsert_note(trashed, vault.root, trashed=True)

        found = db.titles()
        assert "会議メモ" in found and "日報" in found
        assert "捨てる" not in found


class TestFolders:
    """フォルダごとの件数と絞り込み（K-2）。

    サブフォルダは既に読める（§7.1）が、画面から見えなかった。タグツリーと
    同じ形で出せるように、索引側で数えられるようにする。
    """

    @pytest.fixture
    def foldered(self, db, vault):
        (vault.root / "仕事" / "2026").mkdir(parents=True, exist_ok=True)
        (vault.root / "私用").mkdir(parents=True, exist_ok=True)
        for relative in ("直下.md", "仕事/会議.md", "仕事/2026/年始.md", "私用/買い物.md"):
            path = vault.root / relative
            path.write_text(f"# {path.stem}\n\n本文\n", encoding="utf-8")
            db.upsert_note(vault.read(path), vault.root)
        return db

    def test_フォルダを数える(self, foldered) -> None:
        """**どのフォルダも直下だけを数える**（ユーザー要望）。

        選んだときに出るノートと同じ数でなければ、「2 と出ているのに
        1 件しか出ない」になる。
        """
        from hitofude.storage.index_db import ROOT_FOLDER

        found = {row.folder: row.count for row in foldered.folder_tree()}
        assert found == {ROOT_FOLDER: 1, "仕事": 1, "仕事/2026": 1, "私用": 1}

    def test_親は子を数えない(self, foldered) -> None:
        """`仕事` は直下の 1 件だけ（`仕事/2026` のぶんは子が持つ）。"""
        found = {row.folder: row.count for row in foldered.folder_tree()}
        assert found["仕事"] == 1

    def test_フォルダで絞れる(self, foldered) -> None:
        """**直下だけ**。`仕事/2026` の「年始」は含まない（ユーザー要望）。"""
        titles = {row.title for row in foldered.notes_in_folder("仕事")}
        assert titles == {"会議"}

    def test_子フォルダだけでも絞れる(self, foldered) -> None:
        titles = {row.title for row in foldered.notes_in_folder("仕事/2026")}
        assert titles == {"年始"}

    def test_似た名前を巻き込まない(self, foldered, vault) -> None:
        """`仕事` で `仕事場/` を拾わない（前方一致の落とし穴）。"""
        (vault.root / "仕事場").mkdir(parents=True, exist_ok=True)
        path = vault.root / "仕事場" / "別物.md"
        path.write_text("# 別物\n", encoding="utf-8")
        foldered.upsert_note(vault.read(path), vault.root)

        titles = {row.title for row in foldered.notes_in_folder("仕事")}
        assert "別物" not in titles

    def test_ゴミ箱は数えない(self, foldered, vault) -> None:
        path = vault.root / "仕事" / "捨てる.md"
        path.write_text("# 捨てる\n", encoding="utf-8")
        foldered.upsert_note(vault.read(path), vault.root, trashed=True)

        found = {row.folder: row.count for row in foldered.folder_tree()}
        assert found["仕事"] == 1  # 捨てたぶんは数えない（直下は「会議」だけ）

    def test_フォルダが無くてもルートだけは出る(self, db, vault) -> None:
        """「常に表示」（ユーザー要望）。サブフォルダがゼロでも直下は出す。"""
        from hitofude.storage.index_db import ROOT_FOLDER

        note = vault.create("直下だけ")
        db.upsert_note(note, vault.root)
        assert [row.folder for row in db.folder_tree()] == [ROOT_FOLDER]


class TestFolderRangeQuery:
    """フォルダ絞りは範囲述語で引く（コードレビュー指摘）。

    LIKE は既定の大文字小文字非区別と BINARY 索引が噛み合わず常に全表
    走査になる（EXPLAIN で実測）。範囲（path >= '仕事/' AND path < '仕事0'）
    なら UNIQUE 索引をそのまま使える。
    """

    def make(self, db, vault, relative: str):
        path = vault.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")
        from hitofude.core.document import Note

        db.upsert_note(Note.read(path), vault.root)

    def test_境界の隣の名前を拾わない(self, db, vault) -> None:
        self.make(db, vault, "仕事/中.md")
        self.make(db, vault, "仕事場/外.md")
        found = [str(row.path) for row in db.notes_in_folder("仕事")]
        assert found == ["仕事/中.md"]

    def test_LIKEの記号を含むフォルダ名も引ける(self, db, vault) -> None:
        self.make(db, vault, "50%off_セール/対象.md")
        found = [row.title for row in db.notes_in_folder("50%off_セール")]
        assert found == ["対象"]

    def test_索引を使って引けている(self, db, vault) -> None:
        self.make(db, vault, "仕事/中.md")
        plan = db._connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM notes WHERE trashed = 0 AND path >= ? AND path < ?",
            ("仕事/", "仕事0"),
        ).fetchall()
        assert any("SEARCH" in row["detail"] for row in plan)


class TestNotesMatching:
    """保存した検索の中身を一覧の行として引く（K-4）。"""

    def seed(self, db, vault):
        for title, body in (
            ("仕事の予算", "来期の予算を決める\n\n#仕事"),
            ("私用の予算", "旅行の予算\n\n#私用"),
            ("仕事の雑務", "備品の発注\n\n#仕事"),
        ):
            note = vault.create(title, f"# {title}\n\n{body}\n")
            db.upsert_note(note, vault.root)

    def test_タグと言葉で絞れる(self, db, vault) -> None:
        self.seed(db, vault)
        rows = db.notes_matching(text="予算", tags=("仕事",))
        assert [row.title for row in rows] == ["仕事の予算"]

    def test_絞り込みだけでも引ける(self, db, vault) -> None:
        self.seed(db, vault)
        rows = db.notes_matching(text="", tags=("仕事",))
        assert {row.title for row in rows} == {"仕事の予算", "仕事の雑務"}

    def test_ピン留めが先頭に来る(self, db, vault) -> None:
        self.seed(db, vault)
        pinned = vault.set_pinned(vault.root / "仕事の雑務.md", True)
        db.upsert_note(pinned, vault.root)
        rows = db.notes_matching(text="", tags=("仕事",))
        assert rows[0].title == "仕事の雑務"


class TestRootFolder:
    """ルートも「フォルダ」として並べる（ユーザー要望）。

    **ルートだけは非再帰**（直下のノートだけ）。子孫まで含めると
    「すべて」と同義になり、選ぶ意味が無くなる。
    """

    def seed(self, db, vault):
        for relative in ("直下A.md", "直下B.md", "仕事/中.md", "仕事/2026/深い.md"):
            path = vault.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.stem}\n", encoding="utf-8")
            from hitofude.core.document import Note

            db.upsert_note(Note.read(path), vault.root)

    def test_ルートが先頭に並ぶ(self, db, vault) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER

        self.seed(db, vault)
        found = db.folder_tree()
        assert found[0].folder == ROOT_FOLDER
        assert found[0].count == 2  # 直下の 2 件だけ

    def test_フォルダが無くてもルートは出る(self, db, vault) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER

        note = vault.create("ひとつ", "# ひとつ\n")
        db.upsert_note(note, vault.root)
        assert [count.folder for count in db.folder_tree()] == [ROOT_FOLDER]

    def test_ルートを選ぶと直下だけ(self, db, vault) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER

        self.seed(db, vault)
        rows = db.notes_in_folder(ROOT_FOLDER)
        assert {row.title for row in rows} == {"直下A", "直下B"}

    def test_どのフォルダも直下だけ(self, db, vault) -> None:
        """ルートと同じ規則に揃えた（ユーザー要望）。"""
        self.seed(db, vault)
        assert {row.title for row in db.notes_in_folder("仕事")} == {"中"}
        assert {row.title for row in db.notes_in_folder("仕事/2026")} == {"深い"}


class TestMergeFolders:
    """索引の件数とディスクのフォルダを合わせる（ユーザー要望）。

    件数は索引（速い）、存在はディスク（空フォルダも見える）。
    """

    def test_空のフォルダは0件で並ぶ(self) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER, FolderCount, merge_folders

        counts = [FolderCount(folder=ROOT_FOLDER, count=1), FolderCount(folder="仕事", count=2)]
        found = merge_folders(counts, ["仕事", "空っぽ"])
        assert [(row.folder, row.count) for row in found] == [
            (ROOT_FOLDER, 1),
            ("仕事", 2),
            ("空っぽ", 0),
        ]

    def test_ルートは常に先頭(self) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER, FolderCount, merge_folders

        found = merge_folders([FolderCount(folder=ROOT_FOLDER, count=0)], ["あ", "い"])
        assert found[0].folder == ROOT_FOLDER

    def test_消えたフォルダは残さない(self) -> None:
        """索引が古くてもディスクに無いフォルダは出さない（R9: 真実はファイル）。"""
        from hitofude.storage.index_db import ROOT_FOLDER, FolderCount, merge_folders

        counts = [FolderCount(folder=ROOT_FOLDER, count=0), FolderCount(folder="消えた", count=3)]
        found = merge_folders(counts, [])
        assert [row.folder for row in found] == [ROOT_FOLDER]


class TestDirectChildrenOnly:
    """フォルダを選んだら**そのフォルダ直下だけ**（ユーザー要望）。

    ルートが非再帰なのにサブフォルダは再帰、という食い違いを揃える。
    """

    def seed(self, db, vault):
        for relative in (
            "直下.md",
            "仕事/浅い.md",
            "仕事/2026/深い.md",
            "仕事/2026/期末/もっと深い.md",
        ):
            path = vault.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.stem}\n", encoding="utf-8")
            db.upsert_note(vault.read(path), vault.root)

    def test_孫は出さない(self, db, vault) -> None:
        self.seed(db, vault)
        assert {row.title for row in db.notes_in_folder("仕事")} == {"浅い"}

    def test_中間のフォルダも直下だけ(self, db, vault) -> None:
        self.seed(db, vault)
        assert {row.title for row in db.notes_in_folder("仕事/2026")} == {"深い"}

    def test_末端も引ける(self, db, vault) -> None:
        self.seed(db, vault)
        assert {row.title for row in db.notes_in_folder("仕事/2026/期末")} == {"もっと深い"}

    def test_件数と一覧が一致する(self, db, vault) -> None:
        """サイドバーの数字と、選んだときに出る件数がずれない。"""
        self.seed(db, vault)
        counts = {row.folder: row.count for row in db.folder_tree()}
        for folder, count in counts.items():
            assert len(db.notes_in_folder(folder)) == count, folder


class TestRelatedSignals:
    """関連ノートの根拠を索引から引く（L-3）。

    **既に索引にある**もの（タグ・`[[…]]`）を引き直すだけ。新しい表は
    増やさない（R9: 索引は捨てて作り直せるまま）。
    """

    def seeded(self, db, vault):
        from hitofude.core.document import Note

        notes = {
            "今.md": "# 今\n\n#仕事 の話。[[会議メモ]] を見る。\n",
            "仕事/会議メモ.md": "# 会議メモ\n\n#仕事 の会議。\n",
            "私用/買い物.md": "# 買い物\n\n#私用 のメモ。\n",
            "指す.md": "# 指す\n\n[[今]] を指している。\n",
        }
        for relative, text in notes.items():
            path = vault.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            db.upsert_note(Note.read(path), vault.root)
        return note_key(Note.read(vault.root / "今.md"), vault.root)

    def test_同じタグのノートが出る(self, db, vault) -> None:
        self.seeded(db, vault)
        found = {str(row.path) for row in db.notes_sharing_tags(["仕事"])}
        assert "仕事/会議メモ.md" in found
        assert "私用/買い物.md" not in found

    def test_自分のタグが分かる(self, db, vault) -> None:
        note_id = self.seeded(db, vault)
        assert db.tags_of(note_id) == ["仕事"]

    def test_指している先が分かる(self, db, vault) -> None:
        note_id = self.seeded(db, vault)
        assert db.links_of(note_id) == ["会議メモ"]

    def test_指されている側も引ける(self, db, vault) -> None:
        """既にある `backlinks()` をそのまま使う（増やさない）。"""
        self.seeded(db, vault)
        assert [str(row.path) for row in db.backlinks("今")] == ["指す.md"]

    def test_タグが無ければ空(self, db) -> None:
        assert db.notes_sharing_tags([]) == []


class TestLinkMap:
    """図（M-2）が要る「題名 → 指している先」の一覧。

    **1 本ずつ引かない。** 深さ 2 でも数十本になり、そのたびに問い合わせると
    開くのが遅くなる（`titles()` を足したときと同じ理由）。
    """

    def test_指している先が題名で引ける(self, vault, db) -> None:
        add(vault, db, "会議メモ", "[[買い物リスト]] を見る")
        add(vault, db, "買い物リスト", "卵と牛乳")
        assert db.link_map() == {"会議メモ": ["買い物リスト"], "買い物リスト": []}

    def test_リンクの無いノートも鍵になる(self, vault, db) -> None:
        """**索引にあること**が「まだ無いノート」との違い。図はここで見分ける。"""
        add(vault, db, "ひとりごと", "誰も指していない")
        assert db.link_map() == {"ひとりごと": []}

    def test_行き先が無くても載せる(self, vault, db) -> None:
        add(vault, db, "会議メモ", "[[まだ無いノート]] と書いた")
        assert db.link_map()["会議メモ"] == ["まだ無いノート"]

    def test_ゴミ箱のノートは出さない(self, vault, db) -> None:
        """**捨てたものは図に出さない**（一覧にも検索にも出ない）。"""
        note = add(vault, db, "捨てる", "[[会議メモ]]")
        db.upsert_note(note, vault.root, trashed=True)
        assert "捨てる" not in db.link_map()

    def test_同じ題名が_2_つあってもまとめる(self, vault, db) -> None:
        """題名で引く図なので、鍵は題名。**片方が消えない**ようにする。"""
        add(vault, db, "同じ名前", "[[あ]]")
        second = vault.create("同じ名前", "# 同じ名前\n\n[[い]]\n")
        db.upsert_note(second, vault.root)
        assert sorted(db.link_map()["同じ名前"]) == ["あ", "い"]

    def test_空なら空(self, db) -> None:
        assert db.link_map() == {}


class TestRelations:
    """リンクに付く続柄（M-3）。**同じ相手を別の関係で指せる。**"""

    def test_続柄ごと索引に入る(self, vault, db) -> None:
        add(vault, db, "会議メモ", "- 参考文献: [[本]]\n- 元ネタ: [[日報]]")
        assert db.link_map()["会議メモ"] == ["日報", "本"]
        assert sorted(db.relations()) == ["元ネタ", "参考文献"]

    def test_続柄で絞れる(self, vault, db) -> None:
        add(vault, db, "会議メモ", "- 参考文献: [[本]]\n- 元ネタ: [[日報]]")
        assert db.link_map(relation="参考文献") == {"会議メモ": ["本"]}

    def test_絞ってもノートは残す(self, vault, db) -> None:
        """**図の起点が消えない。** 鍵ごと消えると起点を置く場所が無くなる。"""
        add(vault, db, "ひとりごと", "何も指していない")
        assert db.link_map(relation="参考文献") == {"ひとりごと": []}

    def test_同じ相手を別の続柄で指せる(self, vault, db) -> None:
        """主キーが `(note_id, target)` のままだと**片方が消える**。"""
        add(vault, db, "会議メモ", "- 参考文献: [[本]]\n- 元ネタ: [[本]]")
        assert db.link_map(relation="元ネタ") == {"会議メモ": ["本"]}
        assert db.link_map(relation="参考文献") == {"会議メモ": ["本"]}

    def test_無印のリンクは続柄に出てこない(self, vault, db) -> None:
        """**それが普通。** 空の続柄が選択肢に並ぶと邪魔になる。"""
        add(vault, db, "会議メモ", "[[本]] を見る")
        assert db.relations() == []

    def test_続柄の一覧は並べて重複を除く(self, vault, db) -> None:
        add(vault, db, "あ", "- 参考文献: [[本]]")
        add(vault, db, "い", "- 参考文献: [[別の本]]\n- 前提: [[土台]]")
        assert db.relations() == ["前提", "参考文献"]

    def test_ゴミ箱のノートの続柄は出さない(self, vault, db) -> None:
        note = add(vault, db, "捨てる", "- 参考文献: [[本]]")
        db.upsert_note(note, vault.root, trashed=True)
        assert db.relations() == []

    def test_指されている側も続柄で引ける(self, vault, db) -> None:
        """「参考文献として指しているノート」を引く（M-3 の使い道）。"""
        add(vault, db, "会議メモ", "- 参考文献: [[本]]")
        add(vault, db, "日報", "- 元ネタ: [[本]]")
        assert [row.title for row in db.backlinks("本", relation="参考文献")] == ["会議メモ"]

    def test_続柄を指定しなければ今まで通り(self, vault, db) -> None:
        add(vault, db, "会議メモ", "- 参考文献: [[本]]")
        add(vault, db, "日報", "[[本]]")
        assert {row.title for row in db.backlinks("本")} == {"会議メモ", "日報"}


class TestSchemaVersion:
    def test_版を上げてある(self) -> None:
        """**上げないと古いノートの新しい列が黙って空のまま残る**（表の注記）。

        `relation` を足したのに版が 3 のままだと、既にあるノートは触られる
        まで読み直されず（`sync()` は mtime を見る）、続柄が付かない。
        """
        assert IndexDb.__module__  # 参照だけ（下の値がこのテストの本体）
        from hitofude.storage.index_db import SCHEMA_VERSION

        assert SCHEMA_VERSION >= 4


# 版 3 の形（`links` に `relation` が無い）。**実際に出荷した形**で、
# ここから上げられなければ、使っている人のノートが一覧から消える
OLD_SCHEMA_V3 = """
CREATE TABLE notes (
    id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
    preview TEXT NOT NULL, created_at TEXT NOT NULL, modified_at TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL, size_bytes INTEGER NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0, trashed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tags (note_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (note_id, tag));
CREATE TABLE links (note_id TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY (note_id, target));
CREATE VIRTUAL TABLE notes_fts USING fts5(
    title, body, note_id UNINDEXED, tokenize = 'trigram'
);
"""


def make_old_index(vault, *, version: int) -> Path:
    """古い形の索引をその場に作る。"""
    path = vault.managed_dir / "index.sqlite"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA_V3)
    con.execute(f"PRAGMA user_version = {version}")
    con.commit()
    con.close()
    return path


class TestUpgradeFromOldShape:
    """**列を足したときに古い形を作り変える**（不具合。ユーザー報告 2026-08-23）。

    `CREATE TABLE IF NOT EXISTS` は既にある表を作り変えない。`reset()` は
    行を消すだけなので、`links` は 2 列のまま残った。そこへ `relation` を
    書こうとして毎回失敗し、**索引が空のまま**——一覧からノートが全部
    消えて見えた（ファイルは無事、ゴミ箱は別経路なので見えていた）。
    """

    def test_古い形でも取り込める(self, vault) -> None:
        note = vault.create("会議メモ", "# 会議メモ\n\n- 参考文献: [[本]]\n")
        with IndexDb(make_old_index(vault, version=3)) as db:
            db.upsert_note(note, vault.root)
            assert [row.title for row in db.notes()] == ["会議メモ"]
            assert db.link_map()["会議メモ"] == ["本"]

    def test_古い形でも走査できる(self, vault) -> None:
        vault.create("会議メモ", "# 会議メモ\n\n- 参考文献: [[本]]\n")
        with IndexDb(make_old_index(vault, version=3)) as db:
            assert len(db.sync(vault).added) == 1
            assert len(db.notes()) == 1

    def test_版が今と同じでも形が古ければ作り直す(self, vault) -> None:
        """**版だけ見ていると直らない。** 版 4 を古い形のまま出してしまった
        ので、使っている人の索引は「版は 4、形は 3」になっている。
        """
        vault.create("会議メモ", "# 会議メモ\n\n- 参考文献: [[本]]\n")
        with IndexDb(make_old_index(vault, version=SCHEMA_VERSION)) as db:
            assert len(db.sync(vault).added) == 1
            assert db.link_map()["会議メモ"] == ["本"]

    def test_主キーの違いも作り直す(self, vault) -> None:
        """列は合っていても**主キーが古い**と、同じ相手を別の続柄で指せない。"""
        path = vault.managed_dir / "index.sqlite"
        con = sqlite3.connect(path)
        con.executescript(
            OLD_SCHEMA_V3.replace(
                "CREATE TABLE links (note_id TEXT NOT NULL, target TEXT NOT NULL,"
                " PRIMARY KEY (note_id, target));",
                "CREATE TABLE links (note_id TEXT NOT NULL, target TEXT NOT NULL,"
                " relation TEXT NOT NULL DEFAULT '', PRIMARY KEY (note_id, target));",
            )
        )
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        con.commit()
        con.close()
        note = vault.create("会議メモ", "# 会議メモ\n\n- 参考文献: [[本]]\n- 元ネタ: [[本]]\n")
        with IndexDb(path) as db:
            db.upsert_note(note, vault.root)
            assert db.link_map(relation="参考文献") == {"会議メモ": ["本"]}
            assert db.link_map(relation="元ネタ") == {"会議メモ": ["本"]}

    def test_今の形は作り直さない(self, vault, db) -> None:
        """**毎回作り直さない。** 起動のたびに全件読み直すことになる。"""
        note = vault.create("会議メモ", "# 会議メモ\n\n本文\n")
        db.upsert_note(note, vault.root)
        assert len(db.notes()) == 1
        db._migrate()  # 2 度目
        assert len(db.notes()) == 1


class TestRebuildInPlace:
    """**開いたままの接続からも見える**ように作り直す（ユーザー要望の同期）。

    `rebuild()` は索引のファイルを消して作り直す（R9 の担保）。それを
    背景スレッドでやると、**UI 側が持っている接続は消えた実体を読み続ける**
    ——作り直したのに一覧が空のまま、という壊れ方になる（実測）。
    """

    def test_持っている接続からも見える(self, vault, db) -> None:
        for title in ("あ", "い", "う"):
            vault.create(title, f"# {title}\n\n本文\n")
        db.sync(vault)
        db.reset()
        assert db.notes() == []

        # 背景スレッドの代わりに、別の接続から作り直す
        with IndexDb(db.path) as worker:
            assert len(worker.rebuild_in_place(vault).added) == 3
        assert len(db.notes()) == 3

    def test_ファイルは消さない(self, vault, db) -> None:
        """R9。**捨ててよいのは索引だけ。**"""
        vault.create("あ", "# あ\n\n本文\n")
        db.rebuild_in_place(vault)
        assert sorted(path.name for path in vault.root.glob("*.md")) == ["あ.md"]

    def test_中身が狂っていても直る(self, vault, db) -> None:
        """**差分だけでは直らない場面。** `sync()` は `mtime` と大きさで
        飛ばすので、ファイルが変わっていなければ索引の中身が狂っていても
        読み直さない。作り直しはそこを直せる（これが要る理由そのもの）。
        """
        note = vault.create("会議メモ", "# 会議メモ\n\n本文\n")
        db.sync(vault)
        # 索引の中だけ壊す（ファイルは触らない）
        db._connection.execute("UPDATE notes SET title = 'でたらめ'")
        db._connection.commit()
        assert [row.title for row in db.notes()] == ["でたらめ"]

        assert db.sync(vault).changed == 0  # 差分では気づけない
        assert [row.title for row in db.notes()] == ["でたらめ"]

        db.rebuild_in_place(vault)
        assert [row.title for row in db.notes()] == ["会議メモ"]
        assert note.path.exists()

    def test_古い行は残さない(self, vault, db) -> None:
        """作り直しなので、**外で消えたノートの行も消える**。"""
        note = vault.create("消える", "# 消える\n\n本文\n")
        db.sync(vault)
        note.path.unlink()
        db.rebuild_in_place(vault)
        assert db.notes() == []

    def test_形が古くても直る(self, vault) -> None:
        """壊れた索引のための逃げ道なので、**形の違いも直せる**。"""
        vault.create("あ", "# あ\n\n- 参考文献: [[本]]\n")
        with IndexDb(make_old_index(vault, version=SCHEMA_VERSION)) as db:
            db.rebuild_in_place(vault)
            assert db.link_map()["あ"] == ["本"]
