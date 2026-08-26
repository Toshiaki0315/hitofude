"""表のセル折り返し（案 B / ADR-0017）のテスト。

罫線そのものの描画検査は tests/editor/test_table_render.py。
ここは折り返しの純ロジック（R3: GUI 非依存）だけを見る。
"""

import pytest

from hitofude.core import table
from hitofude.core.table import (
    CELL_OVERHEAD,
    MIN_WRAP_COLUMN,
    wrap_cell,
    wrap_row,
    wrapped_columns,
)


class TestWrapCell:
    """セルの折り返し（案 B / ADR-0017）。表示幅（全角 2）で数える。"""

    def test_収まるセルはそのまま(self) -> None:
        assert wrap_cell("abc", 10) == ["abc"]

    def test_幅を超えたら折り返す(self) -> None:
        assert wrap_cell("abcdef", 4) == ["abcd", "ef"]

    def test_全角は2桁で数える(self) -> None:
        assert wrap_cell("あいうえお", 6) == ["あいう", "えお"]

    def test_空白があればそこで折る(self) -> None:
        """英単語の途中で切らない。ただし 1 語が幅を超えるときは字で切る。"""
        assert wrap_cell("hello world", 8) == ["hello", "world"]
        assert wrap_cell("abcdefghij x", 6) == ["abcdef", "ghij x"]

    def test_空のセルは1行(self) -> None:
        assert wrap_cell("", 6) == [""]

    def test_全角と半角の混在(self) -> None:
        assert wrap_cell("価格は $100 です", 8) == ["価格は", "$100", "です"]


class TestWrappedColumns:
    """収まらない表の列幅配分（案 B / ADR-0017）。

    自然幅（各列の最長セル）が使える幅に収まればそのまま。溢れたら
    **いちばん広い列から**削る。狭い列は道連れにしない。
    """

    def rows(self) -> list[str]:
        return [
            "| 短い | とてもとても長い中身のセルがここにある |",
            "| --- | --- |",
            "| a | b |",
        ]

    def test_収まるなら自然幅のまま(self) -> None:
        widths = wrapped_columns(["| ab | cd |", "| - | - |"], available=40)
        assert widths == [2, 2]

    def test_溢れたら広い列から削る(self) -> None:
        widths = wrapped_columns(self.rows(), available=40)
        assert widths[0] == 4  # 「短い」の自然幅のまま
        assert widths[1] < 38  # 長い列だけが縮む
        assert sum(widths) + CELL_OVERHEAD * 2 + 1 <= 40

    def test_最低幅より狭くしない(self) -> None:
        widths = wrapped_columns(self.rows(), available=20)
        assert all(w >= MIN_WRAP_COLUMN or w >= 4 for w in widths)

    def test_区切り行は幅に数えない(self) -> None:
        """`|---|` の `-` の数は書き手の癖で、内容の幅ではない。"""
        widths = wrapped_columns(["| ab | cd |", "| ---------- | ---------- |"], available=60)
        assert widths == [2, 2]


class TestWrapRow:
    def test_行の見た目の行数はいちばん高いセル(self) -> None:
        cells = wrap_row("| 短い | あいうえおかきくけこ |", [4, 6])
        assert cells[0] == ["短い"]
        assert cells[1] == ["あいう", "えおか", "きくけ", "こ"]


class TestForcedBreak:
    """セル内の明示的な改行 `<br>`（ユーザー要望 2026-08-25 / ADR-0028）。

    GFM の表はセル内改行の公式記法を持たず、GitHub / Qiita とも `<br>` が
    事実上の標準。表のセルの中だけで意味を持ち、本文中は文字のまま。
    """

    def test_brで折り返す(self) -> None:
        assert table.wrap_cell("一行目<br>二行目", 20) == ["一行目", "二行目"]

    @pytest.mark.parametrize("br", ["<br>", "<br/>", "<br />", "<BR>", "<Br/>"])
    def test_変種も同義(self, br: str) -> None:
        assert table.wrap_cell(f"上{br}下", 20) == ["上", "下"]

    def test_断片はさらに幅で折り返す(self) -> None:
        assert table.wrap_cell("short<br>ながいながい", 6) == ["short", "ながい", "ながい"]

    def test_brが無ければ今まで通り(self) -> None:
        assert table.wrap_cell("あい うえ", 4) == ["あい", "うえ"]

    def test_列の自然幅は断片の最長(self) -> None:
        """`<br>` を入れると列が痩せる、という直感どおりの効き。"""
        rows = ["| 見出し |", "| --- |", "| 短い<br>ながいながい |"]
        assert table.wrapped_columns(rows, 200) == [table.display_width("ながいながい")]

    def test_brがあれば折り返し表示になる(self) -> None:
        rows = ["| A |", "| --- |", "| 上<br>下 |"]
        assert table.forces_wrap(rows) is True

    def test_brが無ければ強制しない(self) -> None:
        rows = ["| A |", "| --- |", "| ふつう |"]
        assert table.forces_wrap(rows) is False

    def test_整形の縦線はbr込みの全長で揃える(self) -> None:
        """ユーザー決定 2026-08-25。整形はソースの見た目を揃える機能で、
        断片幅で数えるとソース上の縦線がずれる。"""
        lines = ["| A | B |", "| --- | --- |", "| 上<br>下 | x |"]
        fixed = table.format_table(lines)
        assert fixed is not None
        assert "| 上<br>下 | x" in fixed[2]
        # 見出し行の A の列は「上<br>下」の全長ぶん空く
        assert table.display_width(fixed[0].split("|")[1]) >= table.display_width(" 上<br>下 ")


class TestTrailingBreak:
    """末尾の `<br>` は空行を作らない（ユーザー報告 2026-08-25）。

    `<td>dd<br></td>` をブラウザは空行にしない（行ボックスの規則）。
    GitHub 互換の記法なので、見え方も合わせる。**中の空行は残す**
    （`a<br><br>b` の真ん中の空行は書いた人の意図）。
    """

    def test_末尾のbrは無視する(self) -> None:
        assert table.wrap_cell("dd<br>", 20) == ["dd"]

    def test_末尾に連続していても無視する(self) -> None:
        assert table.wrap_cell("dd<br><br>", 20) == ["dd"]

    def test_中の空行は残す(self) -> None:
        assert table.wrap_cell("a<br><br>b", 20) == ["a", "", "b"]

    def test_先頭の空行も残す(self) -> None:
        assert table.wrap_cell("<br>a", 20) == ["", "a"]
