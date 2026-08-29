"""日本語の文体チェック（U-4。ユーザー要望 2026-08-29）。

iA Writer の Style Check（決まり文句・冗長表現の指摘）の日本語版。
**指摘するだけで、直さない**——書き手の言葉を機械が上書きしない。

**形態素解析は使わない。** 品詞で見ると辞書と実行時間が要るうえ、
外すと的外れな指摘になる。**言い回しの辞書**に絞れば、当たるものだけを
確実に当てられる。外れを出さないことを取る（1 つの誤検出が、以後
全部の指摘を無視させる）。
"""

import pytest

from hitofude.core.style_check import Finding, Kind, check

pytestmark = []


def kinds(text: str) -> list[Kind]:
    return [found.kind for found in check(text)]


def messages(text: str) -> list[str]:
    return [found.message for found in check(text)]


class TestRedundant:
    """冗長な言い回し。"""

    @pytest.mark.parametrize(
        "text",
        ["これを実行することができます。", "設定することが可能です。"],
    )
    def test_見つける(self, text: str) -> None:
        assert Kind.REDUNDANT in kinds(text)

    def test_言い換えを添える(self) -> None:
        """**何が悪いかではなく、どう書けるか**を出す。"""
        assert any("できます" in m for m in messages("これを実行することができます。"))

    def test_素直な文は指摘しない(self) -> None:
        assert check("これを実行できます。") == []


class TestDoubleNegative:
    @pytest.mark.parametrize(
        "text",
        ["それは間違いなくはない。", "できないことはない。"],
    )
    def test_見つける(self, text: str) -> None:
        assert Kind.DOUBLE_NEGATIVE in kinds(text)


class TestTautology:
    """重ね言葉（頭痛が痛い の類）。"""

    @pytest.mark.parametrize(
        "text",
        ["まず最初に確認します。", "違和感を感じました。", "今の現状はこうです。"],
    )
    def test_見つける(self, text: str) -> None:
        assert Kind.TAUTOLOGY in kinds(text)


class TestParticleRun:
    def test_のが3つ続くと指摘(self) -> None:
        assert Kind.PARTICLE_RUN in kinds("私の友人の家の庭は広い。")

    def test_2つなら指摘しない(self) -> None:
        """**ふつうに書ける範囲**を叱らない。"""
        assert Kind.PARTICLE_RUN not in kinds("私の友人の家は広い。")


class TestLongSentence:
    def test_長い文を指摘(self) -> None:
        long = "これは" + "とても" * 40 + "長い文です。"
        assert Kind.LONG_SENTENCE in kinds(long)

    def test_短い文は指摘しない(self) -> None:
        assert Kind.LONG_SENTENCE not in kinds("これは短い文です。")

    def test_句点で区切って数える(self) -> None:
        """**行の長さではない。** 短い文が並んでいるだけなら問題ない。"""
        text = "。".join("これは短い文です" for _ in range(20)) + "。"
        assert Kind.LONG_SENTENCE not in kinds(text)


class TestPosition:
    """指摘の位置。**どこを直すかが分からないと動けない。**"""

    def test_見つけた場所を返す(self) -> None:
        found = check("あとで実行することができます。")[0]
        assert found.start >= 0
        assert found.length > 0

    def test_その場所が当該の語(self) -> None:
        text = "あとで実行することができます。"
        found = next(f for f in check(text) if f.kind is Kind.REDUNDANT)
        assert "することができ" in text[found.start : found.start + found.length]


class TestQuiet:
    """**黙るべきところで黙る。**"""

    def test_コードの中は見ない(self) -> None:
        """コード例に日本語の言い回しが入っていても指摘しない。"""
        text = "```python\n# 実行することができます\nprint(1)\n```\n"
        assert check(text) == []

    def test_空なら何も出ない(self) -> None:
        assert check("") == []

    def test_findingは並べ替えられている(self) -> None:
        text = "違和感を感じます。あとで実行することができます。"
        found = check(text)
        assert [f.start for f in found] == sorted(f.start for f in found)


class TestDataclass:
    def test_中身(self) -> None:
        found = Finding(start=0, length=3, kind=Kind.TAUTOLOGY, message="重ね言葉")
        assert found.end == 3


class TestNoFalsePositives:
    """**外れを出さない。** 実物の文書に当てて分かったこと。

    1 つの誤検出が、以後全部の指摘を無視させる。当たらないより、
    間違って当たるほうが悪い。
    """

    def test_表の行は文ではない(self) -> None:
        """`docs/TASKS.md` で 193 件のうちほとんどが表だった（実測）。"""
        row = "| --- | ------ | " + "-" * 120 + " |"
        assert check(row) == []

    def test_表の中身も見ない(self) -> None:
        text = "| 見出し | 説明 |\n| --- | --- |\n| あ | " + "説明" * 60 + " |\n"
        assert check(text) == []

    def test_のの連なりは短い語だけ(self) -> None:
        """**節をまたいで拾わない。** `本文の上のボタンからも付けられます（次の`
        のような長い塊は、`の` の連なりではない（実測で 21 件出た）。
        """
        assert check("本文の上のボタンからも付けられます。") == []

    def test_本当の連なりは拾う(self) -> None:
        assert Kind.PARTICLE_RUN in kinds("私の友人の家の庭は広い。")

    def test_区切り線は見ない(self) -> None:
        assert check("-" * 120) == []

    def test_こそあどは鎖に数えない(self) -> None:
        """`その` の `の` は「〜の〜」の連なりではない（連体詞の一部）。

        実物で `前の行の字下げがその` を拾っていた（実測）。
        """
        assert Kind.PARTICLE_RUN not in kinds("前の行の字下げがその位置になります。")

    def test_それでも本当の連なりは拾う(self) -> None:
        assert Kind.PARTICLE_RUN in kinds("本文の上の表のボタンを押す。")
