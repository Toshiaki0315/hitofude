"""Markdown をスライドの構造に割る（F-4）。

**書き出しの土台。** ここは純関数で、PowerPoint そのものは知らない
（組み立ては F-5 の `editor/pptx_export.py`）。分けておくと、割り方の
規則をヘッドレスで固定できる。

区切りはユーザーと決めた:

- `#` は**タイトルスライド**。その下の段落が副題になる
- `##` ごとに 1 枚（PowerPoint の取り込み F-3 と同じ区切り）
- 画像は**右側**に置くので、本文とは分けて持つ
- `>` の引用は**発表者ノート**（スライドには出さない）

**解析は `block_parser` を使う。** パーサを 2 本にしない（ADR-0007）。

`core/` にあるので PySide6 に依存しない（R3）。
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from hitofude.core import frontmatter
from hitofude.core.block_parser import classify_line
from hitofude.core.document import strip_markers
from hitofude.core.inline_scanner import image_only_line
from hitofude.core.models import BlockInfo, BlockState, BlockType

# スライドの題になる見出しの深さ
TITLE_LEVEL = 1
SLIDE_LEVEL = 2

# 箇条書きの階層は `block_parser` が**空白 2 つを 1 段**として数える
# （`- x` が 1、`    - x` が 3）。このアプリの字下げは 4 つなので、
# 半分にして 0 から始まる深さに直す
_LEVELS_PER_INDENT = 2


class BlockKind(Enum):
    PARAGRAPH = auto()
    BULLET = auto()
    HEADING = auto()
    """スライドの中の小見出し（`###` 以下）。"""

    CODE = auto()
    TABLE = auto()
    IMAGE = auto()
    """本文の並びには入れない（右側に置くため `Slide.images` が持つ）。"""


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0
    """箇条書きの階層（0 が第 1 階層）。"""

    language: str = ""
    """コードの言語。無ければ空。"""

    lines: list[str] = field(default_factory=list)
    """表の行（`| a | b |` のまま）。**セルには割らない。**

    割る道具（`editor/table.split_cells`）は表示側にあり、`core/` から
    そちらを参照すると層が逆向きになる。**同じ規則を 2 つ書かない**ため、
    割るのは使う側（F-5 の書き出し）に任せる。
    """


@dataclass(frozen=True, slots=True)
class Slide:
    title: str = ""
    blocks: list[Block] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    """右側に置く画像のパス。**本文とは分ける**（並びに混ぜない）。"""

    notes: str = ""
    """発表者ノート。スライドには出さない。"""


@dataclass(frozen=True, slots=True)
class Deck:
    title: str = ""
    subtitle: str = ""
    slides: list[Slide] = field(default_factory=list)


def _bullet_level(level: int) -> int:
    """行頭マーカーの位置を、0 から始まる階層に直す。

    `block_parser` は空白 2 つを 1 段として数える（`- x` が 1、
    `    - x` が 3）。字下げが半端でも段が飛ばないよう切り捨てる。
    """
    return max(0, (level - 1) // _LEVELS_PER_INDENT)


def split(text: str) -> Deck:
    """本文をスライドの並びにする。

    `#` より前や、最初の `##` より前に書かれた段落は**副題**として扱う。
    表紙に載る文章はふつうそこにあるため。
    """
    builder = _Builder()
    state = BlockState()
    for number, line in enumerate(frontmatter.split(text).body.split("\n")):
        info, state = classify_line(line, number, state)
        builder.feed(line, info)
    return builder.finish()


class _Builder:
    """1 行ずつ受け取って組み立てる。**状態は行の分類だけに従う。**"""

    def __init__(self) -> None:
        self._title = ""
        self._subtitle: list[str] = []
        self._slides: list[Slide] = []
        self._current: dict | None = None
        self._paragraph: list[str] = []
        self._code: list[str] = []
        self._language = ""
        self._table: list[str] = []
        self._notes: list[str] = []

    # ------------------------------------------------------------------ 受信

    def feed(self, line: str, info: BlockInfo) -> None:
        match info.type:
            case BlockType.CODE_FENCE_OPEN:
                self._flush_text()
                self._language = info.lang or ""
                self._code = []
            case BlockType.CODE_FENCE_BODY:
                self._code.append(line)
            case BlockType.CODE_FENCE_CLOSE:
                self._add(Block(BlockKind.CODE, "\n".join(self._code), language=self._language))
                self._code = []
            case BlockType.HEADING:
                self._heading(line, info)
            case BlockType.BLOCKQUOTE:
                self._flush_text()
                self._notes.append(strip_markers(line, info).strip())
            case BlockType.TABLE_ROW:
                self._flush_paragraph()
                self._table.append(line.strip())
            case BlockType.TABLE_DELIMITER:
                pass  # 区切り行は形式の飾り。中身を持たない
            case BlockType.BLANK:
                self._flush_text()
            case (
                BlockType.BULLET_LIST_ITEM | BlockType.ORDERED_LIST_ITEM | BlockType.TASK_LIST_ITEM
            ):
                self._flush_paragraph()
                self._add(
                    Block(
                        BlockKind.BULLET,
                        strip_markers(line, info).strip(),
                        _bullet_level(info.level),
                    )
                )
            case _:
                self._paragraph_line(line, info)

    # ---------------------------------------------------------------- 組み立て

    def _heading(self, line: str, info: BlockInfo) -> None:
        self._flush_text()
        body = strip_markers(line, info).strip()
        if info.level <= TITLE_LEVEL:
            self._title = self._title or body
            return
        if info.level == SLIDE_LEVEL:
            self._close_slide()
            self._current = {"title": body, "blocks": [], "images": []}
            return
        self._add(Block(BlockKind.HEADING, body))

    def _paragraph_line(self, line: str, info: BlockInfo) -> None:
        url = image_only_line(line)
        if url is not None:
            # **右側に置くので本文に混ぜない**（ユーザーと決めた並べ方）
            self._flush_text()
            if self._current is None:
                return
            self._current["images"].append(url)
            return

        body = strip_markers(line, info).strip()
        if body:
            self._paragraph.append(body)

    def _flush_paragraph(self) -> None:
        if self._paragraph:
            self._add(Block(BlockKind.PARAGRAPH, " ".join(self._paragraph)))
            self._paragraph = []

    def _flush_text(self) -> None:
        self._flush_paragraph()
        if self._table:
            self._add(Block(BlockKind.TABLE, lines=self._table))
            self._table = []

    def _add(self, block: Block) -> None:
        """スライドがまだ無ければ副題として扱う。

        表紙の文章は `#` の直後にあり、まだ 1 枚目が始まっていない。
        """
        if self._current is None:
            if block.kind is BlockKind.PARAGRAPH and block.text:
                self._subtitle.append(block.text)
            return
        self._current["blocks"].append(block)

    def _close_slide(self) -> None:
        if self._current is None:
            return
        self._slides.append(
            Slide(
                title=self._current["title"],
                blocks=self._current["blocks"],
                images=self._current["images"],
                notes="\n".join(self._notes).strip(),
            )
        )
        self._notes = []
        self._current = None

    def finish(self) -> Deck:
        self._flush_text()
        self._close_slide()
        return Deck(title=self._title, subtitle=" ".join(self._subtitle), slides=self._slides)
