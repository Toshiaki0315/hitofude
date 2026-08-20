"""`[[ノート名]]` の打ちかけ判定と候補絞り（ユーザー要望）。

書けるのに候補が出ないと、正確な名前を覚えているか、別のノートを開いて
確かめることになる。タグ（`core/tags.py`）と同じ形で補完する。

**ここは Qt に触れない**（R3）。どこに出すか・何を候補にするかは UI 側。
"""

import re

from hitofude.core import tags as _tags

# 打ちかけの `[[名前`。**閉じていないものだけ**を拾う。
#
# - `|` と `]` を含まない … 別名の記法（`[[名前|表示]]`）は未対応で、
#   中途半端に補完すると名前が壊れる（`inline_scanner` と揃える）
# - `[` も含まない … `[[[` のような打ち間違いで名前が伸びない
# - 行をまたがない … `[[` の後で改行したら、それはもうリンクではない
_TYPING_RE = re.compile(r"\[\[(?P<name>[^\[\]|\n]*)\Z")


def prefix_at(line: str, column: int) -> str | None:
    """その位置で打ちかけているノート名。リンクの外なら `None`。

    **カーソルより後ろは見ない。** `[[会議メモ` の途中に居るときは、
    打った分（`会議`）で絞る。後ろまで含めると、直そうとしている綴りで
    絞ってしまう（タグ補完と同じ考え方）。
    """
    found = _TYPING_RE.search(line[:column])
    return found.group("name") if found is not None else None


# カーソルから閉じ `]]` までに残っている名前。閉じたリンクの中で
# 確定したとき、この分も一緒に置き換える（残すと `[[会議メモ]]モ]]` になる）
_TAIL_RE = re.compile(r"\A(?P<name>[^\[\]|\n]*)\]\]")


def closing_tail(rest: str) -> int | None:
    """カーソル位置から閉じ `]]` までに残っている名前の長さ。

    閉じが無ければ `None`（開きかけのリンク。行の残りは名前ではないので
    食べてはいけない）。
    """
    found = _TAIL_RE.match(rest)
    return len(found.group("name")) if found is not None else None


def matches(prefix: str, titles: list[str]) -> list[str]:
    """前方一致で候補を絞る。大文字小文字は区別しない。

    絞りの規則はタグ補完と**同じもの**を使う（`tags.matches`）。
    「打ったものと同じだけなら出さない」という Enter の解釈に関わる
    規則が 2 か所にあると、片方だけ直されて挙動がずれる。
    `[[` 直後（`prefix` が空）に全部出るのも同じ実装で成立する。
    """
    return _tags.matches(prefix, titles)
