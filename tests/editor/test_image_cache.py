"""本文に描く画像の読み込みとキャッシュ（タスク A-2 後半）。

毎フレーム読み込み直すと 3024x1964 の PNG で 21ms かかり、§6.6 の
16ms を超える。縮小結果を持ち回れば 0.05ms。**キャッシュは必須要件**。
"""

from pathlib import Path

import pytest

from hitofude.editor.image_cache import ImageCache

pytestmark = pytest.mark.gui


@pytest.fixture
def cache(qapp, tmp_path: Path) -> ImageCache:
    return ImageCache(tmp_path)


class TestLoading:
    def test_読める(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path / "attachments" / "a.png")
        assert cache.pixmap("attachments/a.png", 720) is not None

    def test_無ければNone(self, cache) -> None:
        assert cache.pixmap("attachments/居ない.png", 720) is None

    def test_画像でないファイルはNone(self, cache, tmp_path, write_png) -> None:
        (tmp_path / "資料.pdf").write_bytes(b"%PDF-1.4")
        assert cache.pixmap("資料.pdf", 720) is None

    def test_大きい画像は幅に収める(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path / "big.png", 3000, 2000)
        pixmap = cache.pixmap("big.png", 720)
        assert pixmap.width() == 720

    def test_縦横比を保つ(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path / "big.png", 3000, 1500)
        pixmap = cache.pixmap("big.png", 720)
        assert pixmap.height() == pytest.approx(360, abs=2)

    def test_小さい画像は拡大しない(self, cache, tmp_path, write_png) -> None:
        """40px の絵を 720px に引き伸ばすとぼやけるだけ。"""
        write_png(tmp_path / "small.png", 40, 20)
        pixmap = cache.pixmap("small.png", 720)
        assert pixmap.width() == 40

    def test_サイズだけ先に引ける(self, cache, tmp_path, write_png) -> None:
        """行の高さを決めるのに使う。ハイライタから毎回呼ばれる。"""
        write_png(tmp_path / "a.png", 200, 100)
        assert cache.size("a.png", 720) == (200, 100)

    def test_無い画像のサイズはNone(self, cache) -> None:
        assert cache.size("居ない.png", 720) is None


class TestOutsideVault:
    """本文は手で編集できる。保管フォルダの外を読みに行かない。"""

    def test_親をたどるパスは読まない(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path.parent / "外.png")
        assert cache.pixmap("../外.png", 720) is None

    def test_絶対パスは読まない(self, cache, tmp_path, write_png) -> None:
        outside = write_png(tmp_path.parent / "外2.png")
        assert cache.pixmap(str(outside), 720) is None

    def test_httpは読みに行かない(self, cache) -> None:
        """描画のたびに通信しない。"""
        assert cache.pixmap("https://example.com/a.png", 720) is None


class TestCaching:
    def test_2回目は展開し直さない(self, cache, tmp_path, write_png) -> None:
        """更新の確認に `stat()` はするが、PNG の展開と縮小はしない。
        速さは `TestPerformance` が見る。"""
        write_png(tmp_path / "a.png")
        assert cache.pixmap("a.png", 720) is cache.pixmap("a.png", 720)

    def test_消された画像は返さない(self, cache, tmp_path, write_png) -> None:
        """無いものを描き続けない。"""
        path = write_png(tmp_path / "a.png")
        cache.pixmap("a.png", 720)
        path.unlink()
        assert cache.pixmap("a.png", 720) is None

    def test_同じものを返す(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png")
        assert cache.pixmap("a.png", 720) is cache.pixmap("a.png", 720)

    def test_書き換えたら読み直す(self, cache, tmp_path, write_png) -> None:
        """外部エディタで画像を差し替えたら反映されてほしい。"""
        import os

        path = write_png(tmp_path / "a.png", 100, 50)
        first = cache.pixmap("a.png", 720)
        write_png(tmp_path / "a.png", 200, 100)
        os.utime(path, (0, 0))  # mtime を確実に変える
        assert cache.pixmap("a.png", 720) is not first

    def test_幅が変われば作り直す(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png", 3000, 1500)
        assert cache.pixmap("a.png", 720).width() != cache.pixmap("a.png", 300).width()

    def test_溜め込みすぎない(self, cache, tmp_path, write_png) -> None:
        """1 枚数 MB になる。無制限に抱えるとメモリを食い潰す。"""
        for index in range(ImageCache.MAX_ENTRIES + 5):
            write_png(tmp_path / f"{index}.png")
            cache.pixmap(f"{index}.png", 720)
        assert len(cache) <= ImageCache.MAX_ENTRIES

    def test_捨てても読み直せる(self, cache, tmp_path, write_png) -> None:
        write_png(tmp_path / "a.png")
        cache.pixmap("a.png", 720)
        cache.clear()
        assert cache.pixmap("a.png", 720) is not None


class TestPerformance:
    def test_2回目は十分速い(self, cache, tmp_path, write_png) -> None:
        import time

        write_png(tmp_path / "big.png", 3024, 1964)
        cache.pixmap("big.png", 720)

        started = time.perf_counter()
        for _ in range(100):
            cache.pixmap("big.png", 720)
        each = (time.perf_counter() - started) * 1000 / 100
        assert each < 1.0, f"1 回あたり {each:.3f}ms"
