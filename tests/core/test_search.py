"""ノート内検索のテスト（`Cmd+F`）。

`Cmd+O` はノートを探し、`Cmd+Shift+F` はノートを横断して探す。
ここは**開いている 1 つのノートの中**を探す層。

R3 に従い GUI 非依存。`QTextCursor` の位置と文字オフセットは R4 により
常に 1:1 なので、ここで返す位置をそのままカーソルに渡せる。
"""

import pytest

from hitofude.core.search import find_all, find_next, replace_all

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
