"""文字数・単語数のテスト。

日本語には語の区切りが無いので、英語式の「空白で割る」が使えない。
CJK は 1 文字を 1 語として数える。
"""

import pytest

from hitofude.core.stats import count


class TestCharacters:
    def test_数える(self) -> None:
        assert count("あいうえお").characters == 5

    def test_改行は数えない(self) -> None:
        assert count("あい\nうえ").characters == 4

    def test_空白は数える(self) -> None:
        """原稿の分量としては空白も場所を取っている。"""
        assert count("あ い").characters == 3

    def test_front_matterは数えない(self) -> None:
        assert count("---\nid: ABC\n---\nあいう\n").characters == 3

    def test_装飾の記号は数えない(self) -> None:
        """`**` は読む文章の一部ではない。"""
        assert count("**強調**").characters == 2

    def test_見出しの記号も数えない(self) -> None:
        assert count("# 見出し").characters == 3

    def test_コードブロックは記号ごと数える(self) -> None:
        """中身をそのまま書いたものなので、勝手に削らない。"""
        assert count("```py\na=1\n```").characters > 3

    def test_空なら0(self) -> None:
        assert count("").characters == 0


class TestWords:
    def test_英語は空白で割る(self) -> None:
        assert count("hello brave new world").words == 4

    def test_日本語は1文字1語(self) -> None:
        """空白で割れないので、CJK は文字数をそのまま語数にする。"""
        assert count("こんにちは").words == 5

    def test_混ざっていても数えられる(self) -> None:
        assert count("Qt と PySide").words == 3

    def test_句読点だけの語は数えない(self) -> None:
        assert count("hello, world!").words == 2

    def test_空なら0(self) -> None:
        assert count("").words == 0

    def test_空白だけなら0(self) -> None:
        assert count("   \n  ").words == 0


class TestLines:
    def test_行を数える(self) -> None:
        assert count("一行目\n二行目\n三行目").lines == 3

    def test_末尾の改行で1行増やさない(self) -> None:
        assert count("一行目\n").lines == 1

    def test_空なら0(self) -> None:
        assert count("").lines == 0


class TestPerformance:
    """§6.6: 入力のたびに数えても引っかからないこと。"""

    @pytest.mark.parametrize("_", range(1))
    def test_1万語でも十分速い(self, _) -> None:
        import time

        text = "これは日本語の文章です。**強調** も入ります。\n" * 2000
        started = time.perf_counter()
        count(text)
        elapsed = (time.perf_counter() - started) * 1000
        assert elapsed < 200, f"{elapsed:.0f}ms かかった"
