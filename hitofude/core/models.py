"""コア層のデータモデル（spec §6.2）。

オフセットの約束: **すべて `[start, end)` の半開区間**。
`QSyntaxHighlighter.setFormat(start, length)` にそのまま渡せるようにするため。
唯一の例外はリビール判定の `InlineSpan.contains()` で、こちらは閉区間（§6.4）。
"""

from dataclasses import dataclass
from enum import Enum, auto

# 見出しは CommonMark の定義により 1..6
MIN_HEADING_LEVEL = 1
MAX_HEADING_LEVEL = 6


class BlockType(Enum):
    """Markdown ソース 1 行の種別。`QTextBlock` 1 個に 1:1 で対応する。"""

    PARAGRAPH = auto()
    HEADING = auto()
    BULLET_LIST_ITEM = auto()
    ORDERED_LIST_ITEM = auto()
    TASK_LIST_ITEM = auto()
    BLOCKQUOTE = auto()
    CODE_FENCE_OPEN = auto()
    CODE_FENCE_BODY = auto()
    CODE_FENCE_CLOSE = auto()
    TABLE_ROW = auto()
    TABLE_DELIMITER = auto()
    HORIZONTAL_RULE = auto()
    FRONT_MATTER = auto()
    BLANK = auto()


@dataclass(frozen=True, slots=True)
class BlockInfo:
    """Markdown ソース 1 行 = QTextBlock 1 個 に対するメタ情報。"""

    line: int
    type: BlockType
    level: int = 0
    """見出しレベル / リストのネスト深さ / 引用の深さ。"""

    marker_len: int = 0
    """行頭マーカーの文字数（`'## '` なら 3）。装飾を隠す範囲でもある。"""

    checked: bool | None = None
    """`TASK_LIST_ITEM` のときのみ意味を持つ。"""

    lang: str | None = None
    """コードフェンスの言語。`` ```python `` なら `"python"`。"""

    quote_depth: int = 0

    def __post_init__(self) -> None:
        for name in ("line", "level", "marker_len", "quote_depth"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} は 0 以上でなければならない: {getattr(self, name)}")
        if self.type is BlockType.HEADING and not (
            MIN_HEADING_LEVEL <= self.level <= MAX_HEADING_LEVEL
        ):
            raise ValueError(
                f"見出しの level は {MIN_HEADING_LEVEL}..{MAX_HEADING_LEVEL}: {self.level}"
            )


class SpanType(Enum):
    """1 行内のインライン要素の種別。"""

    STRONG = auto()
    EM = auto()
    STRONG_EM = auto()
    CODE = auto()
    STRIKE = auto()
    HIGHLIGHT = auto()
    LINK_TEXT = auto()
    LINK_URL = auto()
    IMAGE = auto()
    TAG = auto()
    AUTOLINK = auto()


@dataclass(frozen=True, slots=True)
class InlineSpan:
    """1 行内の文字オフセット。すべて `[start, end)` の半開区間。

    4 つのオフセットは常に
    `open_start <= open_end <= close_start <= close_end` を満たす。
    マーカーを持たない要素（タグなど）は `open_start == open_end` になる。
    """

    type: SpanType
    open_start: int
    """開きマーカーの開始。"""

    open_end: int
    """開きマーカーの終端 = 内容の開始。"""

    close_start: int
    """内容の終端 = 閉じマーカーの開始。"""

    close_end: int
    """閉じマーカーの終端。"""

    payload: str = ""
    """リンク URL、タグ名など、装飾以外に必要な付随情報。"""

    def __post_init__(self) -> None:
        offsets = (self.open_start, self.open_end, self.close_start, self.close_end)
        if self.open_start < 0:
            raise ValueError(f"オフセットは 0 以上でなければならない: {offsets}")
        if not (self.open_start <= self.open_end <= self.close_start <= self.close_end):
            raise ValueError(
                "オフセットは open_start <= open_end <= close_start <= close_end "
                f"を満たさなければならない: {offsets}"
            )

    @property
    def start(self) -> int:
        """マーカーを含む全体の開始。"""
        return self.open_start

    @property
    def end(self) -> int:
        """マーカーを含む全体の終端。"""
        return self.close_end

    @property
    def content_start(self) -> int:
        return self.open_end

    @property
    def content_end(self) -> int:
        return self.close_start

    @property
    def open_len(self) -> int:
        return self.open_end - self.open_start

    @property
    def close_len(self) -> int:
        return self.close_end - self.close_start

    def contains(self, position: int) -> bool:
        """リビール判定（spec §6.4）。

        ここだけ**閉区間** `[open_start, close_end]` で判定する。
        右端を含めることで、閉じマーカーの直後にキャレットを置いたまま
        編集を続けられる（そこで隠れると打ち直しができない）。
        """
        return self.open_start <= position <= self.close_end
