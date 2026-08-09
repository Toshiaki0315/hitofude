"""コードの字句解析（B-6 / 画面用）。

書き出し（`core/html.py`）は Pygments に HTML を組ませればよいが、画面は
`QSyntaxHighlighter` が**行単位**で動くので、行ごとの位置と色が要る。

`core/` にあるので PySide6 に依存しない（R3）。ヘッドレスで検査できる。
"""

import pytest

from hitofude.core.code_tokens import tokenize


def colors(spans) -> set[str]:
    return {span.color for line in spans for span in line}


class TestShape:
    def test_行ごとに返す(self) -> None:
        assert len(tokenize("x = 1\ny = 2\n", "python")) == 3

    def test_行の中の位置を返す(self) -> None:
        spans = tokenize("def f():", "python")[0]
        first = spans[0]
        assert (first.start, first.length) == (0, 3)  # `def`

    def test_2行目の位置は行頭から数える(self) -> None:
        """絶対位置のままだと 2 行目以降が右にずれる。"""
        spans = tokenize("x = 1\ndef f():", "python")[1]
        assert spans[0].start == 0

    def test_知らない言語は空(self) -> None:
        assert tokenize("x = 1", "そんな言語") == [[]]

    def test_言語が空でも落ちない(self) -> None:
        assert tokenize("x = 1", "") == [[]]

    def test_空のコードでも落ちない(self) -> None:
        assert tokenize("", "python") == [[]]


class TestColors:
    def test_予約語に色が付く(self) -> None:
        assert tokenize("def f():", "python")[0][0].color

    def test_予約語と文字列で色が違う(self) -> None:
        spans = tokenize('x = "文字"', "python")[0]
        assert len({s.color for s in spans}) >= 2

    def test_色は16進表記(self) -> None:
        for line in tokenize("def f():", "python"):
            for span in line:
                assert span.color.startswith("#") and len(span.color) == 7

    def test_太字や斜体も返す(self) -> None:
        spans = tokenize("def f():\n    # コメント\n", "python")
        assert any(s.bold or s.italic for line in spans for s in line)

    def test_暗い配色では色が変わる(self) -> None:
        assert colors(tokenize("def f():", "python")) != colors(
            tokenize("def f():", "python", dark=True)
        )


class TestLanguages:
    @pytest.mark.parametrize(
        ("lang", "code"),
        [
            ("python", "def f(): pass"),
            ("javascript", "const x = 1;"),
            ("json", '{"a": 1}'),
            ("bash", "echo hello"),
            ("html", "<p>x</p>"),
            ("sql", "SELECT * FROM t"),
        ],
    )
    def test_主な言語を扱える(self, lang: str, code: str) -> None:
        assert any(tokenize(code, lang))

    def test_別名でも引ける(self) -> None:
        """`js` や `py` と書く人がいる。"""
        assert any(tokenize("const x = 1;", "js"))


class TestMultiLine:
    """**行をまたぐ状態こそが、行単位で解析できない理由。**"""

    def test_複数行の文字列は続きも文字列(self) -> None:
        spans = tokenize('x = """\nここは文字列\n"""\n', "python")
        assert spans[1], "2 行目に色が付いていない"

    def test_文字列の中の予約語は予約語にしない(self) -> None:
        spans = tokenize('x = """\ndef f():\n"""\n', "python")
        inside = {s.color for s in spans[1]}
        keyword = tokenize("def f():", "python")[0][0].color
        assert keyword not in inside


class TestSourceUntouched:
    def test_元の文字列を変えない(self) -> None:
        code = "def f():\n    pass\n"
        tokenize(code, "python")
        assert code == "def f():\n    pass\n"

    def test_同じ入力からは同じ結果(self) -> None:
        assert tokenize("def f():", "python") == tokenize("def f():", "python")
