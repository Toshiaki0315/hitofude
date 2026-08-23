"""検索の問い合わせを読み取る（提案 3）。

`Cmd+Shift+F` は全文一致だけで、タグで絞れなかった。索引にはタグが入って
いるので、`#仕事 予算` のように**本文と同じ書き方**で絞れるようにする。

**入力欄は増やさない。** 書き方が本文と揃っているほうが覚えることが少ない。

**ここは Qt にも SQL にも触れない**（R3）。読み取るだけで、どう探すかは
`storage/index_db.py`、どこに出すかは UI の仕事。
"""

import re
from dataclasses import dataclass
from datetime import date

from hitofude.core import tags as tag_rules
from hitofude.core.template import strict_date

# 絞り込みのタグは本文と**同じ規則・同じ正規表現**（`core/tags.py`）で拾う。
# 判定を 2 箇所に書くと必ず片方だけ直されてずれる（tags.py 自身の警告）
_TAG_RE = tag_rules.TAG_RE

# 期間の絞り込み（案 A）。`after:2026-08-01` / `before:2026-08-31`。
# **日付として読めるものだけ**を絞り込みと見なす（下の `_read_date`）
_DATE_RE = re.compile(r"(?:(?<=\s)|\A)(?P<edge>after|before):(?P<value>\S*)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    """本文から探す言葉。タグだけを書いたときは空。"""

    tags: tuple[str, ...]
    """絞り込みのタグ。**全部満たすものだけ**を返す（AND）。"""

    after: date | None = None
    """この日以降に更新したものだけ。**その日を含む。**"""

    before: date | None = None
    """この日以前に更新したものだけ。**その日を含む。**"""

    unreadable_dates: tuple[str, ...] = ()
    """日付として読めなかった `after:` / `before:`（案 1）。

    **探すのはやめない**（言葉として残す）が、書き方が違うことは
    呼び出し側から知らせられるように覚えておく。0 件になった理由が
    画面から読めないと、打ち間違いに気づけない。
    """

    @property
    def filter_only(self) -> bool:
        """絞り込みだけで、本文の言葉が無いか。"""
        return bool(self.tags or self.after or self.before) and not self.text


def parse(query: str) -> SearchQuery:
    """打たれた文字列を「タグ」と「言葉」に分ける。

    **語では分けない。** 残りはそのまま全文検索へ渡す（`来週の予算` は
    打った通りの並びで探す。既存の挙動を変えない）。

    **AND で絞る。** OR だと、絞ったのに件数が増えて驚く。
    """
    tags: list[str] = []
    for found in _TAG_RE.finditer(query):
        # 索引は正規化済み（casefold・空セグメント除去）で持っている。
        # 揃えないと `#TODO` がサイドバーでは引けるのに検索だけ 0 件になる
        name = tag_rules.normalize(found.group("name"))
        if name and name not in tags:
            tags.append(name)

    edges: dict[str, date] = {}
    unreadable: list[str] = []

    def take_date(found: re.Match[str]) -> str:
        day = _read_date(found.group("value"))
        if day is None:
            unreadable.append(found.group(0))
            return found.group(0)  # 読めないものは言葉として残す
        edges[found.group("edge").lower()] = day
        return " "

    text = _DATE_RE.sub(take_date, query)
    text = _TAG_RE.sub(" ", text)
    # 置換の跡の空白を 1 つに畳む。`予算 #仕事 会議` を素直に置換すると
    # `予算   会議` になり、FTS（trigram のフレーズ一致）も LIKE もこの
    # 空白を文字として要求して黙って 0 件になる（コードレビュー指摘）
    text = " ".join(text.split())
    return SearchQuery(
        text=text,
        tags=tuple(tags),
        after=edges.get("after"),
        before=edges.get("before"),
        unreadable_dates=tuple(unreadable),
    )


def _read_date(value: str) -> date | None:
    """`2026-08-01` を日付にする。読めなければ `None`。

    **黙って絞らない。** 打ち間違い（`after:きのう`）を絞り込みと見なすと、
    0 件になった理由が画面から分からない。読めなければ言葉として扱い、
    「そう書いたものを探した」という結果になるほうが辿れる。

    読み方は日誌の判定と**同じ 1 本**（`template.strict_date`）を使う。
    別々に書くと、片方だけ緩めたときにずれる。
    """
    return strict_date(value)
