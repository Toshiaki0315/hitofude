"""Python 文字列と QString（UTF-16）の位置変換。

Python の str はコードポイント単位、Qt の QString は UTF-16 単位で数える。
🍎 や 𠮷 など BMP 外の文字は Python では 1 文字、UTF-16 では 2 単位
（サロゲートペア）になる。R4 の「`QTextCursor` の位置とソース文字列の
オフセットが 1:1」は BMP 内でしか成り立たないため、core が返す位置を
Qt の API（`setFormat` / `QTextCursor.setPosition`）へ渡す境界、および
Qt から受け取った位置で Python 文字列を引く境界で、必ずここを通す。

R3 に従い GUI に依存しない。ただの文字列計算なので core に置く。
"""

# BMP の外（サロゲートペアで表す文字）の始まり
_SUPPLEMENTARY = 0x10000


def py_to_utf16(text: str, index: int) -> int:
    """Python の文字位置 → UTF-16 の位置。

    `index` が範囲外なら全文を数えた値になる（呼び出し側の clamp を邪魔しない）。
    """
    prefix = text[:index]
    return len(prefix) + sum(1 for char in prefix if ord(char) >= _SUPPLEMENTARY)


def utf16_to_py(text: str, index: int) -> int:
    """UTF-16 の位置 → Python の文字位置。

    サロゲートペアの内側を指していたら、その文字の頭へ寄せる
    （Qt はペアの間へカーソルを置かないので、来るとすれば計算誤りの防御）。
    範囲外は末尾へ丸める。
    """
    units = 0
    for position, char in enumerate(text):
        width = 2 if ord(char) >= _SUPPLEMENTARY else 1
        if index < units + width:
            return position
        units += width
    return len(text)
