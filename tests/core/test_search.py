"""ノート内検索のテスト（`Cmd+F`）。

`Cmd+O` はノートを探し、`Cmd+Shift+F` はノートを横断して探す。
ここは**開いている 1 つのノートの中**を探す層。

R3 に従い GUI 非依存。`QTextCursor` の位置と文字オフセットは R4 により
常に 1:1 なので、ここで返す位置をそのままカーソルに渡せる。
"""

import pytest

from hitofude.core.search import find_all, find_next, matching_line, replace_all

TEXT = "りんご みかん りんご\nぶどう りんご"


class TestFindAll:
    def test_すべての位置を返す(self) -> None:
        assert find_all(TEXT, "りんご") == [(0, 3), (8, 11), (16, 19)]

    def test_見つからなければ空(self) -> None:
        assert find_all(TEXT, "バナナ") == []

    def test_空のクエリは何も返さない(self) -> None:
        """空文字が全位置に一致すると、検索バーを開いた瞬間に全文が光る。"""
        assert find_all(TEXT, "") == []

    def test_既定では大文字小文字を区別しない(self) -> None:
        assert len(find_all("Apple apple APPLE", "apple")) == 3

    def test_区別させることもできる(self) -> None:
        assert find_all("Apple apple", "apple", case_sensitive=True) == [(6, 11)]

    def test_重なる一致は数えない(self) -> None:
        """`aa` を `aaaa` から探して 3 件になると置換で壊れる。"""
        assert find_all("aaaa", "aa") == [(0, 2), (2, 4)]

    def test_改行をまたいで探せる(self) -> None:
        assert find_all("あ\nい", "あ\nい") == [(0, 3)]

    def test_正規表現の記号は文字として扱う(self) -> None:
        """`.` や `*` を打ったときに予想外の一致をしない。"""
        assert find_all("a.c abc", ".") == [(1, 2)]


class TestCasefoldで長さが変わる文字:
    """casefold は長さを変えることがある（ﬁ→fi、ß→ss）。

    折り畳んだ文字列上の位置を元の本文にそのまま使うと、合字より
    後ろの一致位置が全部ずれ、置換が本文を壊していた（回帰）。
    """

    def test_合字より後ろの一致位置がずれない(self) -> None:
        text = "ﬁle と ß を含む行 x"
        assert find_all(text, "x") == [(13, 14)]

    def test_合字を挟んだ置換が本文を壊さない(self) -> None:
        text = "ﬁle と ß を含む行 x"
        assert replace_all(text, "x", "Y") == ("ﬁle と ß を含む行 Y", 1)

    def test_合字は折り畳んだ形でも引ける(self) -> None:
        """`FILE` で `ﬁle` が見つかる。一致範囲は元の文字を丸ごと覆う。"""
        assert find_all("ﬁle を開く", "FILE") == [(0, 3)]

    def test_エスツェットはSSでも引ける(self) -> None:
        assert find_all("groß", "GROSS") == [(0, 4)]

    def test_合字の内側だけの一致は返さない(self) -> None:
        """`ﬁ` の `i` だけを置換することはできない。半端な一致は捨てる。"""
        assert find_all("ﬁle", "i") == []

    def test_区別する検索は折り畳まない(self) -> None:
        assert find_all("ﬁle x", "x", case_sensitive=True) == [(4, 5)]


class TestFindNext:
    def test_カーソルより後ろを探す(self) -> None:
        assert find_next(TEXT, "りんご", 1) == (8, 11)

    def test_末尾まで行ったら先頭へ戻る(self) -> None:
        assert find_next(TEXT, "りんご", 19) == (0, 3)

    def test_後ろ向きに探せる(self) -> None:
        assert find_next(TEXT, "りんご", 16, backward=True) == (8, 11)

    def test_後ろ向きで先頭まで行ったら末尾へ戻る(self) -> None:
        assert find_next(TEXT, "りんご", 0, backward=True) == (16, 19)

    def test_見つからなければNone(self) -> None:
        assert find_next(TEXT, "バナナ", 0) is None

    def test_空のクエリはNone(self) -> None:
        assert find_next(TEXT, "", 0) is None

    def test_一致が1つならそこへ戻ってくる(self) -> None:
        assert find_next("ひとつだけ", "ひとつ", 3) == (0, 3)

    @pytest.mark.parametrize("start", [-5, 0, 3, 999])
    def test_範囲外の位置でも落ちない(self, start: int) -> None:
        assert find_next(TEXT, "りんご", start) is not None


class TestReplaceAll:
    def test_すべて置き換える(self) -> None:
        replaced, count = replace_all(TEXT, "りんご", "なし")
        assert count == 3
        assert "りんご" not in replaced

    def test_件数を返す(self) -> None:
        assert replace_all(TEXT, "みかん", "なし")[1] == 1

    def test_見つからなければ元のまま(self) -> None:
        assert replace_all(TEXT, "バナナ", "なし") == (TEXT, 0)

    def test_空のクエリは何もしない(self) -> None:
        """全位置に空文字を挿入して本文を壊さない。"""
        assert replace_all(TEXT, "", "X") == (TEXT, 0)

    def test_空文字へ置換すると削除になる(self) -> None:
        assert replace_all("あいう", "い", "")[0] == "あう"

    def test_置換後の文字列を再び拾わない(self) -> None:
        """`a` を `aa` にしたときに無限に増えない。"""
        assert replace_all("aaa", "a", "aa") == ("aaaaaa", 3)

    def test_大文字小文字を区別しないと元の字は残らない(self) -> None:
        assert replace_all("Apple apple", "apple", "梨")[0] == "梨 梨"

    def test_区別させることもできる(self) -> None:
        assert replace_all("Apple apple", "apple", "梨", case_sensitive=True)[0] == "Apple 梨"

    def test_マーカーを壊さない(self) -> None:
        """R1: 置換はただの文字列操作。Markdown の構造を解釈しない。"""
        replaced, _ = replace_all("**強調** と `コード`", "強調", "太字")
        assert replaced == "**太字** と `コード`"


class TestMatchingLine:
    """全文検索の結果から、その行へ飛ぶ（G-1）。

    索引には**マーカーを外した写し**が入っている（`searchable_text`）ので、
    `**予算**について` は `予算について` として引ける。飛び先を探すときも
    同じ形で見ないと、**索引では見つかるのに本文では見つからない**という
    食い違いが起きる。

    **索引に行番号は持たせない。** 持たせると索引の作りが変わって作り直しが
    要るうえ、ノートを開けば数え直せる（開く数は 1 つ）。
    """

    def test_その行を返す(self) -> None:
        text = "# 見出し\n\n本文です。\n予算の話。\n"
        assert matching_line(text, "予算") == 3

    def test_最初の一致(self) -> None:
        assert matching_line("予算\n本文\n予算\n", "予算") == 0

    def test_マーカー越しに見つける(self) -> None:
        """索引は `**予算**について` を `予算について` として持っている。"""
        assert matching_line("# 題\n\n**予算**について話す\n", "予算について") == 2

    def test_行頭のマーカーも越える(self) -> None:
        assert matching_line("- **予算**の話\n", "予算の話") == 0

    def test_大小を無視する(self) -> None:
        assert matching_line("# Title\n\nBudget review\n", "budget") == 2

    def test_front_matterは数に入れる(self) -> None:
        """行番号は**ファイルの先頭から**数える（キャレットの位置に使う）。"""
        text = "---\nid: ABC\n---\n\n予算\n"
        assert matching_line(text, "予算") == 4

    def test_見つからなければNone(self) -> None:
        assert matching_line("本文\n", "存在しない") is None

    def test_空の検索語(self) -> None:
        assert matching_line("本文\n", "") is None

    def test_元の文字列を変えない(self) -> None:
        text = "**予算**\n"
        matching_line(text, "予算")
        assert text == "**予算**\n"

    def test_全角の本文を半角で見つける(self) -> None:
        """索引は NFKC で寄せている（`searchable_text`）ので、半角 `UI` で
        全角 `ＵＩ` のノートが検索に出る。飛び先も同じ形で見ないと、
        **一覧には出るのに選んでも先頭のまま**になる（レビュー指摘 2026-08-31）。
        """
        assert matching_line("# 題\n\n本文のＵＩについて\n", "UI") == 2

    def test_半角の本文を全角で見つける(self) -> None:
        assert matching_line("# 題\n\nUI の見直し\n", "ＵＩ") == 2

    def test_半角カナの本文を全角カナで見つける(self) -> None:
        assert matching_line("ﾒﾓの整理\n", "メモ") == 0
