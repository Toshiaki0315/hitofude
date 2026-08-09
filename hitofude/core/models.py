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

# `:::note` の種類（B-3 / Qiita 記法）
NOTE_KINDS = ("info", "warn", "alert")
DEFAULT_NOTE_KIND = NOTE_KINDS[0]
"""種類を省いた（`:::note` だけの）ときの扱い。省略は書き忘れではない。"""

UNKNOWN_NOTE_KIND = "unknown"
"""知らない綴り（`:::note warm` など）。

**`info` には寄せない。** 寄せると青い線が出るだけで、間違えたことに
気づく手掛かりが無くなる（ユーザー報告）。囲みとしては成立させて本文は
残しつつ、灰色の線にして区切り行も隠さない。
"""

# 状態に詰めるときの並び。0 は「囲みの外」なので番号は 1 始まり
_STATE_NOTE_KINDS = (*NOTE_KINDS, UNKNOWN_NOTE_KIND)


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
    NOTE_DELIMITER = auto()
    """`:::note info` と閉じの `:::`（B-3 / Qiita 記法）。"""

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

    note_kind: str | None = None
    """`:::note` の種類（`info` / `warn` / `alert`）。

    **囲みの中の行すべてに付く。** 縦線は行ごとに描くので、区切り行だけが
    知っていても引けない。
    """

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


@dataclass(frozen=True, slots=True)
class BlockState:
    """行から次の行へ引き継ぐ状態（spec §6.3）。

    `QSyntaxHighlighter` が行間で渡せるのは `setCurrentBlockState()` の
    **int 1 個だけ**。そこにビットフラグとして詰め込む。

    フェンスの記号と長さも持つ理由: ` ``` ` で開いたコードブロックを `~~~` で
    閉じてはいけないし、`` ```` `` で開いたものは ` ``` ` では閉じられない
    （CommonMark）。これを知らないとコードブロックの範囲が壊れる。
    """

    in_code: bool = False
    in_front_matter: bool = False
    in_table: bool = False
    after_blank: bool = True
    """直前が空行か。インデントコードは空行の後でしか始まらない（CommonMark）。"""

    in_list: bool = False
    """リストの中か。中では字下げが入れ子を意味するのでコードにしない（§6.4）。"""

    in_indented_code: bool = False
    note_kind: str = ""
    """`:::note` の中に居るか。空文字なら囲みの外（B-3）。"""

    quote_depth: int = 0
    fence_char: str = ""
    fence_len: int = 0

    _CODE = 1 << 0
    _FRONT_MATTER = 1 << 1
    _TABLE = 1 << 2
    _TILDE_FENCE = 1 << 3
    _QUOTE_SHIFT = 4
    _QUOTE_MASK = 0b1111
    _FENCE_LEN_SHIFT = 8
    _FENCE_LEN_MASK = 0b11111
    _NOT_AFTER_BLANK = 1 << 13
    _IN_LIST = 1 << 14
    _INDENTED_CODE = 1 << 15
    # 囲みの種類。0 は「囲みの外」。既定が 0 でなければならないので
    # 種類の番号は 1 始まりで持つ（B-3）
    _NOTE_SHIFT = 16
    # 4 種類 +「囲みの外」で 5 通り。2 ビットでは足りない
    _NOTE_MASK = 0b111

    MAX_QUOTE_DEPTH = _QUOTE_MASK
    MAX_FENCE_LEN = _FENCE_LEN_MASK

    @property
    def in_note(self) -> bool:
        """`:::note` の中か（B-3）。"""
        return bool(self.note_kind)

    def encode(self) -> int:
        """`setCurrentBlockState()` に渡す非負の int にする。

        `previousBlockState()` は未設定を -1 で表すため、正当な状態は
        必ず 0 以上でなければならない。
        """
        value = 0
        if self.in_code:
            value |= self._CODE
        if self.in_front_matter:
            value |= self._FRONT_MATTER
        if self.in_table:
            value |= self._TABLE
        if self.fence_char == "~":
            value |= self._TILDE_FENCE
        value |= min(self.quote_depth, self.MAX_QUOTE_DEPTH) << self._QUOTE_SHIFT
        value |= min(self.fence_len, self.MAX_FENCE_LEN) << self._FENCE_LEN_SHIFT
        if not self.after_blank:
            # **既定を 0 のままにするため反転して持つ。** 初期状態（文書の先頭）は
            # 空行の後と同じ扱いで、`encode()` が 0 でなければならない
            value |= self._NOT_AFTER_BLANK
        if self.in_list:
            value |= self._IN_LIST
        if self.in_indented_code:
            value |= self._INDENTED_CODE
        if self.note_kind in _STATE_NOTE_KINDS:
            value |= (_STATE_NOTE_KINDS.index(self.note_kind) + 1) << self._NOTE_SHIFT
        return value

    @classmethod
    def decode(cls, value: int) -> "BlockState":
        """`previousBlockState()` の戻り値から復元する。-1（未設定）は初期状態。"""
        if value < 0:
            return cls()
        in_code = bool(value & cls._CODE)
        fence_char = ""
        if in_code:
            fence_char = "~" if value & cls._TILDE_FENCE else "`"
        return cls(
            in_code=in_code,
            in_front_matter=bool(value & cls._FRONT_MATTER),
            in_table=bool(value & cls._TABLE),
            quote_depth=(value >> cls._QUOTE_SHIFT) & cls._QUOTE_MASK,
            fence_char=fence_char,
            fence_len=(value >> cls._FENCE_LEN_SHIFT) & cls._FENCE_LEN_MASK if in_code else 0,
            after_blank=not (value & cls._NOT_AFTER_BLANK),
            in_list=bool(value & cls._IN_LIST),
            in_indented_code=bool(value & cls._INDENTED_CODE),
            note_kind=cls._decode_note(value),
        )

    @classmethod
    def _decode_note(cls, value: int) -> str:
        index = (value >> cls._NOTE_SHIFT) & cls._NOTE_MASK
        return _STATE_NOTE_KINDS[index - 1] if index else ""


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
    FOOTNOTE = auto()
    """脚注の参照 `[^1]` と定義の頭（B-3 / Qiita 記法）。"""


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
