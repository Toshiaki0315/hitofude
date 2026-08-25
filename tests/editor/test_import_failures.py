"""取り込みが壊れたときの道（カバレッジの穴を埋める 2026-08-25）。

うまくいく道は `test_import_samples.py` と `test_importer.py` が見ている。
**壊れたときの道が 1 つも通っていなかった**（実測 87%）——取り消し、
壊れた PDF、1 ページだけ読めない、読み手が例外を投げる。

**どれも「落ちずに済ませる」ための分岐**なので、通っていないと
守れているかどうか分からない。取り消しは背景スレッド化（2026-08-25）で
入ったばかりで、**効いていなければ窓を閉じても読み続ける**。
"""

from pathlib import Path

import pytest

from hitofude.editor import importer

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"


class Boom:
    """読み取り役が必ず転ぶ。"""

    def available(self) -> bool:
        return True

    def read(self, image: Path) -> str:
        raise RuntimeError("読み取り役が転んだ")


class Reader:
    def __init__(self, text: str = "読み取った文字です。") -> None:
        self.text = text
        self.count = 0

    def available(self) -> bool:
        return True

    def read(self, image: Path) -> str:
        self.count += 1
        return self.text


def sample(name: str) -> Path:
    path = SAMPLES / name
    assert path.is_file(), f"{path} が無い"
    return path


class TestCancel:
    """**途中でやめられる。** 窓を閉じたあともページを読み続けない。"""

    def test_合図が立てば止まる(self) -> None:
        with pytest.raises(importer.Cancelled):
            importer.to_markdown(
                sample("会議メモ-スキャン.pdf"), ocr=Reader(), should_stop=lambda: True
            )

    def test_立たなければ最後まで読む(self) -> None:
        found = importer.to_markdown(
            sample("会議メモ-スキャン.pdf"), ocr=Reader(), should_stop=lambda: False
        )
        assert found.strip()

    def test_画像でも止まる(self) -> None:
        with pytest.raises(importer.Cancelled):
            importer.to_markdown(sample("会議メモ.png"), ocr=Reader(), should_stop=lambda: True)

    def test_読む前に見る(self) -> None:
        """**読んでから合図を見るのでは遅い。** 1 枚 0.85 秒（ADR-0027）
        かかるので、読み終えてから止めても待たされる。
        """
        reader = Reader()
        with pytest.raises(importer.Cancelled):
            importer.to_markdown(
                sample("会議メモ-スキャン.pdf"), ocr=reader, should_stop=lambda: True
            )
        assert reader.count == 0, "止めたのに読んでいる"


class TestProgress:
    """**何ページ目かを伝える。** 待つ側に進み具合が見える。"""

    def test_ページごとに知らせる(self) -> None:
        seen: list[tuple[int, int]] = []
        importer.to_markdown(
            sample("会議メモ.png"),
            ocr=Reader(),
            on_page=lambda done, total: seen.append((done, total)),
        )
        assert seen == [(1, 1)]

    def test_スキャンでもページ数が合う(self) -> None:
        seen: list[tuple[int, int]] = []
        importer.to_markdown(
            sample("会議メモ-スキャン.pdf"),
            ocr=Reader(),
            on_page=lambda done, total: seen.append((done, total)),
        )
        assert seen, "1 度も知らせなかった"
        assert seen[-1][0] == seen[-1][1]  # 最後は「N / N」


class TestReaderFails:
    """**読み手が転んでも落ちない。** 道具が無い・モデルが違う。"""

    def test_画像なら空を返す(self) -> None:
        assert importer.to_markdown(sample("会議メモ.png"), ocr=Boom()).strip() == ""

    def test_混在なら読めたページは残す(self) -> None:
        """**読めないページのせいで全部を失わない**（ADR-0027 の 3）。"""
        found = importer.to_markdown(sample("会議メモ-混在.pdf"), ocr=Boom())
        assert "1 枚目は文字として入っています" in found


class TestBrokenPdf:
    """**壊れた PDF・暗号化。** 画像を取り出せなくても本文は諦めない。"""

    def test_画像は空で返す(self, tmp_path: Path) -> None:
        broken = tmp_path / "壊れた.pdf"
        broken.write_text("%PDF-1.4\nこれは PDF ではない\n", encoding="utf-8")
        assert importer.pdf_images(broken) == {}

    def test_中身が空でも落ちない(self, tmp_path: Path) -> None:
        empty = tmp_path / "空.pdf"
        empty.write_bytes(b"")
        assert importer.pdf_images(empty) == {}


class TestUnreadablePage:
    """**1 ページの故障で全部を諦めない。**"""

    def test_読めないページは飛ばす(self, monkeypatch) -> None:
        """**`PdfReader` は関数の中で import している**（起動を軽くするため）
        ので、差し替えるのは `pypdf` 側。
        """
        import pypdf

        real = pypdf.PdfReader

        class OnePageBroken:
            """1 ページ目だけ画像が読めない PDF のふり。"""

            def __init__(self, path: str) -> None:
                self._pages = list(real(path).pages)

            @property
            def pages(self):
                class Broken:
                    @property
                    def images(self):
                        raise RuntimeError("このページの画像は読めない")

                return [Broken(), *self._pages[1:]]

        monkeypatch.setattr(pypdf, "PdfReader", OnePageBroken)
        # 落ちずに戻る（1 ページ目は飛ばされる）
        assert 0 not in importer.pdf_images(sample("会議メモ-混在.pdf"))
