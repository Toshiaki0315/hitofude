"""表の列幅を行ごとに計算し直さない（性能。2026-08-26）。

**起動が基準を割っていた**（1814ms / 基準 1500ms）。当てると、使い方の
ノートを開くのに 299ms かかり、**表の行を抜くと 42ms**（表 101 行で
257ms）。プロファイルの一位は `table.split_cells` で **14,534 回**——
`wrapped_columns` が**行ごとに表ぜんたいを数え直していた**（N 行の表で
N 回）ので、行数の 2 乗で効いていた。

**同じ表の列幅は行が変わっても同じ。** 1 つ覚えておけば足りる——表の行は
続けて処理されるので、次の行は必ず同じ表のもの。
"""

import pytest

pytestmark = pytest.mark.gui


def make_table(rows: int) -> str:
    head = "| 操作 | キー | 説明 |\n| --- | --- | --- |\n"
    body = "".join(f"| 操作の名前 {i} | Cmd+{i} | この操作の説明です |\n" for i in range(rows))
    return head + body


@pytest.fixture
def counted(monkeypatch):
    """`wrapped_columns` が何回呼ばれたかを数える。"""
    from hitofude.editor import highlighter

    calls: list[int] = []
    real = highlighter.wrapped_columns

    def counting(rows, available, **kwargs):
        calls.append(len(rows))
        return real(rows, available, **kwargs)

    monkeypatch.setattr(highlighter, "wrapped_columns", counting)
    return calls


class TestComputedOnce:
    def test_行の数だけ数え直さない(self, window, counted) -> None:
        """**ここが本題。** 20 行の表なら 20 回ではなく 1 回で足りる。"""
        window.editor.setPlainText(make_table(20))
        assert len(counted) == 1, f"{len(counted)} 回 数え直した"

    def test_中身の違う表はそれぞれ数える(self, window, counted) -> None:
        """**別の表は列の顔ぶれが違う。**

        中身が同じ表を 2 つ並べると 1 回で済む（鍵が同じなので当たり前）。
        最初そう書いて落ちた——**違う中身**で見る。
        """
        other = make_table(10).replace("操作の名前", "べつの名前")
        window.editor.setPlainText(make_table(10) + "\n本文\n\n" + other)
        assert len(counted) == 2

    def test_一行の表でも動く(self, window, counted) -> None:
        window.editor.setPlainText("| あ | い |\n| --- | --- |\n| 1 | 2 |\n")
        assert len(counted) == 1


class TestStillCorrect:
    """**速くしても結果は変えない。**"""

    def widths_of(self, window, line: int):
        found = window.editor.document().findBlockByNumber(line).userData()
        assert found is not None and found.wrapped is not None, f"{line} 行目が表でない"
        return list(found.wrapped.col_widths)

    def test_同じ表の行はどれも同じ列幅(self, window) -> None:
        """**覚えたものを配っている**ことの裏返し。ずれたら列がガタつく。

        （`core` の `wrapped_columns` と直に比べるのは単位が違って
        できない——あちらの既定は桁数、こちらは実測ピクセル。）
        """
        window.editor.setPlainText(make_table(20))
        first = self.widths_of(window, 2)
        assert first and all(w > 0 for w in first)
        for line in (3, 10, 21):
            assert self.widths_of(window, line) == first

    def test_幅が変われば数え直す(self, window, counted) -> None:
        """**覚えたものを使い回しすぎない。** 幅が変われば列も変わる。"""
        window.editor.setPlainText(make_table(10))
        before = len(counted)
        window.editor.set_content_width(400)
        assert len(counted) > before

    def test_中身が変われば数え直す(self, window, counted) -> None:
        window.editor.setPlainText(make_table(10))
        before = len(counted)
        window.editor.setPlainText(make_table(10).replace("操作の名前 3", "ずっと長い操作の名前 3"))
        assert len(counted) > before
