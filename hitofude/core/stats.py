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

# 巨大ファイルガードの上限（spec §6.6 / R7）。装飾（scan + classify +
# setFormat）は行数に比例して効くため、超えたら装飾を諦めて素のまま開く
HUGE_FILE_BYTES = 2 * 1024 * 1024
HUGE_FILE_LINES = 20_000


def is_huge(text: str) -> bool:
    """装飾を諦めるべき大きさか（spec §6.6 / R7）。

    行数を先に見る（数えるだけで安い）。バイト数は「1 行が異常に長い」
    ファイルを拾うための保険で、行数で引っかからなかったときだけ数える。
    """
    if text.count("\n") + 1 > HUGE_FILE_LINES:
        return True
    return len(text.encode("utf-8")) > HUGE_FILE_BYTES


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
