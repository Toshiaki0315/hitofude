"""`#tag` の抽出・階層分解・正規化（spec §6.5 規則 7, §7.2, §7.3）。

タグは front matter ではなく**本文が真実**（§7.2）。ノートを保存するたびに
本文を全走査して索引を張り直す。

`#` は見出しマーカーと同じ文字なので、区別の条件が仕様の核心になる:

- `#` の直前は**行頭または空白**であること
- `#` の直後は空白でも `#` でもないこと

`TAG_RE` は `inline_scanner`（タスク 1-7）からも使う。判定を 2 箇所に書くと
必ず片方だけ直され、サイドバーとエディタで見えるタグがずれる。
"""

import re
from dataclasses import dataclass

SEPARATOR = "/"

# (?<![^\s]) は「直前が非空白ではない」＝行頭または空白の後、を表す。
# 文字列先頭でも成立するので \A を別に書かなくてよい。
TAG_RE = re.compile(r"(?<![^\s])#(?P<name>[^\s#]+)")

# コードフェンスの開始/終了。前置の空白は 3 つまで（CommonMark）。
_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")

# インラインコード。同じ数のバッククォートで閉じる。
_INLINE_CODE_RE = re.compile(r"(?P<ticks>`+)(?P<body>.+?)(?P=ticks)", re.DOTALL)

# コードを潰すときの詰め物。空白にすると「直前が空白」の条件を満たしてしまい、
# 本来タグではない `` `code`#tag `` を拾ってしまうため、非空白文字を使う。
_MASK_CHAR = "x"


@dataclass(frozen=True, slots=True)
class TagMatch:
    """本文中に出現した 1 つのタグ。オフセットは `[start, end)`。"""

    name: str
    """正規化済みのフルパス（`work/会議`）。"""

    raw: str
    """原文のまま（`#` は含まない）。"""

    start: int
    """`#` の位置。"""

    end: int


def normalize(raw: str) -> str:
    """索引に載せる形へ揃える（spec §7.3: 小文字フルパス）。"""
    return SEPARATOR.join(part for part in raw.split(SEPARATOR) if part).casefold()


def _mask_inline_code(line: str) -> str:
    """インラインコードを非空白文字で潰す。長さは変えない（オフセットを保つため）。"""
    return _INLINE_CODE_RE.sub(lambda m: _MASK_CHAR * len(m.group(0)), line)


def find_all(text: str) -> list[TagMatch]:
    """本文中のタグを出現順に返す。

    コードフェンスの内側とインラインコードは走査しない。`#include` や
    `#!/bin/sh` がタグツリーに現れると実用にならないため
    （§6.5 規則 1「コード範囲内では他の記法を一切解釈しない」と同じ方針）。
    """
    matches: list[TagMatch] = []
    offset = 0
    fence: str | None = None

    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match is not None:
            found = fence_match.group("fence")
            if fence is None:
                fence = found
            elif found[0] == fence[0] and len(found) >= len(fence):
                fence = None
            offset += len(line) + 1
            continue

        if fence is None:
            masked = _mask_inline_code(line)
            for match in TAG_RE.finditer(masked):
                raw = match.group("name")
                matches.append(
                    TagMatch(
                        name=normalize(raw),
                        raw=raw,
                        start=offset + match.start(),
                        end=offset + match.end(),
                    )
                )

        offset += len(line) + 1

    return matches


def extract(text: str) -> list[str]:
    """正規化済みタグを、重複を除いて出現順に返す。"""
    seen: dict[str, None] = {}
    for match in find_all(text):
        seen.setdefault(match.name, None)
    return list(seen)


def ancestors(tag: str) -> list[str]:
    """自身を含む祖先を浅い順に返す（`a/b/c` → `a`, `a/b`, `a/b/c`）。

    サイドバーのタグツリー（§5.1）を組むときに使う。
    """
    parts = tag.split(SEPARATOR)
    return [SEPARATOR.join(parts[: i + 1]) for i in range(len(parts))]


def parent(tag: str) -> str | None:
    """1 つ上の階層。最上位なら None。"""
    head, separator, _ = tag.rpartition(SEPARATOR)
    return head if separator else None


def leaf(tag: str) -> str:
    """末端の名前だけ（`work/会議` → `会議`）。ツリーの表示ラベルに使う。"""
    return tag.rpartition(SEPARATOR)[2]
