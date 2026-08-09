"""文字数と行数（ステータスバーの表示）。

**単語数は出さない。** 日本語には語の区切りが無く、かつて CJK を
1 文字 1 語として数えていたが、`東京都渋谷区` が 6 語になるなど
語数としての意味を成さなかった（ユーザーの指摘で取りやめ）。
本当に数えるには形態素解析が要り、ステータスバーの数字 1 つのために
依存を増やす価値はない。

数える対象はマーカーを外した本文（`plain_text`）。`**` や `#` は
読む文章の一部ではないので、分量に含めない。front matter も同様。
"""

from dataclasses import dataclass

from hitofude.core.document import plain_text


@dataclass(frozen=True, slots=True)
class TextStats:
    characters: int
    lines: int


def count(text: str) -> TextStats:
    """本文の分量を数える。"""
    body = plain_text(text)
    stripped = body.replace("\n", "")

    return TextStats(
        characters=len(stripped),
        lines=len(body.rstrip("\n").split("\n")) if body.strip() else 0,
    )
