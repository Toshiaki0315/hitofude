"""見出しの一覧（C-2 / アウトライン）。

長いノートで迷子にならないよう、見出しへ飛べるようにする。

**分類はハイライタと同じ経路を使う**（`block_parser.classify_line`）。
自前で `#` を数えると、コードブロックの中の `# コメント` や `#タグ` を
見出しとして拾ってしまう。
"""

from dataclasses import dataclass

from hitofude.core.block_parser import classify_line
from hitofude.core.models import BlockState, BlockType


@dataclass(frozen=True, slots=True)
class Heading:
    line: int
    """0 始まりの行番号。飛び先に使う。"""

    level: int
    text: str
    """`#` と前後の空白を外した中身。**装飾の記号は残す。**

    消すと画面に出ている行と対応が取れず、探しているものを見つけにくい。
    """


def headings(text: str) -> list[Heading]:
    """本文の見出しを上から順に返す。"""
    found: list[Heading] = []
    state = BlockState()
    for number, line in enumerate(text.split("\n")):
        info, state = classify_line(line, number, state)
        # 引用の中の見出しは「引用元の文章」で、このノートの構造ではない
        if info.type is not BlockType.HEADING or info.quote_depth:
            continue
        found.append(
            Heading(line=number, level=info.level, text=line[info.marker_len :].strip(" #\t"))
        )
    return found
