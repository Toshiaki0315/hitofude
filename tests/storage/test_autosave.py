"""保存とデバウンスのテスト（タスク 4-3, 4-4 / spec §7.4）。"""

from pathlib import Path

import pytest

from hitofude.storage.autosave import DEBOUNCE_SECONDS, Debouncer, save_atomic


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
