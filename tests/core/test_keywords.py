"""質問から探す語を取り出す（L-2）。

**質問は検索語ではない。** 全文検索は打った通りの並びを探す（trigram の
フレーズ一致）ので、「予算について何が決まった？」ではどのノートにも
当たらない（実測で出典 0 件だった）。

形態素解析は入れない（辞書ごと抱えることになる）。**漢字とカタカナの
連なりは意味を担い、ひらがなは助詞と語尾に偏る**という日本語の性質だけを
使って、素朴に切り出す。
"""

import pytest

from hitofude.core.keywords import terms


class TestJapanese:
    def test_漢字の並びを拾う(self) -> None:
        assert terms("予算について何が決まった？") == ["予算"]

    def test_複数拾える(self) -> None:
        assert terms("会議の議事録はどこ？") == ["会議", "議事録"]

    def test_カタカナの並びを拾う(self) -> None:
        assert terms("プロジェクトの進捗は？") == ["プロジェクト", "進捗"]

    def test_1文字は拾わない(self) -> None:
        """**「何」「が」で全ノートに当たる。** 絞れない語は語にしない。"""
        assert terms("何がどうなった？") == []

    def test_送り仮名は挟んで繋ぐ(self) -> None:
        """**「買い物」が落ちる**（実測）。漢字が仮名 1 文字で切れる語は多い。"""
        assert terms("買い物のメモ") == ["買い物", "メモ"]

    def test_助詞では繋がない(self) -> None:
        """「会議の議事録」を 1 語にすると、その並びのノートにしか当たらない。"""
        assert terms("会議の議事録") == ["会議", "議事録"]

    def test_ひらがなだけの語は拾わない(self) -> None:
        """助詞と語尾に偏る。拾うと当たりが増えすぎる（既知の割り切り）。"""
        assert terms("それはどうなりましたか") == []


class TestOthers:
    def test_英字の語を拾う(self) -> None:
        assert terms("Ollama の設定は？") == ["Ollama", "設定"]

    def test_1文字の英字は拾わない(self) -> None:
        assert terms("a の話") == []

    def test_数字の並びも拾う(self) -> None:
        # 「年」は 1 文字なので落ちる（絞れない語は語にしない）
        assert terms("2026 年の予算") == ["2026", "予算"]

    @pytest.mark.parametrize("mark", ["？", "、", "。", "「", "」", "！"])
    def test_記号では切る(self, mark: str) -> None:
        assert terms(f"予算{mark}会議") == ["予算", "会議"]


class TestShape:
    def test_同じ語は1回だけ(self) -> None:
        assert terms("予算と予算の話") == ["予算"]

    def test_多すぎる語は絞る(self) -> None:
        """**問い合わせの回数がそのまま増える。** 上から数語で足りる。"""
        found = terms("予算 会議 議事録 資料 日程 場所 参加者 費用")
        assert len(found) <= 4

    def test_空なら空(self) -> None:
        assert terms("   ") == []
