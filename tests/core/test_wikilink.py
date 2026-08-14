"""`[[ノート名]]` の走査と解決（E-6）。

ノート同士を繋ぐためのリンク。**CommonMark ではない**（Qiita 記法や
`::ハイライト::` と同じ立場）。他のアプリで開けばただの文字に見えるが、
ソースが真実（R1）なので何も失われない。

名前で解決するのは、このアプリのタイトルが**本文の H1 から導かれ、
ファイル名がそれに追従する**（ADR-0005）ため。ID で結ぶ手もあるが、
`[[01J8XZ...]]` と書かれたノートは人が読めない。
"""

from typing import ClassVar

import pytest

from hitofude.core.activation import Activation, ActivationKind, activation_at
from hitofude.core.inline_scanner import scan
from hitofude.core.models import SpanType
from hitofude.core.wikilink import normalize, resolve


def wiki(text: str) -> list:
    return [span for span in scan(text) if span.type is SpanType.WIKI_LINK]


class TestScan:
    def test_見つかる(self) -> None:
        assert len(wiki("[[会議メモ]]")) == 1

    def test_名前を持つ(self) -> None:
        assert wiki("[[会議メモ]]")[0].payload == "会議メモ"

    def test_記号の範囲(self) -> None:
        """`[[` と `]]` がマーカー。隠すのはここだけ。"""
        span = wiki("[[会議メモ]]")[0]
        assert (span.open_start, span.open_end) == (0, 2)
        assert (span.close_start, span.close_end) == (6, 8)

    def test_文の途中でも見つかる(self) -> None:
        span = wiki("詳しくは [[会議メモ]] を見て")[0]
        assert span.payload == "会議メモ"
        assert span.start == 5

    def test_1行に2つ(self) -> None:
        assert [span.payload for span in wiki("[[あ]] と [[い]]")] == ["あ", "い"]

    def test_前後の空白は落とす(self) -> None:
        assert wiki("[[ 会議メモ ]]")[0].payload == "会議メモ"

    @pytest.mark.parametrize("text", ["[[]]", "[[   ]]", "[会議メモ]", "[[会議メモ]", "[[会議メモ"])
    def test_これはリンクではない(self, text: str) -> None:
        assert wiki(text) == []

    def test_コードの中は拾わない(self) -> None:
        """`` `[[a]]` `` はコードとして書いたもの。"""
        assert wiki("`[[会議メモ]]`") == []

    def test_ふつうのリンクを壊さない(self) -> None:
        spans = scan("[題名](https://example.com)")
        assert any(span.type is SpanType.LINK_TEXT for span in spans)
        assert not any(span.type is SpanType.WIKI_LINK for span in spans)

    def test_画像を壊さない(self) -> None:
        spans = scan("![](attachments/図.png)")
        assert any(span.type is SpanType.IMAGE for span in spans)

    def test_中の記号は装飾にしない(self) -> None:
        """`[[a_b_c]]` の `_` は名前の一部。強調にすると飛び先が変わる。"""
        spans = scan("[[a_b_c]]")
        assert not any(span.type is SpanType.EM for span in spans)

    def test_縦棒を含むものは拾わない(self) -> None:
        """別名（`[[名前|表示]]`）は未対応。**中途半端に拾わない。**"""
        assert wiki("[[会議メモ|きょう]]") == []


class TestNormalize:
    def test_前後の空白を落とす(self) -> None:
        assert normalize(" 会議メモ ") == "会議メモ"

    def test_連なる空白は1つに(self) -> None:
        """ファイル名も同じ規則で作られる（`sanitize_filename`）。"""
        assert normalize("会議  メモ") == "会議 メモ"

    def test_濁点の書き方を揃える(self) -> None:
        """`が` は 1 文字でも「か + 濁点」の 2 文字でも書ける。NFC に寄せる。

        macOS のファイル名は分解された形（NFD）で来ることがあり、揃えないと
        同じ名前が別物になる（`sanitize_filename` も NFC にしている）。
        """
        assert normalize("\u304b\u3099") == "\u304c"


class TestResolve:
    TITLES: ClassVar[list[str]] = ["会議メモ", "Hitofude の使い方", "Weekly Report"]

    def test_そのままの名前(self) -> None:
        assert resolve("会議メモ", self.TITLES) == "会議メモ"

    def test_無ければNone(self) -> None:
        assert resolve("存在しない", self.TITLES) is None

    def test_前後の空白は無視(self) -> None:
        assert resolve(" 会議メモ ", self.TITLES) == "会議メモ"

    def test_英字の大小は無視(self) -> None:
        """打つときに大文字を思い出せなくても届く。"""
        assert resolve("weekly report", self.TITLES) == "Weekly Report"

    def test_完全一致を優先(self) -> None:
        assert resolve("ABC", ["abc", "ABC"]) == "ABC"

    def test_候補が空(self) -> None:
        assert resolve("会議メモ", []) is None

    def test_空の名前(self) -> None:
        assert resolve("", self.TITLES) is None


class TestActivation:
    def test_ノートを開く動作になる(self) -> None:
        spans = scan("[[会議メモ]]")
        assert activation_at(spans, 3) == Activation(ActivationKind.NOTE, "会議メモ")

    def test_記号の上でも効く(self) -> None:
        """`[[` は隠れていて見えないが、押せる場所ではある。"""
        assert activation_at(scan("[[会議メモ]]"), 0).kind is ActivationKind.NOTE

    def test_外は何も起きない(self) -> None:
        assert activation_at(scan("[[あ]] の外"), 8) is None
