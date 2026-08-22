"""画像を文字にする（ADR-0027）。

読み手は 2 つ（macOS の Vision / 手元の LLM）。**ここは Qt を知らない**（R3）。
外の道具（同梱の実行ファイル・Ollama）は差し替えられるようにしてあり、
テストで実物を動かさない。
"""

from pathlib import Path

import pytest

from hitofude.core import ocr


class FakeRunner:
    """同梱の実行ファイルを呼んだことにする。"""

    def __init__(self, output: str = "読み取った文字", code: int = 0) -> None:
        self.output = output
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], timeout: float):
        self.calls.append(args)
        if self.code:
            raise OSError("動かなかった")
        return self.output


class FakeLLM:
    def __init__(self, answer: str = "読み取った文字") -> None:
        self.answer = answer
        self.images: list[bytes] = []

    def available(self) -> bool:
        return True

    def generate(self, prompt, *, images=None, on_chunk=None, should_stop=None) -> str:
        self.images.extend(images or [])
        return self.answer


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "写真.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


class TestMacEngine:
    def test_読み取れる(self, image) -> None:
        runner = FakeRunner("会議メモ\n予算の話")
        found = ocr.MacEngine(tool=Path("/usr/local/bin/hitofude-ocr"), runner=runner)
        assert found.read(image) == "会議メモ\n予算の話"

    def test_画像の場所を渡す(self, image) -> None:
        runner = FakeRunner()
        ocr.MacEngine(tool=Path("/tool"), runner=runner).read(image)
        assert runner.calls[0][-1] == str(image)

    def test_道具が無ければ使えない(self, tmp_path) -> None:
        """**押してから断らない**（G-3 と同じ作法）。"""
        found = ocr.MacEngine(tool=tmp_path / "無い", runner=FakeRunner())
        assert found.available() is False

    def test_道具があれば使える(self, tmp_path) -> None:
        tool = tmp_path / "hitofude-ocr"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
        assert ocr.MacEngine(tool=tool, runner=FakeRunner()).available() is True

    def test_動かなければ知らせる(self, image, tmp_path) -> None:
        found = ocr.MacEngine(tool=Path("/tool"), runner=FakeRunner(code=1))
        with pytest.raises(ocr.Unavailable):
            found.read(image)


class TestLlmEngine:
    def test_読み取れる(self, image) -> None:
        found = ocr.LlmEngine(client=FakeLLM("会議メモ"))
        assert found.read(image) == "会議メモ"

    def test_画像を渡す(self, image) -> None:
        """**中身を渡す。** パスを渡してもモデルは開けない。"""
        client = FakeLLM()
        ocr.LlmEngine(client=client).read(image)
        assert client.images == [image.read_bytes()]

    def test_読めないモデルなら知らせる(self, image) -> None:
        """画像を見られないモデルは、何も返さないか説明を返す。"""
        found = ocr.LlmEngine(client=FakeLLM("   "))
        with pytest.raises(ocr.Unavailable):
            found.read(image)


class TestEngineChoice:
    def test_名前で選べる(self) -> None:
        assert ocr.Engine("mac") is ocr.Engine.MAC
        assert ocr.Engine("llm") is ocr.Engine.LLM

    def test_既定はmacOS(self) -> None:
        """**速くて正確**（実測 0.85 秒／誤りゼロ。ADR-0027）。"""
        assert ocr.DEFAULT_ENGINE is ocr.Engine.MAC


class TestCleanup:
    """読み取った文字をノートにする前の手当て。"""

    def test_前後の空白を落とす(self) -> None:
        assert ocr.tidy("  会議メモ  \n\n") == "会議メモ"

    def test_行の中の余分な空白は残す(self) -> None:
        """**勝手に整形しない。** 表や字下げが崩れる。"""
        assert ocr.tidy("  a  b") == "a  b"

    def test_3行以上の空行は畳む(self) -> None:
        assert ocr.tidy("上\n\n\n\n下") == "上\n\n下"
