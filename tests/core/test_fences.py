"""コードフェンスの門番（レビュー 2026-08-25）。

開閉の規則はここが唯一の置き場（tags / wikilink が同じものを 3 回
書いていた）。規則そのものの検査もここに置く。
"""

import pytest

from hitofude.core.fences import FenceGate


def walk(lines: list[str]) -> list[bool]:
    """各行が「本文として読まれるか」を返す。"""
    gate = FenceGate()
    return [not gate.crosses(line) and not gate.inside for line in lines]


class TestGate:
    def test_フェンスの中は読まない(self) -> None:
        assert walk(["前", "```", "中", "```", "後"]) == [True, False, False, False, True]

    def test_チルダでも開く(self) -> None:
        assert walk(["~~~", "中", "~~~", "後"]) == [False, False, False, True]

    def test_違う文字では閉じない(self) -> None:
        assert walk(["```", "~~~", "後ろもまだ中"]) == [False, False, False]

    def test_短い区切りでは閉じない(self) -> None:
        """開きより長い区切りで閉じる（CommonMark）。"""
        assert walk(["````", "```", "まだ中", "````", "外"]) == [
            False,
            False,
            False,
            False,
            True,
        ]

    def test_長い区切りなら閉じる(self) -> None:
        assert walk(["```", "````", "外"]) == [False, False, True]

    @pytest.mark.parametrize("indent", ["", " ", "  ", "   "])
    def test_前置の空白は3つまで許す(self, indent: str) -> None:
        assert walk([f"{indent}```", "中"]) == [False, False]

    def test_4つ空くとフェンスではない(self) -> None:
        assert walk(["    ```", "本文"]) == [True, True]
