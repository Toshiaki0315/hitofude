"""表の整形のテスト（spec §1.2「等幅フォント + 罫線揃え」）。

GFM / Qiita と同じ記法。**日本語は等幅フォントで 2 桁ぶんの幅**を取るので、
文字数ではなく表示幅で揃えないと縦線がずれる。
"""

import pytest

from hitofude.editor.table import Alignment, display_width, find_table, format_table


class TestDisplayWidth:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("abc", 3),
            ("あいう", 6),  # 全角は 2 桁
            ("あa", 3),
            ("", 0),
            ("１２３", 6),  # 全角数字
            ("ｱｲｳ", 3),  # 半角カナは 1 桁
            ("🙂", 2),
        ],
    )
    def test_表示幅(self, text: str, expected: int) -> None:
        assert display_width(text) == expected


class TestFormatTable:
    def test_桁を揃える(self) -> None:
        source = ["| A | Bbbb |", "|---|---|", "| 1 | 2 |"]
        assert format_table(source) == [
            "| A | Bbbb |",
            "| - | ---- |",
            "| 1 | 2    |",
        ]

    def test_日本語の幅で揃える(self) -> None:
        """文字数で揃えると縦線がずれる。"""
        source = ["| 項目 | 値 |", "|---|---|", "| あ | 1 |"]
        formatted = format_table(source)
        widths = {display_width(line) for line in formatted}
        assert len(widths) == 1, f"行ごとに幅が違う: {formatted}"

    def test_崩れた表を直す(self) -> None:
        source = ["|A|B|", "|-|-|", "|   1   |2|"]
        assert format_table(source) == ["| A | B |", "| - | - |", "| 1 | 2 |"]

    def test_列数が足りない行を埋める(self) -> None:
        source = ["| A | B | C |", "|---|---|---|", "| 1 |"]
        assert format_table(source)[2] == "| 1 |   |   |"

    def test_余った列は捨てない(self) -> None:
        source = ["| A | B |", "|---|---|", "| 1 | 2 | 3 |"]
        assert "3" in format_table(source)[2]

    @pytest.mark.parametrize(
        ("marker", "alignment", "expected_delimiter"),
        [
            ("---", Alignment.NONE, "| ---- |"),
            (":--", Alignment.LEFT, "| :--- |"),
            ("--:", Alignment.RIGHT, "| ---: |"),
            (":-:", Alignment.CENTER, "| :--: |"),
        ],
    )
    def test_揃え指定を保つ(
        self, marker: str, alignment: Alignment, expected_delimiter: str
    ) -> None:
        formatted = format_table(["| Head |", f"|{marker}|", "| a |"])
        assert formatted[1] == expected_delimiter

    def test_右揃えの列は右に寄せる(self) -> None:
        formatted = format_table(["| A | Bbbb |", "|---|---:|", "| 1 | 2 |"])
        assert formatted[2] == "| 1 |    2 |"

    def test_中央揃えの列は中央に寄せる(self) -> None:
        formatted = format_table(["| A | Bbbbb |", "|---|:---:|", "| 1 | 2 |"])
        assert formatted[2] == "| 1 |   2   |"

    def test_引用の中の表も揃う(self) -> None:
        source = ["> | A | Bbbb |", "> |---|---|", "> | 1 | 2 |"]
        formatted = format_table(source)
        assert all(line.startswith("> ") for line in formatted)
        assert formatted[2] == "> | 1 | 2    |"

    def test_区切り行が無ければ整形しない(self) -> None:
        assert format_table(["| A | B |", "| 1 | 2 |"]) is None

    def test_空なら整形しない(self) -> None:
        assert format_table([]) is None

    def test_整形しても内容は変わらない(self) -> None:
        source = ["| 名前 | 個数 |", "|---|---:|", "| りんご | 3 |"]
        formatted = format_table(source)
        for line in ("名前", "個数", "りんご", "3"):
            assert line in "".join(formatted)

    def test_整形は冪等(self) -> None:
        source = ["| A | Bbbb |", "|---|---:|", "| 1 | 2 |"]
        once = format_table(source)
        assert format_table(once) == once


DOC: tuple[str, ...] = (
    "本文",
    "",
    "| A | B |",
    "|---|---|",
    "| 1 | 2 |",
    "",
    "続き",
)


class TestFindTable:
    @pytest.mark.parametrize("line", [2, 3, 4])
    def test_表の中ならその範囲を返す(self, line: int) -> None:
        assert find_table(list(DOC), line) == (2, 5)

    @pytest.mark.parametrize("line", [0, 1, 5, 6])
    def test_表の外ならNone(self, line: int) -> None:
        assert find_table(list(DOC), line) is None

    def test_区切り行が無ければNone(self) -> None:
        assert find_table(["| A | B |", "| 1 | 2 |"], 0) is None

    def test_パイプを含むだけの文は表にしない(self) -> None:
        """`本文に a | b と書いた` を表として扱わない。"""
        lines = ["本文に a | b と書いた", "価格は 100 | 税込"]
        assert find_table(lines, 0) is None

    def test_範囲外の行番号でも落ちない(self) -> None:
        assert find_table(list(DOC), 99) is None
