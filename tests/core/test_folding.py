"""見出しの折りたたみ範囲（I-4 / ADR-0019）。

範囲の計算は純関数に置き、GUI なしで検証する（R3）。
levels[i] は i 行目の見出しレベル（見出しでなければ 0）。
"""

import pytest

from hitofude.core.folding import section_end


class TestSectionEnd:
    @pytest.mark.parametrize(
        ("levels", "start", "expected"),
        [
            # H1 の下の本文は次の H1 の手前まで
            ([1, 0, 0, 1, 0], 0, 3),
            # 末尾まで見出しが無ければ最後まで
            ([1, 0, 0], 0, 3),
            # H2 は次の H2 で止まる
            ([2, 0, 2, 0], 0, 2),
            # H2 は浅い H1 でも止まる
            ([2, 0, 1, 0], 0, 2),
            # H1 は深い H2 を巻き込む
            ([1, 0, 2, 0, 1], 0, 4),
            # 本文の無い見出し（次の行が同レベル）
            ([1, 1, 0], 0, 1),
            # 途中の見出しから
            ([1, 0, 2, 0, 0, 1], 2, 5),
        ],
    )
    def test_範囲(self, levels, start, expected) -> None:
        assert section_end(levels, start) == expected

    def test_見出しでない行はそこで終わり(self) -> None:
        """呼び手の間違い。畳む範囲は無い（start+1）を返す。"""
        assert section_end([0, 0], 0) == 1
