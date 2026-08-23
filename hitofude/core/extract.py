"""選択範囲を別のノートに切り出す（M-1 / 仮身化）。

BTRON の「選択した部分が新しい実身として切り出され、元の場所には仮身が
残る」を Markdown に写したもの。**ここは Qt もファイルも知らない**（R3）。

**題名は本文から決まる。** ノートの題名は `document.title_of`（最初の H1 →
最初の非空行）が決めるので、こちらで勝手に付けた題名は索引に載らない。
`[[…]]` は題名で解決する（E-6）から、ずれると**リンクの先が行方不明**に
なり、しかも押すと「無ければ作る」で 2 つ目ができる。気づきにくい。

だから**題名を作り直したときは見出しを足して、本文から同じ題名が読めるように
する**。この不変条件は `tests/core/test_extract.py::TestLinkAlwaysResolves`
が全ケースで見ている。
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from hitofude.core.document import UNTITLED, title_of

MAX_TITLE_LENGTH = 40
"""題名の長さ。**本文の 1 行がそのまま題名になる**（見出しが無いとき）ので、
切らないと `[[…]]` が本文を埋め尽くす。ファイル名の上限（200 バイト）とは
別で、こちらは読みやすさのため。"""

# `[[…]]` の中に入るとリンクがそこで切れて別のものを指す。`|` は別名の
# 記法に見える（`core/notelink.py` が同じ理由で除いている）
_BREAKS_LINK = re.compile(r"[\[\]|]")

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Extracted:
    """切り出した結果。**呼ぶ側はこの 3 つを使うだけ。**"""

    title: str
    """新しいノートの題名。`text` から `title_of` で読めることが保証される。"""

    text: str
    """新しいノートの本文。"""

    link: str
    """元の場所に残す文字列（`[[題名]]`）。"""


def extract(selection: str, *, taken: Iterable[str] = ()) -> Extracted | None:
    """選択範囲から切り出す材料を作る。中身が無ければ `None`。

    `taken` は既にある題名。**同じ題名を 2 つ作らない** — `[[…]]` は題名で
    解決するので、重なるとどちらへ飛ぶか決まらない。ファイル名は
    `unique_path` が避けるが、**題名は本文から決まる**ので避けてくれない。
    """
    body = selection.strip()
    if not body:
        return None

    natural = title_of(body, UNTITLED)
    title = _fit(natural)
    title = _avoid(title, taken)

    # **本文から同じ題名が読めるときだけ、本文を触らない。** 触らずに済む
    # ほうが「書いた文がそのまま移った」と分かる（R1 の感覚）
    text = body if title_of(body, UNTITLED) == title else f"# {title}\n\n{body}"
    return Extracted(title=title, text=text, link=f"[[{title}]]")


def _fit(title: str) -> str:
    """題名として使える形にする。**落とした結果が空なら「無題」。**"""
    cleaned = _WHITESPACE.sub(" ", _BREAKS_LINK.sub("", title)).strip()
    if not cleaned:
        return UNTITLED
    return cleaned[:MAX_TITLE_LENGTH].strip() or UNTITLED


def _avoid(title: str, taken: Iterable[str]) -> str:
    """既にある題名を避ける。`resolve` と同じく大文字小文字を区別しない。"""
    used = {name.casefold() for name in taken}
    if title.casefold() not in used:
        return title
    number = 2
    while f"{title} {number}".casefold() in used:
        number += 1
    return f"{title} {number}"
