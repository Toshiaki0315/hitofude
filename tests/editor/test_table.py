"""表の整形のテスト（spec §1.2「等幅フォント + 罫線揃え」）。

GFM / Qiita と同じ記法。**日本語は等幅フォントで 2 桁ぶんの幅**を取るので、
文字数ではなく表示幅で揃えないと縦線がずれる。
"""

import pytest

from hitofude.editor.table import (
    Alignment,
    _split_row,
    display_width,
    find_table,
    fits,
    format_table,
)


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


class TestAmbiguousWidth:
    """曖昧幅の文字（C-1 / 既知の不具合の原因）。

    Unicode の East Asian Width が `A`（Ambiguous）の文字は、環境によって
    半角にも全角にもなる。**日本語フォントでは全角**で描かれる。

    実測（表に使う BIZ UDGothic 15pt、半角 10.0px を 1 とする）:

        → 2.00 / ① 2.00 / ± 2.00 / § 2.00 / Ω 2.00

    1 桁として数えていたので、これらを含む行だけ桁がずれていた（実測 20px）。
    """

    @pytest.mark.parametrize("char", ["→", "①", "±", "§", "Ω"])
    def test_曖昧幅は全角として数える(self, char: str) -> None:
        assert display_width(char) == 2

    def test_半角は1のまま(self) -> None:
        assert display_width("abc123") == 6

    def test_全角は2のまま(self) -> None:
        assert display_width("日本語") == 6

    def test_矢印を含む行が揃う(self) -> None:
        formatted = format_table(["| → 前 | ① |", "| --- | --- |", "| 設計 | 野村 |"])
        widths = {display_width(line) for line in formatted}
        assert len(widths) == 1, formatted


class TestEscapedPipe:
    """セルの中のパイプ（ユーザー報告の原因）。

    GFM では `\\|` と書けばセルの中のリテラルなパイプになる。**エスケープを
    見ずに割ると、行が壊れて列が増える。**

    実際に `docs/manual_test.md` で起きた。`` `|` `` と書いた行が 4 セルと
    見なされ、整形が表全体をその列数に揃えた結果、GitHub で 13 列の空欄が
    並ぶ表になっていた。
    """

    def test_エスケープしたパイプは区切りにしない(self) -> None:
        assert _split_row(r"| a | `\|` の説明 | c |").cells == ["a", r"`\|` の説明", "c"]

    def test_素のパイプは今まで通り区切り(self) -> None:
        """エスケープしていないものは GFM でも区切り。ここは変えない。"""
        assert len(_split_row("| a | b | c |").cells) == 3

    def test_整形しても列が増えない(self) -> None:
        rows = [
            "| 見出し | 説明 |",
            "| --- | --- |",
            r"| 記号 | `\|` のこと |",
        ]
        formatted = format_table(rows)
        assert all(len(_split_row(line).cells) == 2 for line in formatted), formatted

    def test_エスケープを保つ(self) -> None:
        formatted = format_table(["| a | b |", "| --- | --- |", r"| x | `\|` |"])
        assert r"`\|`" in formatted[2]

    def test_桁も合う(self) -> None:
        """`\\|` は 2 文字だが画面には 1 文字として出る。"""
        formatted = format_table(["| a | b |", "| --- | --- |", r"| x | `\|` |"])
        assert len({display_width(line) for line in formatted}) == 1


class TestFits:
    """画面の幅に収まるか（ユーザー報告 / ADR-0003 追記）。

    収まらない行は折り返し、「ソースの 1 行 = 画面の 1 行」が崩れる。
    崩れた行に罫線は引けないので、判定をここに置いて描画側と共有する。
    """

    def test_収まる(self) -> None:
        assert fits("| a | b |", 20) is True

    def test_収まらない(self) -> None:
        assert fits("| aaaaaaaaaa | bbbbbbbbbb |", 10) is False

    def test_ちょうどは収まる(self) -> None:
        # `|` は隠れて幅を持たないので 3 桁ぶん引く
        assert fits("|ab|cd|", 4) is True
        assert fits("|ab|cde|", 4) is False

    def test_パイプは数えない(self) -> None:
        """隠れている記号に幅を持たせると、収まる表まで弾いてしまう。"""
        assert fits("|" * 10 + "ab", 2) is True

    def test_日本語は2桁(self) -> None:
        assert fits("|あい|", 4) is True
        assert fits("|あいう|", 4) is False

    def test_幅が分からないうちは収まる扱い(self) -> None:
        """起動直後に表が生の Markdown で出るより、あとで気づくほうがまし。"""
        assert fits("| とても長い行 |", 0) is True
        assert fits("| とても長い行 |", -1) is True
