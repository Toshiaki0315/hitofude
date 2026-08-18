"""保存とデバウンスのテスト（タスク 4-3, 4-4 / spec §7.4）。"""

from pathlib import Path

import pytest

from hitofude.storage.autosave import (
    DEBOUNCE_SECONDS,
    Debouncer,
    save_atomic,
    save_bytes_atomic,
)


class TestSaveAtomic:
    def test_書いた内容が読める(self, tmp_path: Path) -> None:
        target = tmp_path / "メモ.md"
        save_atomic(target, "本文\n")
        assert target.read_text(encoding="utf-8") == "本文\n"

    def test_上書きできる(self, tmp_path: Path) -> None:
        target = tmp_path / "メモ.md"
        save_atomic(target, "古い\n")
        save_atomic(target, "新しい\n")
        assert target.read_text(encoding="utf-8") == "新しい\n"

    def test_一時ファイルを残さない(self, tmp_path: Path) -> None:
        save_atomic(tmp_path / "メモ.md", "本文\n")
        assert [p.name for p in tmp_path.iterdir()] == ["メモ.md"]

    def test_親ディレクトリを作る(self, tmp_path: Path) -> None:
        target = tmp_path / "深い" / "階層" / "メモ.md"
        save_atomic(target, "本文\n")
        assert target.is_file()

    def test_改行はLFで書く(self, tmp_path: Path) -> None:
        """spec §7.2: 改行コードは LF 固定。"""
        target = tmp_path / "メモ.md"
        save_atomic(target, "一行目\n二行目\n")
        assert b"\r\n" not in target.read_bytes()

    def test_日本語をUTF8で書く(self, tmp_path: Path) -> None:
        target = tmp_path / "メモ.md"
        save_atomic(target, "日本語\n")
        assert target.read_bytes() == "日本語\n".encode()

    def test_書き込みが失敗したら一時ファイルを片付ける(self, tmp_path: Path, monkeypatch) -> None:
        """失敗の痕跡が vault に残るとユーザーから見えるゴミになる。"""
        target = tmp_path / "メモ.md"

        def boom(*args, **kwargs):
            raise OSError("ディスクが一杯")

        monkeypatch.setattr("os.fsync", boom)
        with pytest.raises(OSError):
            save_atomic(target, "本文\n")
        assert list(tmp_path.iterdir()) == []

    def test_失敗しても元の内容は壊れない(self, tmp_path: Path, monkeypatch) -> None:
        """アトミック書き込みの核心。"""
        target = tmp_path / "メモ.md"
        save_atomic(target, "無事な内容\n")

        monkeypatch.setattr("os.fsync", lambda *a: (_ for _ in ()).throw(OSError("失敗")))
        with pytest.raises(OSError):
            save_atomic(target, "壊れた書き込み\n")
        assert target.read_text(encoding="utf-8") == "無事な内容\n"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestDebouncer:
    @pytest.fixture
    def clock(self) -> FakeClock:
        return FakeClock()

    @pytest.fixture
    def debouncer(self, clock: FakeClock) -> Debouncer:
        return Debouncer(clock=clock)

    def test_既定は800ミリ秒(self) -> None:
        assert pytest.approx(0.8) == DEBOUNCE_SECONDS

    def test_変更が無ければ書かない(self, debouncer) -> None:
        assert debouncer.pending is False
        assert debouncer.due() is False

    def test_時間が経つまで書かない(self, debouncer, clock) -> None:
        debouncer.touch()
        clock.advance(0.5)
        assert debouncer.due() is False

    def test_時間が経てば書く(self, debouncer, clock) -> None:
        debouncer.touch()
        clock.advance(0.8)
        assert debouncer.due() is True

    def test_打鍵のたびに待ち直す(self, debouncer, clock) -> None:
        """入力が続いている間は書かない。これがデバウンスの目的。"""
        debouncer.touch()
        for _ in range(10):
            clock.advance(0.5)
            debouncer.touch()
            assert debouncer.due() is False
        # 0.5 の足し込みで誤差が乗るため、境界ちょうどではなく余裕を持って進める
        clock.advance(1.0)
        assert debouncer.due() is True

    def test_書いたら待ちが解除される(self, debouncer, clock) -> None:
        debouncer.touch()
        clock.advance(1.0)
        debouncer.clear()
        assert debouncer.pending is False
        assert debouncer.due() is False

    def test_残り時間を教える(self, debouncer, clock) -> None:
        debouncer.touch()
        clock.advance(0.3)
        assert debouncer.remaining() == pytest.approx(0.5)

    def test_期限を過ぎたら残りはゼロ(self, debouncer, clock) -> None:
        debouncer.touch()
        clock.advance(5.0)
        assert debouncer.remaining() == 0.0


class TestRecovery:
    """クラッシュリカバリ（タスク 6-6 / spec §9 Phase 6）。"""

    def test_退避先はApplicationSupportの下(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import recovery_root

        got = recovery_root(Path("/vault"), home=tmp_path)
        expected = tmp_path / "Library" / "Application Support" / "Hitofude" / "recovery"
        assert got.parent == expected

    def test_退避先はvaultごとに分かれる(self, tmp_path: Path) -> None:
        """別の保管フォルダの未保存内容が出てくると混乱する。"""
        from hitofude.storage.autosave import recovery_root

        first = recovery_root(Path("/vault/A"), home=tmp_path)
        second = recovery_root(Path("/vault/B"), home=tmp_path)
        assert first != second

    def test_退避して拾える(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import pending, stash

        stash(tmp_path, Path("/vault/メモ.md"), "未保存の本文\n")
        found = pending(tmp_path)
        assert len(found) == 1
        assert found[0].source == Path("/vault/メモ.md")
        assert found[0].text == "未保存の本文\n"

    def test_同じノートは上書きする(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import pending, stash

        stash(tmp_path, Path("/vault/メモ.md"), "古い")
        stash(tmp_path, Path("/vault/メモ.md"), "新しい")
        found = pending(tmp_path)
        assert len(found) == 1
        assert found[0].text == "新しい"

    def test_別のノートは別に退避される(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import pending, stash

        stash(tmp_path, Path("/vault/A.md"), "あ")
        stash(tmp_path, Path("/vault/B.md"), "い")
        assert len(pending(tmp_path)) == 2

    def test_捨てられる(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import discard, pending, stash

        stash(tmp_path, Path("/vault/メモ.md"), "本文")
        discard(tmp_path, Path("/vault/メモ.md"))
        assert pending(tmp_path) == []

    def test_無いものを捨てても壊れない(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import discard

        discard(tmp_path, Path("/vault/存在しない.md"))

    def test_退避先が無ければ空(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import pending

        assert pending(tmp_path / "まだ無い") == []

    def test_壊れた退避は飛ばす(self, tmp_path: Path) -> None:
        """読めない退避のせいで起動できなくなってはいけない。"""
        from hitofude.storage.autosave import pending, stash

        stash(tmp_path, Path("/vault/正常.md"), "本文")
        (tmp_path / "こわれた.source").write_text("/vault/欠けている.md", encoding="utf-8")
        assert [s.source.name for s in pending(tmp_path)] == ["正常.md"]

    def test_本文はそのまま読める形で置く(self, tmp_path: Path) -> None:
        """復元の仕組みが壊れても手で救い出せること。"""
        from hitofude.storage.autosave import stash

        target = stash(tmp_path, Path("/vault/メモ.md"), "手で読める本文\n")
        assert target.suffix == ".md"
        assert target.read_text(encoding="utf-8") == "手で読める本文\n"


class TestSaveBytes:
    """画像などバイト列の保存（タスク A-2）。テキストと同じ約束で書く。"""

    def test_書ける(self, tmp_path: Path) -> None:
        target = tmp_path / "画像.png"
        save_bytes_atomic(target, b"\x89PNG\r\n")
        assert target.read_bytes() == b"\x89PNG\r\n"

    def test_改行を変換しない(self, tmp_path: Path) -> None:
        """テキストと違い `\\r\\n` はデータの一部。触ると画像が壊れる。"""
        target = tmp_path / "画像.png"
        save_bytes_atomic(target, b"a\r\nb")
        assert target.read_bytes() == b"a\r\nb"

    def test_親フォルダを作る(self, tmp_path: Path) -> None:
        target = tmp_path / "深い" / "階層" / "画像.png"
        save_bytes_atomic(target, b"data")
        assert target.is_file()

    def test_失敗したら一時ファイルを残さない(self, tmp_path: Path, monkeypatch) -> None:
        import os

        def explode(fileno: int) -> None:
            raise OSError("書けない")

        monkeypatch.setattr(os, "fsync", explode)
        target = tmp_path / "画像.png"
        with pytest.raises(OSError):
            save_bytes_atomic(target, b"data")
        assert list(tmp_path.iterdir()) == []


class TestBrokenStash:
    def test_不正なバイト列の退避は飛ばす(self, tmp_path: Path) -> None:
        """「壊れた退避は黙って飛ばす」の約束が UnicodeDecodeError には
        効いていなかった（except が OSError のみ。回帰）。"""
        from hitofude.storage.autosave import pending, stash

        stash(tmp_path, Path("/vault/正常.md"), "本文")
        (tmp_path / "こわれた.source").write_text("/vault/壊.md", encoding="utf-8")
        (tmp_path / "こわれた.stash").write_bytes(b"\x8c\xf0\xff")

        assert [s.source.name for s in pending(tmp_path)] == ["正常.md"]

    def test_サブディレクトリがあっても全消しできる(self, tmp_path: Path) -> None:
        from hitofude.storage.autosave import clear_all, stash

        stash(tmp_path, Path("/vault/メモ.md"), "本文")
        (tmp_path / "手で作った入れ物").mkdir()

        clear_all(tmp_path)  # IsADirectoryError で落ちない
        assert not list(tmp_path.glob("*.stash"))
