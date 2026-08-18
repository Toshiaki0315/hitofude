"""表のセル折り返し（案 B / ADR-0017）のテスト。

罫線そのものの描画検査は tests/editor/test_table_render.py。
ここは折り返しの純ロジック（R3: GUI 非依存）だけを見る。
"""

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
