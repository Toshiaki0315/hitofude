"""文字数・単語数（ステータスバーの表示）。

**日本語には語の区切りが無い。** 英語式に空白で割ると、1 行の日本語が
まるごと 1 語になって意味を成さない。CJK は 1 文字を 1 語として数える。

数える対象はマーカーを外した本文（`plain_text`）。`**` や `#` は
読む文章の一部ではないので、分量に含めない。front matter も同様。
"""

import re
from dataclasses import dataclass

from hitofude.core.document import plain_text

# CJK（漢字・かな・全角記号）。1 文字を 1 語として数える範囲
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ々〆]")
# 語として数える塊。記号だけの並び（`,` や `!`）は語にしない
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class TextStats:
    characters: int
    words: int
    lines: int


def count(text: str) -> TextStats:
    """本文の分量を数える。"""
    body = plain_text(text)
    stripped = body.replace("\n", "")

    cjk = len(_CJK_RE.findall(stripped))
    # CJK を除いた残りから語を拾う。除かないと「Qt と PySide」の
    # 「と」が英単語の並びに巻き込まれて 1 語に潰れる
    latin = len(_WORD_RE.findall(_CJK_RE.sub(" ", stripped)))

    return TextStats(
        characters=len(stripped),
        words=cjk + latin,
        lines=len(body.rstrip("\n").split("\n")) if body.strip() else 0,
    )
