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
from datetime import date, datetime

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


def strict_date(value: str) -> date | None:
    """`2026-08-14` を日付として読む。その形でなければ `None`。

    **書き戻して一致するものだけ**を認める。`strptime` はゼロ詰めの無い
    `2026-8-14` も通すが、書き方が 2 通りあると説明が増えるし、アプリは
    ゼロ詰めしか作らない（`daily_title`）。

    日誌の判定（`parse_daily`）と検索の `after:` / `before:`
    （`core/searchquery.py`）が**同じ規則を使う**ための 1 本。別々に
    書くと、片方だけ緩めたときに「日誌には見えないのに検索では日付」の
    ようなずれが出る。
    """
    try:
        day = datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        return None
    return day if day.strftime(DATE_FORMAT) == value else None


def parse_daily(title: str) -> date | None:
    """日次ノートの題名を日付として読む。日次でなければ `None`。

    **厳しく見る。** `2026-08-14 の記録` のように日付で始まるだけのノートを
    日誌に混ぜると、辿ったときに知らないノートへ飛ぶ。
    """
    return strict_date(title)


def daily_neighbour(titles: list[str], reference: date, *, forward: bool) -> str | None:
    """`reference` の前（後ろ）にある、いちばん近い日次ノートの題名。

    **書かなかった日は飛ばす。** 1 日ずつ止まると、間が空いたときに何度も
    押すことになる。**基準の日そのものは返さない**（今いる場所に留まる
    のは「移動できなかった」と区別が付かない）。

    端まで来たら `None`。作らない（書かなかった日にも空のノートができると
    一覧が埋まる）。呼ぶ側は「これ以上ありません」と伝えればよい。
    """
    days = [(parse_daily(title), title) for title in titles]
    found = [
        (day, title)
        for day, title in days
        if day is not None and (day > reference if forward else day < reference)
    ]
    if not found:
        return None
    return min(found)[1] if forward else max(found)[1]


def daily_title(day: datetime) -> str:
    """日次ノートの題名（E-4）。

    `{{date}}` と同じ書式にする。ファイル名にも一覧にも出るので、
    並べたときに揃っていないと日付順に見えない。
    """
    return day.strftime(DATE_FORMAT)
