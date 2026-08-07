"""Enter / Tab の入力補助（spec §5.5）。

判断は**純関数**に閉じ込め、`QTextCursor` を触る部分と分けている。
入力補助は条件分岐が多く、GUI 越しに検査すると組み合わせを網羅できないため。

判定には `BlockData` に入っている `BlockInfo`（ハイライタが作った）を使う。
行を再解析しないので、コードフェンスの中かどうかも自動的に正しく効く
（フェンス内は `CODE_FENCE_BODY` になり、どの補助も発火しない）。
"""

import re
from dataclasses import dataclass
from enum import Enum, auto

from hitofude.core.models import BlockInfo, BlockType

INDENT = "  "

_LIST_TYPES = frozenset(
    {BlockType.BULLET_LIST_ITEM, BlockType.ORDERED_LIST_ITEM, BlockType.TASK_LIST_ITEM}
)

_ORDERED_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<number>\d{1,9})(?P<delim>[.)])(?P<space>[ \t]+)")
_TASK_RE = re.compile(r"^(?P<prefix>[ \t]*[-*+][ \t]+)\[[ xX]\](?P<space>[ \t]+)")
_QUOTE_LEVEL_RE = re.compile(r"^[ \t]*>[ \t]?")


class EnterKind(Enum):
    DEFAULT = auto()
    """Qt に任せる（普通の改行）。"""

    CONTINUE = auto()
    """改行して、次の行にマーカーを引き継ぐ。"""

    RESET = auto()
    """改行せず、現在行のマーカーを 1 段外す。"""


@dataclass(frozen=True, slots=True)
class EnterAction:
    kind: EnterKind
    text: str = ""
    """CONTINUE なら次行の接頭辞、RESET なら現在行の新しい内容。"""


_DEFAULT = EnterAction(EnterKind.DEFAULT)


def enter_action(line: str, column: int, info: BlockInfo | None) -> EnterAction:
    """Enter を押したときの挙動を決める。

    `info` が None（まだハイライトされていない）なら何もしない。
    推測で補助を効かせるより、素の改行にしたほうが事故が小さい。
    """
    if info is None:
        return _DEFAULT
    if info.type not in _LIST_TYPES and info.type is not BlockType.BLOCKQUOTE:
        return _DEFAULT
    if column < info.marker_len:
        # マーカーの内側にキャレットがある。ここで継承すると壊れた行ができる
        return _DEFAULT

    if not line[info.marker_len :].strip():
        return EnterAction(EnterKind.RESET, _outdent(line, info))
    return EnterAction(EnterKind.CONTINUE, _continuation(line, info))


def _continuation(line: str, info: BlockInfo) -> str:
    match info.type:
        case BlockType.TASK_LIST_ITEM:
            task = _TASK_RE.match(line)
            # 済んだ項目の次に済んだ項目が来るのはおかしいので必ず未チェック
            return (
                f"{task.group('prefix')}[ ]{task.group('space')}"
                if task
                else line[: info.marker_len]
            )
        case BlockType.ORDERED_LIST_ITEM:
            ordered = _ORDERED_RE.match(line)
            if ordered is None:
                return line[: info.marker_len]
            # 以降の番号は振り直さない（§5.5-3）。ソースの diff を最小にするため
            number = int(ordered.group("number")) + 1
            return (
                f"{ordered.group('indent')}{number}{ordered.group('delim')}{ordered.group('space')}"
            )
        case _:
            return line[: info.marker_len]


def _outdent(line: str, info: BlockInfo) -> str:
    """空の項目を 1 段浅くする（spec §5.5-2 の 2 段階解除）。"""
    if info.type is BlockType.BLOCKQUOTE:
        stripped = _QUOTE_LEVEL_RE.sub("", line, count=1)
        return stripped if stripped.strip() else stripped.rstrip()

    if line.startswith(INDENT):
        return line[len(INDENT) :]
    return ""


def indent_action(line: str, info: BlockInfo | None, *, forward: bool) -> str | None:
    """Tab / Shift+Tab を押したときの新しい行。対象外なら None。

    リスト行以外では None を返し、通常のタブ挿入に任せる（§5.4）。
    """
    if info is None or info.type not in _LIST_TYPES:
        return None
    if forward:
        return INDENT + line
    if line.startswith(INDENT):
        return line[len(INDENT) :]
    return None
