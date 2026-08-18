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


def _fold_with_origins(text: str) -> tuple[str, list[int]]:
    """casefold した文字列と、折り畳み後の各位置 → 元の位置の対応表。

    casefold は長さを変えることがある（`ﬁ`→`fi`、`ß`→`ss`）。折り畳んだ
    文字列上の一致位置を元の本文にそのまま使うと、合字より後ろの位置が
    全部ずれ、置換が本文を壊す。末尾に番兵として `len(text)` を足してあり、
    半開区間の終端をそのまま引ける。
    """
    pieces: list[str] = []
    origins: list[int] = []
    for index, char in enumerate(text):
        folded = char.casefold()
        pieces.append(folded)
        origins.extend([index] * len(folded))
    origins.append(len(text))
    return "".join(pieces), origins


def find_all(text: str, query: str, *, case_sensitive: bool = False) -> list[Match]:
    """一致箇所をすべて返す。重なる一致は数えない。

    `aaaa` から `aa` を 3 件見つけてしまうと、置換したときに範囲が重なって
    本文が壊れる。1 件見つけたらその末尾から探し直す。
    """
    if not query:
        # 空文字はあらゆる位置に一致する。検索バーを開いた瞬間に全文が
        # 光り、置換すれば本文が壊れるので、一致なしとして扱う
        return []

    if case_sensitive:
        matches: list[Match] = []
        start = text.find(query)
        while start != -1:
            matches.append((start, start + len(query)))
            start = text.find(query, start + len(query))
        return matches

    haystack, origins = _fold_with_origins(text)
    needle = query.casefold()

    matches = []
    found = haystack.find(needle)
    while found != -1:
        end = found + len(needle)
        # 元の文字の境界に揃った一致だけ返す。`ﬁ` の `i` だけは置換できない
        # （半分だけ消すか、`f` を巻き添えにするかの二択になる）ので捨てる
        aligned_start = found == 0 or origins[found] != origins[found - 1]
        aligned_end = end == len(haystack) or origins[end] != origins[end - 1]
        if aligned_start and aligned_end:
            matches.append((origins[found], origins[end]))
            found = haystack.find(needle, end)
        else:
            found = haystack.find(needle, found + 1)
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


def matching_line(text: str, query: str) -> int | None:
    """`query` を含む最初の行の番号（0 始まり）。無ければ None。

    全文検索（`Cmd+Shift+F`）で選んだノートの、**どこへ飛ぶか**を決める
    ために使う（G-1）。今まではノートの先頭が開くだけで、抜粋を見て選んだ
    のに `Cmd+F` で探し直しになっていた。

    **マーカーを外して見る。** 索引にはマーカーを外した写しが入っている
    （`document.searchable_text`）ので、`**予算**について` は
    `予算について` として引ける。素の本文で探すと、**索引では見つかるのに
    本文では見つからない**という食い違いが起きる。

    **索引に行番号は持たせない。** 持たせると索引の作りが変わって作り直しが
    要る。ノートを開けば数え直せて、開く数は 1 つだけ。
    """
    if not query.strip():
        return None

    from hitofude.core.block_parser import classify_line
    from hitofude.core.document import strip_markers
    from hitofude.core.models import BlockState

    needle = query.casefold()
    state = BlockState()
    for number, line in enumerate(text.split("\n")):
        info, state = classify_line(line, number, state)
        if needle in strip_markers(line, info).casefold() or needle in line.casefold():
            return number
    return None
