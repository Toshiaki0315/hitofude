"""`samples/` の実物を読み込む（手動チェックの自動化 2026-08-25）。

**同じ内容を 5 つの形で出したもの**が `samples/` にある（README 参照）。
手で読み込んで見比べる項目になっていたが、**切り分けの筋道は機械で
確かめられる** — どのページが読み取りに回り、図がどこへ行くか。

**読み取り役は作り物を渡す。** 本物（`hitofude/resources/bin/hitofude-ocr`）は
`make ocr-tool` が作るもので git に入っていない（ADR-0027）。無い環境でも
この試験は動く必要がある。**読み取りの精度は人が見るもの**で、ここで
見るのは**どこへ回すか**。
"""

from pathlib import Path

import pytest

from hitofude.editor import importer

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"


class FakeReader:
    """読み取ったことにする。**何回・どの絵を渡されたか**を覚える。"""

    def __init__(self, text: str = "読み取った文字がここに入ります。") -> None:
        self.text = text
        self.images: list[Path] = []

    def available(self) -> bool:
        return True

    def read(self, image: Path) -> str:
        self.images.append(image)
        return self.text


class MissingReader:
    """読み取り役が使えない状態（同梱の実行ファイルが無い・Ollama が居ない）。"""

    def available(self) -> bool:
        return False

    def read(self, image: Path) -> str:  # pragma: no cover - 呼ばれない
        raise AssertionError("使えないのに呼ばれた")


@pytest.fixture
def attachments(tmp_path: Path):
    """保存した絵を覚える。**本文に出る URL を返す**（`save_attachment` と同じ形）。"""
    saved: list[str] = []

    def save(data: bytes, suffix: str) -> str | None:
        # **本物と同じ契約**（`Vault.attachment_link`）。URL だけを返すと
        # 本文に生の文字列が並ぶ——最初そう書いて試験が落ちた
        path = tmp_path / f"絵{len(saved)}{suffix}"
        path.write_bytes(data)
        saved.append(path.name)
        return f"![](attachments/{path.name})"

    save.saved = saved
    return save


def sample(name: str) -> Path:
    path = SAMPLES / name
    assert path.is_file(), f"{path} が無い（scripts/make_import_samples.py で作れる）"
    return path


class TestTextPdf:
    """文字の入った PDF は**読み取りに回さない**（速くて正確なほうを捨てない）。"""

    def test_読み取りを呼ばない(self) -> None:
        reader = FakeReader()
        found = importer.to_markdown(sample("会議メモ.pdf"), ocr=reader)
        assert reader.images == []
        assert "会議メモ" in found

    def test_中身がそのまま出る(self) -> None:
        found = importer.to_markdown(sample("会議メモ.pdf"), ocr=FakeReader())
        assert "予算" in found


class TestScannedPdf:
    """絵だけの PDF は**ページごとに読み取りに回る**。"""

    def test_全ページ読み取りに回る(self) -> None:
        reader = FakeReader()
        found = importer.to_markdown(sample("会議メモ-スキャン.pdf"), ocr=reader)
        assert reader.images, "読み取りに回らなかった"
        assert reader.text in found

    def test_紙の写真は添付しない(self, attachments) -> None:
        """**読み取った文字と二重になる。** そのページの絵はページそのもの。"""
        importer.to_markdown(
            sample("会議メモ-スキャン.pdf"), save_image=attachments, ocr=FakeReader()
        )
        assert attachments.saved == []


class TestFigures:
    """文字と図が同じページ（ADR-0027 の追記）。"""

    def test_図が添付される(self, attachments) -> None:
        found = importer.to_markdown(
            sample("会議メモ-図つき.pdf"), save_image=attachments, ocr=FakeReader()
        )
        assert attachments.saved, "図が保存されなかった"
        assert "![](attachments/" in found

    def test_読み取りには回らない(self) -> None:
        """そのページには文字がある。**両方読むと二重になる。**"""
        reader = FakeReader()
        importer.to_markdown(sample("会議メモ-図つき.pdf"), ocr=reader)
        assert reader.images == []


class TestMixedPdf:
    """1 枚目は文字・2 枚目は絵。**ページごとに切り分ける**（ユーザー報告で直した）。"""

    def test_どちらのページも中身が入る(self) -> None:
        reader = FakeReader("二枚目から読み取った文字です。")
        found = importer.to_markdown(sample("会議メモ-混在.pdf"), ocr=reader)
        assert "1 枚目は文字として入っています" in found, "1 枚目の文字が落ちた"
        assert reader.text in found, "2 枚目が落ちた"

    def test_絵のページだけ読み取る(self) -> None:
        reader = FakeReader("二枚目から読み取った文字です。")
        importer.to_markdown(sample("会議メモ-混在.pdf"), ocr=reader)
        assert len(reader.images) == 1


class TestImages:
    """画像そのもの（PNG / JPEG）は丸ごと読み取りに回る。"""

    @pytest.mark.parametrize("name", ["会議メモ.png", "会議メモ.jpg"])
    def test_読み取りに回る(self, name: str) -> None:
        reader = FakeReader()
        found = importer.to_markdown(sample(name), ocr=reader)
        assert len(reader.images) == 1
        assert reader.text in found


class TestUnavailable:
    """読み取りができない状態。**空のノートを作らない。**"""

    @pytest.mark.parametrize("name", ["会議メモ.png", "会議メモ-スキャン.pdf"])
    def test_読み取れなければ空を返す(self, name: str) -> None:
        assert importer.to_markdown(sample(name), ocr=MissingReader()).strip() == ""

    def test_読み取り役が無くても空(self) -> None:
        assert importer.to_markdown(sample("会議メモ.png"), ocr=None).strip() == ""

    def test_文字の入った_PDF_は読み取り役が無くても読める(self) -> None:
        """**読み取りができなくても、文字のあるページは失わない。**"""
        found = importer.to_markdown(sample("会議メモ.pdf"), ocr=MissingReader())
        assert "予算" in found


class TestPowerPoint:
    """PowerPoint は構造のまま読む（表が表として戻る唯一の道）。"""

    def test_表のまま入る(self) -> None:
        found = importer.to_markdown(sample("会議メモ.pptx"))
        assert "|" in found, found[:200]
