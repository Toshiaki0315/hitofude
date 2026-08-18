"""見出しの折りたたみ範囲（I-4 / ADR-0019）。

畳む・戻すの実行はエディタ側（`QTextBlock.setVisible`）だが、
**どこまで畳むか**は行のレベル列だけで決まる純関数にする（R3）。
"""

from collections.abc import Sequence


def section_end(levels: Sequence[int], start: int) -> int:
    """見出し行 `start` の節の終わり（排他）。

    `levels[i]` は i 行目の見出しレベル。見出しでない行は 0。
    `start` の次の行から、**同じか浅い**見出しが現れる手前までが節。
    見出しでない行を渡されたら畳む範囲は無い（`start + 1`）。
    """
    level = levels[start]
    if level <= 0:
        return start + 1
    for line in range(start + 1, len(levels)):
        if 0 < levels[line] <= level:
            return line
    return len(levels)
