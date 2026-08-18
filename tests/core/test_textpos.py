"""Python 文字列と QString（UTF-16）の位置変換のテスト。

Python の str はコードポイント単位、Qt の QString は UTF-16 単位で数える。
🍎 や 𠮷 は Python では 1 文字、UTF-16 では 2 単位（サロゲートペア）。
R4 の「カーソル位置とオフセットの 1:1」は BMP 内でしか成り立たないため、
Qt の API へ渡す境界で変換する。
"""

import pytest

from hitofude.core.textpos import py_to_utf16, utf16_to_py


class TestPyToUtf16:
    @pytest.mark.parametrize(
        ("text", "index", "expected"),
        [
            ("abc", 0, 0),
            ("abc", 3, 3),
            ("あいう", 2, 2),  # BMP 内は恒等
            ("🍎a", 0, 0),
            ("🍎a", 1, 2),  # 絵文字は UTF-16 で 2 単位
            ("🍎a", 2, 3),
            ("a🍎b🍇c", 4, 6),
            ("𠮷野家", 1, 2),  # サロゲートペアの漢字も同じ
        ],
    )
    def test_変換(self, text: str, index: int, expected: int) -> None:
        assert py_to_utf16(text, index) == expected


class TestUtf16ToPy:
    @pytest.mark.parametrize(
        ("text", "index", "expected"),
        [
            ("abc", 2, 2),
            ("🍎a", 0, 0),
            ("🍎a", 2, 1),
            ("🍎a", 3, 2),
            ("🍎a", 1, 0),  # ペアの内側はその文字の頭へ寄せる
            ("a🍎b🍇c", 6, 4),
            ("🍎a", 99, 2),  # 範囲外は末尾へ丸める
        ],
    )
    def test_変換(self, text: str, index: int, expected: int) -> None:
        assert utf16_to_py(text, index) == expected

    def test_往復で元に戻る(self) -> None:
        text = "a🍎い𠮷u"
        for index in range(len(text) + 1):
            assert utf16_to_py(text, py_to_utf16(text, index)) == index
