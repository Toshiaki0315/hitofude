"""テンプレートの差し込み（E-4）。

議事録や日報の雛形から新しいノートを作るとき、日付や題名を作った瞬間に
埋める。雛形は vault の `templates/` に置いた**ただの `.md`**で、
独自形式ではない（R1 と同じ考え方。真実はファイル側にある）。

差し込めるのは 4 つだけ。増やすほど「覚えないと使えない道具」になる。

| 印 | 中身 |
|---|---|
| `{{date}}` | 日付。`{{date:%Y年%m月%d日}}` で書式を変えられる |
| `{{time}}` | 時刻。同じく書式を指定できる |
| `{{title}}` | 付ける題名 |
| `{{cursor}}` | 作った直後にキャレットを置く場所（印は残らない） |

**知らない印は残す。** 消すと、書いた人には理由の分からない欠落になる。
"""

import re
from dataclasses import dataclass
from datetime import datetime

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"

CURSOR = "cursor"

# `{{名前}}` と `{{名前:書式}}`。書式に `}` は書けない（閉じ括弧と区別が付かない）
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*(?::([^}]*))?\}\}")


@dataclass(frozen=True, slots=True)
class Expanded:
    text: str
    cursor: int | None = None
    """`{{cursor}}` があった位置（差し込み後の文字数）。無ければ None。"""


def expand(text: str, *, now: datetime, title: str = "") -> Expanded:
    """雛形の印を埋める。

    日時は**引数で受け取る**。中で `datetime.now()` を呼ぶと、テストが
    実行した瞬間に依存して再現しなくなる。
    """
    cursor: int | None = None
    pieces: list[str] = []
    length = 0
    position = 0

    for match in _PLACEHOLDER_RE.finditer(text):
        replacement = _value(match.group(1), match.group(2), now=now, title=title)
        if replacement is None:
            continue  # 知らない印。そのまま本文として残す

        head = text[position : match.start()]
        pieces.append(head)
        length += len(head)

        if match.group(1) == CURSOR:
            # 2 つ以上あっても最初のところ。印はどれも残さない
            cursor = length if cursor is None else cursor
        else:
            pieces.append(replacement)
            length += len(replacement)
        position = match.end()

    pieces.append(text[position:])
    return Expanded("".join(pieces), cursor)


def _value(name: str, fmt: str | None, *, now: datetime, title: str) -> str | None:
    """印の中身。知らない名前なら None（＝そのまま残す）。"""
    if name == CURSOR:
        return ""  # 中身は空。位置だけを `expand` が覚える
    match name:
        case "date":
            return now.strftime(fmt or DATE_FORMAT)
        case "time":
            return now.strftime(fmt or TIME_FORMAT)
        case "title":
            return title
        case _:
            return None


def daily_title(day: datetime) -> str:
    """日次ノートの題名（E-4）。

    `{{date}}` と同じ書式にする。ファイル名にも一覧にも出るので、
    並べたときに揃っていないと日付順に見えない。
    """
    return day.strftime(DATE_FORMAT)
