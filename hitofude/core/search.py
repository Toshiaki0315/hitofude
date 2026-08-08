"""開いている 1 つのノートの中を探す（`Cmd+F`）。

`Cmd+O` はノートを探し、`Cmd+Shift+F` は索引を使ってノートを横断する。
ここはそのどちらでもなく、**今見ている本文の中**を前後に辿る層。

R3 に従い GUI に依存しない。R4 により `QTextCursor` の位置と文字オフセットは
常に 1:1 なので、ここが返す位置はそのままカーソルへ渡せる。

**正規表現は使わない。** ユーザーが打った `.` や `*` が予想外の位置に
一致すると、置換で本文を壊す。打った文字をそのまま探す。
"""

type Match = tuple[int, int]
"""一致範囲。半開区間 `[start, end)`。`InlineSpan` と同じ約束。"""


def _fold(text: str, *, case_sensitive: bool) -> str:
    return text if case_sensitive else text.casefold()


def find_all(text: str, query: str, *, case_sensitive: bool = False) -> list[Match]:
    """一致箇所をすべて返す。重なる一致は数えない。

    `aaaa` から `aa` を 3 件見つけてしまうと、置換したときに範囲が重なって
    本文が壊れる。1 件見つけたらその末尾から探し直す。
    """
    if not query:
        # 空文字はあらゆる位置に一致する。検索バーを開いた瞬間に全文が
        # 光り、置換すれば本文が壊れるので、一致なしとして扱う
        return []

    haystack = _fold(text, case_sensitive=case_sensitive)
    needle = _fold(query, case_sensitive=case_sensitive)

    matches: list[Match] = []
    start = haystack.find(needle)
    while start != -1:
        matches.append((start, start + len(needle)))
        start = haystack.find(needle, start + len(needle))
    return matches


def find_next(
    text: str,
    query: str,
    start: int,
    *,
    backward: bool = False,
    case_sensitive: bool = False,
) -> Match | None:
    """`start` から見て次（前）の一致を返す。端まで来たら反対側へ回り込む。

    回り込むのは、探し直すたびに端で止まるより、同じキーを押し続けて
    全部を見て回れるほうが速いため。一致が 1 つしかなければ、そこへ戻る。
    """
    matches = find_all(text, query, case_sensitive=case_sensitive)
    if not matches:
        return None

    if backward:
        earlier = [match for match in matches if match[1] <= start]
        return earlier[-1] if earlier else matches[-1]

    later = [match for match in matches if match[0] >= start]
    return later[0] if later else matches[0]


def replace_all(
    text: str, query: str, replacement: str, *, case_sensitive: bool = False
) -> tuple[str, int]:
    """すべての一致を置き換える。置き換えた本文と件数を返す。

    置換した結果を再び拾わない（`a` → `aa` で無限に増えない）。
    後ろから置き換えるので、前の位置がずれない。
    """
    matches = find_all(text, query, case_sensitive=case_sensitive)
    if not matches:
        return text, 0

    replaced = text
    for begin, end in reversed(matches):
        replaced = replaced[:begin] + replacement + replaced[end:]
    return replaced, len(matches)
