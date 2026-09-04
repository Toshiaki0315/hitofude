"""ファイルと索引を手で合わせ直す（ユーザー要望 2026-08-23）。

**Finder で直に触ることがある。** 監視（`storage/watcher.py`）は動いて
いる間しか効かず、閉じている間の操作やネットワーク越しの変更は取り
こぼす。取りこぼしたことは**画面からは分からない**ので、押せば必ず
合う道を用意する。

**2 つ置く理由は 100 倍の差**（実測。5,000 本の保管フォルダ）。

| | 差分だけ | 全部作り直す |
| --- | --- | --- |
| 5,000 本 | 144 ms | 19 秒 |

ふだんの取りこぼしは差分で足りる。作り直しは**索引そのものが疑わしい**
ときのためのもの。
"""

import shutil

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def seeded(window):
    for title in ("会議メモ", "買い物リスト"):
        note = window._vault.create(title, f"# {title}\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
    window.refresh()
    # **起動時の走査を先に済ませる。** 残っていると resync() が
    # 「話し中」で弾かれ、実行順しだいで落ちる（実際に落ちた）
    window.wait_for_index_sync()
    return window


def titles(window) -> set[str]:
    return {row.title for row in window._db.notes()}


class TestMenu:
    def test_メニューにある(self, seeded) -> None:
        assert "最新の情報に同期" in seeded.menu_actions
        assert "索引を作り直す" in seeded.menu_actions

    def test_キーは付けない(self, seeded) -> None:
        """**急ぐ操作ではない**（「版の履歴…」と同じ理由）。増やせば衝突の種。"""
        for label in ("最新の情報に同期", "索引を作り直す"):
            assert seeded.menu_actions[label].shortcut().toString() == ""


class TestResync:
    """差分だけ取り込む。**Finder で触ったぶんが入る。**"""

    def test_外で足したファイルが出る(self, seeded, qtbot) -> None:
        (seeded._vault.root / "外で作った.md").write_text(
            "# 外で作った\n\nFinder で置いた\n", encoding="utf-8"
        )
        seeded.resync()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: "外で作った" in titles(seeded), timeout=5000)

    def test_外で消したファイルが消える(self, seeded, qtbot) -> None:
        (seeded._vault.root / "会議メモ.md").unlink()
        seeded.resync()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: "会議メモ" not in titles(seeded), timeout=5000)

    def test_外で書き換えたら題名も追う(self, seeded, qtbot) -> None:
        (seeded._vault.root / "会議メモ.md").write_text(
            "# 打ち合わせメモ\n\n書き換えた\n", encoding="utf-8"
        )
        seeded.resync()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: "打ち合わせメモ" in titles(seeded), timeout=5000)

    def test_始めたことを知らせる(self, seeded) -> None:
        """**押しても何も起きないように見えない**（速すぎて分からない）。"""
        seeded.resync()
        assert seeded.notice()
        seeded.wait_for_index_sync()

    def test_終わったら結果を知らせる(self, seeded, qtbot) -> None:
        (seeded._vault.root / "外で作った.md").write_text(
            "# 外で作った\n\n本文\n", encoding="utf-8"
        )
        seeded.resync()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: "1" in seeded.notice(), timeout=5000)

    def test_変わっていなければそう言う(self, seeded, qtbot) -> None:
        """**「何も起きなかった」と「壊れている」を見分けられるように。**"""
        seeded.resync()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: "変わり" in seeded.notice(), timeout=5000)

    def test_打ちかけを先に保存する(self, seeded, qtbot) -> None:
        """**保存していない字を失わない**（走査は保存済みのファイルを読む）。"""
        note = seeded._vault.create("打ちかけ", "# 打ちかけ\n\n")
        seeded._db.upsert_note(note, seeded._vault.root)
        seeded.refresh()
        seeded.open_and_select(note.path)
        cursor = seeded.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("まだ保存していない字")
        seeded.resync()
        seeded.wait_for_index_sync()
        assert "まだ保存していない字" in note.path.read_text(encoding="utf-8")

    def test_二重に走らせない(self, seeded) -> None:
        seeded.resync()
        assert seeded.resync() is False
        seeded.wait_for_index_sync()

    def test_走っている間に押したら待つよう伝える(self, seeded) -> None:
        """**押しても無反応に見せない**（走査中は始められない）。"""
        from hitofude.ui.main_window import BUSY_NOTICE

        seeded.resync()
        seeded.resync()
        assert seeded.notice() == BUSY_NOTICE
        seeded.wait_for_index_sync()


class TestRebuild:
    """索引を作り直す。**捨ててよいキャッシュ**なので作り直せる（R9）。"""

    def test_壊れた索引でも一覧が戻る(self, seeded, qtbot) -> None:
        """**これが要る場面。** 索引だけがおかしいときの逃げ道。"""
        seeded._db.reset()
        seeded.refresh()
        assert titles(seeded) == set()
        seeded.rebuild_index()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: titles(seeded) == {"会議メモ", "買い物リスト"}, timeout=10000)

    def test_持っている接続からも見える(self, seeded, qtbot) -> None:
        """**索引のファイルを消さない。** 消すと UI 側の接続が消えた実体を
        読み続け、作り直したのに一覧が空のままになる（実測）。
        """
        seeded._db.reset()
        seeded.rebuild_index()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: bool(titles(seeded)), timeout=10000)
        assert seeded.note_list.model().rowCount() > 0

    def test_ファイルは消さない(self, seeded, qtbot) -> None:
        """R9。**捨ててよいのは索引だけ。**"""
        before = sorted(path.name for path in seeded._vault.root.glob("*.md"))
        seeded.rebuild_index()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: bool(titles(seeded)), timeout=10000)
        assert sorted(path.name for path in seeded._vault.root.glob("*.md")) == before

    def test_履歴は消さない(self, seeded, qtbot) -> None:
        """**`.hitofude` ごと消さない**（ADR-0023。版は `.md` から作り直せない）。"""
        versions = seeded._vault.managed_dir / "history"
        versions.mkdir(parents=True, exist_ok=True)
        (versions / "しるし").write_text("残る", encoding="utf-8")
        seeded.rebuild_index()
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: bool(titles(seeded)), timeout=10000)
        assert (versions / "しるし").exists()

    def test_始めたことを知らせる(self, seeded) -> None:
        """**5,000 本で 19 秒**（実測）。黙って固まったように見せない。"""
        seeded.rebuild_index()
        assert seeded.notice()
        seeded.wait_for_index_sync()

    def test_二重に走らせない(self, seeded) -> None:
        seeded.rebuild_index()
        assert seeded.rebuild_index() is False
        seeded.wait_for_index_sync()

    def test_同期中は作り直しも始めない(self, seeded) -> None:
        from hitofude.ui.main_window import BUSY_NOTICE

        seeded.resync()
        assert seeded.rebuild_index() is False
        assert seeded.notice() == BUSY_NOTICE
        seeded.wait_for_index_sync()


class TestFailure:
    def test_失敗したら知らせる(self, seeded) -> None:
        """壊れたときこそ押される操作なので、**黙って終わらない**。"""
        seeded._on_index_sync_failed(RuntimeError("だめ"))
        assert seeded.notice() == seeded.SYNC_FAILED_NOTICE

    def test_失敗しても次は押せる(self, seeded) -> None:
        seeded.resync()
        seeded._on_index_sync_failed(RuntimeError("だめ"))
        seeded.wait_for_index_sync()
        assert seeded.resync() is True
        seeded.wait_for_index_sync()


class TestVaultPath:
    def test_保管フォルダが無くても知らせる(self, seeded, qtbot) -> None:
        """**外で保管フォルダごと消されていることがある。** 落ちずに伝える。"""
        shutil.rmtree(seeded._vault.root)
        assert seeded.resync() is True
        seeded.wait_for_index_sync()
        qtbot.waitUntil(lambda: bool(seeded.notice()), timeout=5000)


class TestTaskWiring:
    """**ワーカーを直に見る**（窓越しでは確かめられない）。

    窓を通すと監視（`storage/watcher.py`）が裏で索引を直してしまい、
    「作り直す」を「差分だけ」に変えても試験が通ってしまった（実測）。
    ここは `MainWindow` を作らないので監視が動かない。
    """

    def run_task(self, vault, *, full: bool) -> None:
        from hitofude.storage.index_db import INDEX_FILE
        from hitofude.ui.index_sync import IndexSyncTask, SyncReporter

        # **受け口を持ったままにする。** 親を使い捨てにすると、走り終わりの
        # 合図を飛ばすところで「送り主が消えている」と言われる
        self.reporter = SyncReporter()
        IndexSyncTask(vault.managed_dir / INDEX_FILE, vault, self.reporter, full=full).run()

    def spoil(self, vault) -> None:
        """ファイルは触らず、索引の中だけ狂わせる。"""
        from hitofude.storage.index_db import INDEX_FILE, IndexDb

        with IndexDb(vault.managed_dir / INDEX_FILE) as db:
            db.sync(vault)
            db._connection.execute("UPDATE notes SET title = 'でたらめ'")
            db._connection.commit()

    def titles_of(self, vault) -> set[str]:
        from hitofude.storage.index_db import INDEX_FILE, IndexDb

        with IndexDb(vault.managed_dir / INDEX_FILE) as db:
            return {row.title for row in db.notes()}

    @pytest.fixture
    def vault(self, tmp_path):
        from hitofude.storage.vault import Vault

        found = Vault(tmp_path / "V")
        found.ensure_layout()
        found.create("会議メモ", "# 会議メモ\n\n本文\n")
        return found

    def test_差分だけでは直らない(self, vault) -> None:
        """`sync()` は `mtime` と大きさで飛ばすので、中身の狂いに気づけない。"""
        self.spoil(vault)
        self.run_task(vault, full=False)
        assert self.titles_of(vault) == {"でたらめ"}

    def test_作り直せば直る(self, vault) -> None:
        """**これが 2 つ置く理由。** ここを差分に変えると直らなくなる。"""
        self.spoil(vault)
        self.run_task(vault, full=True)
        assert self.titles_of(vault) == {"会議メモ"}
