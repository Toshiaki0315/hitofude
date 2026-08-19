"""検索の問い合わせを読み取る（提案 3）。

`Cmd+Shift+F` は全文一致だけで、**タグで絞れなかった**。索引にはタグが
入っているので、`#仕事 予算` のように**本文と同じ書き方**で絞れるようにする。

入力欄は増やさない。書き方が本文と揃っているほうが覚えることが少ない。
"""

from datetime import date

import pytest

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
        assert parse("#仕事").filter_only is True
        assert parse("#仕事 予算").filter_only is False
        assert parse("予算").filter_only is False

    def test_空は絞り込みでもない(self) -> None:
        assert parse("").filter_only is False


class TestDates:
    """期間で絞る（案 A）。**その日を含む。**

    `after:2026-08-01` は 8/1 に書いたものも出す。日付は区切りとして打つ
    ものなので、含まないほうが驚く。
    """

    def test_開始日を取り出す(self) -> None:
        found = parse("予算 after:2026-08-01")
        assert found.after == date(2026, 8, 1)
        assert found.text == "予算"

    def test_終了日を取り出す(self) -> None:
        found = parse("予算 before:2026-08-31")
        assert found.before == date(2026, 8, 31)
        assert found.text == "予算"

    def test_両方書ける(self) -> None:
        found = parse("after:2026-08-01 before:2026-08-31 予算")
        assert (found.after, found.before) == (date(2026, 8, 1), date(2026, 8, 31))
        assert found.text == "予算"

    def test_タグと混ぜられる(self) -> None:
        found = parse("#仕事 after:2026-08-01 予算")
        assert found.tags == ("仕事",)
        assert found.after == date(2026, 8, 1)
        assert found.text == "予算"

    def test_日付だけでも通る(self) -> None:
        found = parse("after:2026-08-01")
        assert found.after == date(2026, 8, 1)
        assert found.text == ""
        assert found.filter_only is True

    @pytest.mark.parametrize(
        "query", ["after:", "after:きのう", "after:2026-13-01", "after:2026-8-1"]
    )
    def test_日付として読めなければ言葉のまま(self, query: str) -> None:
        """**黙って絞らない。** 打ち間違いで 0 件になると、原因が分からない。"""
        found = parse(query)
        assert found.after is None
        assert found.text == query

    def test_大文字でも効く(self) -> None:
        assert parse("After:2026-08-01").after == date(2026, 8, 1)


class TestBadDates:
    """日付として読めなかったことを覚えておく（案 1）。

    読めない書き方はそのまま探す言葉にするが、**そのままだと 0 件の理由が
    画面から読めない**（ユーザー指摘）。`after:` と書いた以上、絞り込みの
    つもりだったことは分かるので、そこだけ拾って呼び出し側に渡す。
    """

    def test_読めない日付を覚える(self) -> None:
        found = parse("after:きのう")
        assert found.unreadable_dates == ("after:きのう",)

    def test_読めれば覚えない(self) -> None:
        assert parse("after:2026-08-01").unreadable_dates == ()

    def test_複数あれば全部(self) -> None:
        found = parse("after:きのう before:あした")
        assert found.unreadable_dates == ("after:きのう", "before:あした")

    def test_言葉としては残っている(self) -> None:
        """**探すのはやめない。** そう書いたものを探した結果が出るほうが辿れる。"""
        found = parse("after:きのう")
        assert found.text == "after:きのう"

    def test_日付の形をしていなければ何も覚えない(self) -> None:
        """`after` と書いていなければ、そもそも絞り込みのつもりではない。"""
        assert parse("きのうの予算").unreadable_dates == ()
