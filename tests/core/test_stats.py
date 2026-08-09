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


class TestNoWordCount:
    """単語数は出さない（ユーザーの指摘で取りやめ）。

    CJK を 1 文字 1 語として数えていたが、`東京都渋谷区` が 6 語になるなど
    語数としての意味を成さなかった。数えるふりをするより出さないほうがよい。
    """

    def test_単語数を持たない(self) -> None:
        assert not hasattr(count("あいうえお"), "words")


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
        """素の実行で 63ms（実測）。

        `make cov` はトレーサが入るので 3.6 倍まで伸びる（実測 228ms）。
        測っているのは実装の速さであって計測器の速さではないので、
        トレーサが居るときだけ枠を広げる。
        """
        import sys
        import time

        text = "これは日本語の文章です。**強調** も入ります。\n" * 2000
        started = time.perf_counter()
        count(text)
        elapsed = (time.perf_counter() - started) * 1000

        budget = 200.0 * (5 if sys.gettrace() or sys.monitoring.get_tool(2) else 1)
        assert elapsed < budget, f"{elapsed:.0f}ms かかった（枠 {budget:.0f}ms）"


class TestSymbolsInProse:
    """記号として書いた文字を落とさないこと。

    「Markdown の記号を一括で消す」実装（`str.translate`）を試したときに
    抜けていた範囲。`-` や `!` や括弧は**文章の一部**なので、
    マーカーとして働いているときだけ落とす。
    """

    def test_ハイフンは数える(self) -> None:
        assert count("1 - 2 = -1 です").characters == len("1 - 2 = -1 です")

    def test_感嘆符は数える(self) -> None:
        assert count("注意! これは大事").characters == len("注意! これは大事")

    def test_括弧は数える(self) -> None:
        assert count("(補足) あとで直す").characters == len("(補足) あとで直す")

    def test_アンダースコアは数える(self) -> None:
        assert count("snake_case の変数").characters == len("snake_case の変数")

    def test_箇条書きの記号だけ落とす(self) -> None:
        """行頭の `- ` はマーカー。中身の文字は残る。"""
        assert count("- りんご\n- みかん").characters == len("りんごみかん")

    def test_引用の記号だけ落とす(self) -> None:
        assert count("> 引用文です").characters == len("引用文です")

    def test_コードブロックの中身は記号ごと残す(self) -> None:
        """コードは書いたままが内容。装飾として解釈しない。"""
        assert count("```\na = b * 2\n```").characters == len("```a = b * 2```")


class TestLinks:
    """リンクの記号は落とすが、URL は数に入る。

    数える元の `plain_text()` は**検索索引と共有**している。索引側では
    URL でノートを引けたほうがよいので、URL を残す判断になっている
    （`document.plain_text` の docstring）。文字数としては多めに出るが、
    ここだけ別扱いにすると「装飾は文章の一部ではない」という 1 つの判断が
    2 つに割れる。変えるなら索引side ごと決め直す話。
    """

    def test_リンクの記号は数えない(self) -> None:
        assert count("[仕様](https://example.com)").characters == len("仕様https://example.com")

    def test_リンクの文字は残る(self) -> None:
        assert count("[仕様](https://example.com)").characters > len("https://example.com")

    def test_裸のURLは数える(self) -> None:
        """書いてあるものが見えているので、そのまま数える。"""
        assert count("https://example.com").characters == len("https://example.com")


class TestLinesWithFrontMatter:
    """行数も front matter を含めない。

    `lines` は画面に出ていないが公開 API なので、`characters` と
    同じ土俵で数える。
    """

    def test_front_matterの行を数えない(self) -> None:
        text = "---\nid: ABC\nmodified: 2026-01-01\n---\n# 見出し\n\n一行目\n二行目\n"
        assert count(text).lines == 4

    def test_front_matterだけなら0行(self) -> None:
        assert count("---\nid: ABC\n---\n").lines == 0

    def test_front_matterが無ければそのまま(self) -> None:
        assert count("一行目\n二行目\n").lines == 2
