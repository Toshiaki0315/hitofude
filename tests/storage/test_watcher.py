"""外部変更の検知と競合判定のテスト（タスク 4-8, 4-9 / spec §7.5）。

`watcher.py` は R3 の唯一の例外で PySide6 を import してよい。
そのぶん**判断ロジックは Qt に触れない純粋な部分に寄せて**、
ここで網羅的に検査する。
"""

from pathlib import Path

import pytest

from hitofude.storage.vault import (
    ConflictAction,
    Vault,
    check_conflict,
    decide,
    keep_both_path,
)
from hitofude.storage.watcher import ChangeKind, WriteSuppressor, classify_event


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestWriteSuppressor:
    """spec §7.5: 自分で書いた直後のイベントは無視リストで除外する。"""

    @pytest.fixture
    def clock(self) -> FakeClock:
        return FakeClock()

    @pytest.fixture
    def suppressor(self, clock: FakeClock) -> WriteSuppressor:
        return WriteSuppressor(window=1.5, clock=clock)

    def test_登録していないパスは通す(self, suppressor) -> None:
        assert suppressor.should_ignore(Path("/vault/メモ.md")) is False

    def test_登録した直後は無視する(self, suppressor) -> None:
        path = Path("/vault/メモ.md")
        suppressor.suppress(path)
        assert suppressor.should_ignore(path) is True

    def test_時間が経てば通す(self, suppressor, clock) -> None:
        path = Path("/vault/メモ.md")
        suppressor.suppress(path)
        clock.advance(1.6)
        assert suppressor.should_ignore(path) is False

    def test_他のパスには影響しない(self, suppressor) -> None:
        suppressor.suppress(Path("/vault/A.md"))
        assert suppressor.should_ignore(Path("/vault/B.md")) is False

    def test_書き直すと期限が延びる(self, suppressor, clock) -> None:
        path = Path("/vault/メモ.md")
        suppressor.suppress(path)
        clock.advance(1.0)
        suppressor.suppress(path)
        clock.advance(1.0)
        assert suppressor.should_ignore(path) is True

    def test_期限切れは溜め込まない(self, suppressor, clock) -> None:
        """保存のたびに増えると長時間の編集でメモリを食う。"""
        for index in range(100):
            suppressor.suppress(Path(f"/vault/{index}.md"))
        clock.advance(2.0)
        suppressor.should_ignore(Path("/vault/0.md"))
        assert len(suppressor) == 0


class TestClassifyEvent:
    """watchdog のイベントを、扱うべき変更に翻訳する。"""

    ROOT = Path("/vault")

    def test_マークダウンの変更を拾う(self) -> None:
        got = classify_event(self.ROOT, "modified", Path("/vault/メモ.md"), is_directory=False)
        assert got == (ChangeKind.MODIFIED, Path("/vault/メモ.md"))

    def test_作成と削除も拾う(self) -> None:
        assert classify_event(self.ROOT, "created", Path("/vault/A.md"), is_directory=False)[0] is (
            ChangeKind.CREATED
        )
        assert classify_event(self.ROOT, "deleted", Path("/vault/A.md"), is_directory=False)[0] is (
            ChangeKind.DELETED
        )

    def test_ディレクトリは無視(self) -> None:
        assert classify_event(self.ROOT, "created", Path("/vault/仕事"), is_directory=True) is None

    def test_マークダウン以外は無視(self) -> None:
        assert classify_event(self.ROOT, "modified", Path("/vault/画像.png"), False) is None

    def test_一時ファイルは無視(self) -> None:
        """save_atomic が作る `.md.tmp` を変更として拾ってはいけない。"""
        assert classify_event(self.ROOT, "created", Path("/vault/メモ.md.tmp"), False) is None

    @pytest.mark.parametrize("directory", [".trash", ".hitofude"])
    def test_管理領域は無視(self, directory: str) -> None:
        path = self.ROOT / directory / "メモ.md"
        assert classify_event(self.ROOT, "modified", path, False) is None

    def test_添付フォルダは無視(self) -> None:
        path = self.ROOT / "attachments" / "図.md"
        assert classify_event(self.ROOT, "modified", path, False) is None

    def test_雛形のフォルダは無視(self) -> None:
        """E-4 の回帰。**雛形はノートではない。**

        走査（`Vault.scan`）では除いていたのに、こちらで拾って索引へ
        入れていた。一覧に雛形が 3 つ並び、開いて書き換えられた。
        """
        path = self.ROOT / "templates" / "議事録.md"
        assert classify_event(self.ROOT, "created", path, False) is None

    def test_除くフォルダの一覧が走査と同じ(self) -> None:
        """**2 か所に書かない。** 片方だけ直したのが上のバグの原因。"""
        from hitofude.storage import watcher
        from hitofude.storage.vault import SKIP_DIRS

        assert watcher.SKIP_DIRS is SKIP_DIRS

    def test_vaultの外は無視(self) -> None:
        assert classify_event(self.ROOT, "modified", Path("/other/メモ.md"), False) is None


class TestDecide:
    """spec §7.5 の競合解決の分岐。"""

    def base(self, **kwargs):
        args = {
            "exists": True,
            "disk_mtime_ns": 100,
            "disk_digest": "AAA",
            "loaded_mtime_ns": 100,
            "loaded_digest": "AAA",
            "dirty": False,
        }
        return decide(**{**args, **kwargs})

    def test_外部で変わっていなければそのまま書く(self) -> None:
        assert self.base() is ConflictAction.WRITE

    def test_編集中でも外部が変わっていなければ書く(self) -> None:
        assert self.base(dirty=True) is ConflictAction.WRITE

    def test_mtimeだけ変わって中身が同じなら書く(self) -> None:
        """touch されただけ、あるいは同じ内容で保存された場合。"""
        assert self.base(disk_mtime_ns=200) is ConflictAction.WRITE

    def test_外部で変わり自分は未編集ならリロード(self) -> None:
        got = self.base(disk_mtime_ns=200, disk_digest="BBB", dirty=False)
        assert got is ConflictAction.RELOAD

    def test_外部で変わり自分も編集中なら聞く(self) -> None:
        got = self.base(disk_mtime_ns=200, disk_digest="BBB", dirty=True)
        assert got is ConflictAction.ASK

    def test_外部で消されたら聞く(self) -> None:
        assert self.base(exists=False) is ConflictAction.RECREATE


class TestCheckConflict:
    @pytest.fixture
    def vault(self, tmp_path: Path) -> Vault:
        target = Vault(tmp_path / "HitofudeNotes")
        target.ensure_layout()
        return target

    def test_書いた直後は競合しない(self, vault) -> None:
        note = vault.create("メモ", "本文\n")
        assert check_conflict(note, dirty=True) is ConflictAction.WRITE

    def test_外部で書き換えられたら検知する(self, vault) -> None:
        note = vault.create("メモ", "本文\n")
        note.path.write_text("外から書き換えた\n", encoding="utf-8")
        assert check_conflict(note, dirty=True) is ConflictAction.ASK

    def test_未編集なら黙ってリロード(self, vault) -> None:
        note = vault.create("メモ", "本文\n")
        note.path.write_text("外から書き換えた\n", encoding="utf-8")
        assert check_conflict(note, dirty=False) is ConflictAction.RELOAD

    def test_消されたら検知する(self, vault) -> None:
        note = vault.create("メモ", "本文\n")
        note.path.unlink()
        assert check_conflict(note, dirty=True) is ConflictAction.RECREATE

    def test_同じ内容で書き換えられても競合にしない(self, vault) -> None:
        """内容が同じなら知らせる意味がない。"""
        note = vault.create("メモ", "本文\n")
        note.path.write_text(note.text, encoding="utf-8")
        assert check_conflict(note, dirty=True) is ConflictAction.WRITE


class TestKeepBoth:
    """spec §7.5: 「両方残す」= `ファイル名 (競合 2026-08-08).md` を作る。"""

    def test_競合ファイル名を作る(self, tmp_path: Path) -> None:
        got = keep_both_path(tmp_path / "会議メモ.md", date="2026-08-08")
        assert got.name == "会議メモ (競合 2026-08-08).md"

    def test_同じ日に2度目なら連番が付く(self, tmp_path: Path) -> None:
        first = keep_both_path(tmp_path / "会議メモ.md", date="2026-08-08")
        first.write_text("x", encoding="utf-8")
        second = keep_both_path(tmp_path / "会議メモ.md", date="2026-08-08")
        assert second.name == "会議メモ (競合 2026-08-08)-2.md"

    def test_日付を省略すると今日になる(self, tmp_path: Path) -> None:
        from datetime import date as date_type

        got = keep_both_path(tmp_path / "メモ.md")
        assert date_type.today().isoformat() in got.name


@pytest.mark.gui
@pytest.mark.slow
class TestVaultWatcherIntegration:
    """実際の watchdog を動かして Qt シグナルまで届くことを見る。

    純関数側のテストは翻訳規則しか見ていないので、配線の確認がここに要る。
    ファイルシステムのイベントは遅延するため slow 扱い。
    """

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Vault:
        target = Vault(tmp_path / "HitofudeNotes")
        target.ensure_layout()
        return target

    @pytest.fixture
    def watcher(self, vault: Vault, qapp):
        from hitofude.storage.watcher import VaultWatcher

        instance = VaultWatcher(vault)
        instance.start()
        yield instance
        instance.stop()

    def test_外部での書き換えがシグナルになる(self, qtbot, vault, watcher) -> None:
        note = vault.create("メモ", "本文\n")
        received: list = []
        watcher.changed.connect(lambda kind, path: received.append((kind, path)))
        qtbot.wait(500)
        watcher.poll()
        received.clear()

        note.path.write_text("外から書き換えた\n", encoding="utf-8")

        def arrived() -> bool:
            watcher.poll()
            return bool(received)

        qtbot.waitUntil(arrived, timeout=10000)
        assert Path(received[0][1]).name == "メモ.md"

    def test_自分の保存は通知されない(self, qtbot, vault, watcher) -> None:
        """spec §7.5: 抑制リストが無いと保存のたびにリロードが走る。"""
        note = vault.create("メモ", "本文\n")
        qtbot.wait(500)
        watcher.poll()  # 作成時のイベントを流し切る

        received: list = []
        watcher.changed.connect(lambda kind, path: received.append((kind, path)))

        watcher.suppress(note.path)
        vault.write(note.path, "自分で書いた\n")
        qtbot.wait(1000)
        watcher.poll()
        assert received == [], "自分の保存が外部変更として通知された"

    def test_停止できる(self, vault, qapp) -> None:
        from hitofude.storage.watcher import VaultWatcher

        instance = VaultWatcher(vault)
        instance.start()
        assert instance.running is True
        instance.stop()
        assert instance.running is False


class TestShutdown:
    """**終了する前に必ず監視を止める。**

    macOS のクラッシュレポートに、`FSEventStreamCallback` が
    `PyGILState_Ensure` を呼んで落ちているものが 2 件残っていた。その時
    メインスレッドは既に `exit()` の後（C++ の後片付け中）で、Python は
    もう動いていない。**監視が生きたままプロセスが終わる**と起きる。

    止め忘れを責めても再発は防げないので、終了直前にまとめて止める。
    """

    @pytest.fixture
    def vault(self, tmp_path):
        from hitofude.storage.vault import Vault

        return Vault(tmp_path / "V")

    def test_始めたら登録される(self, vault, qapp) -> None:
        from hitofude.storage import watcher as module

        instance = module.VaultWatcher(vault)
        instance.start()
        try:
            assert instance in module.live_watchers()
        finally:
            instance.stop()

    def test_止めれば外れる(self, vault, qapp) -> None:
        from hitofude.storage import watcher as module

        instance = module.VaultWatcher(vault)
        instance.start()
        instance.stop()
        assert instance not in module.live_watchers()

    def test_止め忘れても終了前に止まる(self, vault, qapp) -> None:
        from hitofude.storage import watcher as module

        instance = module.VaultWatcher(vault)
        instance.start()
        module.stop_all()
        assert instance.running is False

    def test_タイマが先に消えていても監視は止める(self, vault, qapp) -> None:
        """**止める順で守りが空振りしていた**（2026-08-26 に気づいた）。

        後片付けの途中で Qt の側が先に消えると `self._timer.stop()` が
        `RuntimeError` を投げ、**その先の `observer.stop()` まで届かない**。
        止め忘れた監視スレッドは終了時の segfault に直結するので、
        ここが空振りすると `stop_all` を置いた意味が無くなる。
        """
        from hitofude.storage import watcher as module

        instance = module.VaultWatcher(vault)
        instance.start()

        class Gone:
            def stop(self) -> None:
                raise RuntimeError("Internal C++ object already deleted")

        instance._timer = Gone()
        instance.stop()
        assert instance.running is False
        assert instance not in module.live_watchers()

    def test_止まらなければ記録を残す(self, vault, qapp, caplog) -> None:
        """**黙って諦めない。** 次に落ちたときの手掛かりになる。"""
        from hitofude.storage import watcher as module

        instance = module.VaultWatcher(vault)
        instance.start()

        class Stubborn:
            def stop(self) -> None: ...
            def join(self, timeout=None) -> None: ...
            def is_alive(self) -> bool:
                return True

        real = instance._observer
        instance._observer = Stubborn()
        try:
            instance.stop()
            assert "止まらなかった" in caplog.text
        finally:
            real.stop()
            real.join(timeout=2.0)


class TestNormalizeEventPath:
    """FSEvents の実パス報告を vault の表記へ写す（H-2）。

    macOS の FSEvents はシンボリックリンクを解決した実パスで報告する
    （/tmp → /private/tmp、別名リンク → 実体。実測）。root がリンク経由だと
    受信パスが root 配下に見えず、外部変更の検知が全滅していた。
    """

    def test_実パスをroot表記へ写す(self) -> None:
        from hitofude.storage.watcher import normalize_event_path

        root = Path("/var/tmp/別名")
        real = Path("/private/var/tmp/実体")
        got = normalize_event_path(Path("/private/var/tmp/実体/メモ.md"), root, real)
        assert got == Path("/var/tmp/別名/メモ.md")

    def test_rootが実パスなら何もしない(self) -> None:
        from hitofude.storage.watcher import normalize_event_path

        root = Path("/private/var/tmp/Vault")
        got = normalize_event_path(Path("/private/var/tmp/Vault/メモ.md"), root, root)
        assert got == Path("/private/var/tmp/Vault/メモ.md")

    def test_realの外はそのまま返す(self) -> None:
        from hitofude.storage.watcher import normalize_event_path

        root = Path("/var/tmp/別名")
        real = Path("/private/var/tmp/実体")
        outside = Path("/private/var/tmp/無関係/メモ.md")
        assert normalize_event_path(outside, root, real) == outside


@pytest.mark.gui
@pytest.mark.slow
class TestSymlinkedVault:
    """リンク経由の vault でも外部変更を検知する（H-2 の統合検査）。

    実測: 別名リンク越しに開いた vault では FSEvents の報告パスが
    root 配下に見えず、発火が 0 件だった。
    """

    def test_別名リンク経由でも外部変更が届く(self, qtbot, tmp_path, qapp) -> None:
        from hitofude.storage.watcher import VaultWatcher

        real = tmp_path / "実体Vault"
        real.mkdir()
        alias = tmp_path / "別名"
        alias.symlink_to(real)

        vault = Vault(alias)
        vault.ensure_layout()
        watcher = VaultWatcher(vault)
        watcher.start()
        try:
            received: list = []
            watcher.changed.connect(lambda kind, path: received.append((kind, Path(path))))
            qtbot.wait(500)
            watcher.poll()
            received.clear()

            # 外部エディタは実パス側で書くこともある
            (real / "外部.md").write_text("# 外部\n", encoding="utf-8")

            def arrived() -> bool:
                watcher.poll()
                return bool(received)

            qtbot.waitUntil(arrived, timeout=10000)
            # 届くパスは vault の表記（別名側）。root 基準の relative_to が
            # 成立しないと、上流（index の upsert 等）が全部壊れる
            assert received[0][1] == alias / "外部.md"
        finally:
            watcher.stop()
