"""検索の問い合わせを読み取る（提案 3）。

`Cmd+Shift+F` は全文一致だけで、タグで絞れなかった。索引にはタグが入って
いるので、`#仕事 予算` のように**本文と同じ書き方**で絞れるようにする。

**入力欄は増やさない。** 書き方が本文と揃っているほうが覚えることが少ない。

**ここは Qt にも SQL にも触れない**（R3）。読み取るだけで、どう探すかは
`storage/index_db.py`、どこに出すかは UI の仕事。
"""

import re
from dataclasses import dataclass

# 絞り込みのタグ。**行頭か空白のあと**に限る。本文の規則（`core/tags.py`）と
# 揃える。揃えないと `http://example.com#anchor` が絞り込みに見える
_TAG_RE = re.compile(r"(?:(?<=\s)|\A)#(?P<name>[^\s#]+)")


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    """本文から探す言葉。タグだけを書いたときは空。"""

    tags: tuple[str, ...]
    """絞り込みのタグ。**全部満たすものだけ**を返す（AND）。"""

    @property
    def tags_only(self) -> bool:
        """タグだけで絞っているか（本文の言葉が無い）。"""
        return bool(self.tags) and not self.text


def parse(query: str) -> SearchQuery:
    """打たれた文字列を「タグ」と「言葉」に分ける。

    **語では分けない。** 残りはそのまま全文検索へ渡す（`来週の予算` は
    打った通りの並びで探す。既存の挙動を変えない）。

    **AND で絞る。** OR だと、絞ったのに件数が増えて驚く。
    """
    tags: list[str] = []
    for found in _TAG_RE.finditer(query):
        name = found.group("name")
        if name not in tags:
            tags.append(name)

    text = _TAG_RE.sub(" ", query).strip()
    return SearchQuery(text=text, tags=tuple(tags))
