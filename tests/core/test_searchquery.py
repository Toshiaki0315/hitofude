"""検索の問い合わせを読み取る（提案 3）。

`Cmd+Shift+F` は全文一致だけで、**タグで絞れなかった**。索引にはタグが
入っているので、`#仕事 予算` のように**本文と同じ書き方**で絞れるようにする。

入力欄は増やさない。書き方が本文と揃っているほうが覚えることが少ない。
"""

from hitofude.core.searchquery import parse


class TestText:
    def test_ふつうの言葉(self) -> None:
        found = parse("予算")
        assert found.text == "予算"
        assert found.tags == ()

    def test_前後の空白は落とす(self) -> None:
        assert parse("  予算  ").text == "予算"

    def test_空なら空(self) -> None:
        found = parse("   ")
        assert found.text == ""
        assert found.tags == ()

    def test_複数の語はそのまま渡す(self) -> None:
        """**語で分けない。** 全文検索は打った通りの並びを探す（既存の挙動）。"""
        assert parse("来週の予算").text == "来週の予算"


class TestTags:
    def test_タグを取り出す(self) -> None:
        found = parse("#仕事 予算")
        assert found.tags == ("仕事",)
        assert found.text == "予算"

    def test_書く順は問わない(self) -> None:
        found = parse("予算 #仕事")
        assert found.tags == ("仕事",)
        assert found.text == "予算"

    def test_複数のタグは全部満たす(self) -> None:
        """**AND で絞る。** OR だと、絞ったのに件数が増えて驚く。"""
        found = parse("#仕事 #会議 予算")
        assert found.tags == ("仕事", "会議")
        assert found.text == "予算"

    def test_階層のタグも書ける(self) -> None:
        assert parse("#仕事/会議").tags == ("仕事/会議",)

    def test_タグだけでも通る(self) -> None:
        found = parse("#仕事")
        assert found.tags == ("仕事",)
        assert found.text == ""

    def test_同じタグはまとめる(self) -> None:
        assert parse("#仕事 #仕事").tags == ("仕事",)

    def test_語の途中の井桁はタグにしない(self) -> None:
        """`URL#anchor` を絞り込みと取り違えない（本文の規則と揃える）。"""
        found = parse("http://example.com#anchor")
        assert found.tags == ()
        assert found.text == "http://example.com#anchor"

    def test_井桁だけなら言葉として扱う(self) -> None:
        assert parse("#").tags == ()
        assert parse("#").text == "#"


class TestFilterOnly:
    def test_絞り込みだけか分かる(self) -> None:
        assert parse("#仕事").tags_only is True
        assert parse("#仕事 予算").tags_only is False
        assert parse("予算").tags_only is False

    def test_空は絞り込みでもない(self) -> None:
        assert parse("").tags_only is False
