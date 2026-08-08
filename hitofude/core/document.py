"""ノート 1 つ分のモデルと、そこから導かれる情報（spec §7.2, §7.3）。

タイトルもタグも**本文から導く**。front matter に書き写して二重管理すると、
本文を編集したときに必ず食い違う。真実は常に本文側（§7.2）。
"""

import hashlib
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hitofude.core import frontmatter, tags
from hitofude.core.block_parser import classify_line
from hitofude.core.inline_scanner import scan
from hitofude.core.models import BlockState, BlockType

PREVIEW_LENGTH = 200

# Crockford Base32（`I` `L` `O` `U` を除いて読み間違いを避ける）
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_TIME_CHARS = 10
_ULID_RANDOM_CHARS = 16

_CODE_TYPES = frozenset(
    {BlockType.CODE_FENCE_OPEN, BlockType.CODE_FENCE_BODY, BlockType.CODE_FENCE_CLOSE}
)

# タイトルにしない行。中身が本文の要約になっていない
_SKIP_FOR_TITLE = frozenset(
    {
        BlockType.BLANK,
        BlockType.CODE_FENCE_OPEN,
        BlockType.CODE_FENCE_BODY,
        BlockType.CODE_FENCE_CLOSE,
        BlockType.HORIZONTAL_RULE,
        BlockType.FRONT_MATTER,
        BlockType.TABLE_DELIMITER,
    }
)


def new_id() -> str:
    """ULID を作る（spec §7.2）。

    ライブラリを足さずに済む程度の分量なので自前で持つ。先頭 10 文字が
    ミリ秒精度の時刻なので、**辞書順が生成順と一致する**。ノートの既定の
    並び順にそのまま使える。
    """
    milliseconds = int(time.time() * 1000)
    randomness = secrets.randbits(_ULID_RANDOM_CHARS * 5)
    return _encode(milliseconds, _ULID_TIME_CHARS) + _encode(randomness, _ULID_RANDOM_CHARS)


def _encode(value: int, length: int) -> str:
    digits = []
    for _ in range(length):
        value, remainder = divmod(value, 32)
        digits.append(_CROCKFORD[remainder])
    return "".join(reversed(digits))


def _body_of(text: str) -> str:
    return frontmatter.split(text).body


def title_of(text: str, fallback: str) -> str:
    """最初の H1 → 無ければ最初の非空行 → 無ければ `fallback`（spec §7.2）。"""
    body = _body_of(text)
    state = BlockState()
    first_line: str | None = None

    for number, line in enumerate(body.split("\n")):
        info, state = classify_line(line, number, state)
        if info.type in _SKIP_FOR_TITLE:
            continue
        stripped = line[info.marker_len :].strip()
        if not stripped:
            continue
        if info.type is BlockType.HEADING and info.level == 1:
            return stripped
        if first_line is None:
            # 行頭マーカーは落とす。`- 項目` のままだとノート一覧が読みにくい
            first_line = stripped

    return first_line or fallback


def preview_of(text: str, limit: int = PREVIEW_LENGTH) -> str:
    """ノート一覧に出す本文の冒頭（spec §7.3）。

    front matter と H1 を除いた残りを、改行を空白に潰して切り出す。
    """
    body = _body_of(text)
    state = BlockState()
    parts: list[str] = []
    skipped_title = False

    for number, line in enumerate(body.split("\n")):
        info, state = classify_line(line, number, state)
        if not skipped_title and info.type is BlockType.HEADING and info.level == 1:
            skipped_title = True
            continue
        stripped = line.strip()
        if stripped:
            parts.append(stripped)
        if sum(len(part) + 1 for part in parts) > limit:
            break

    return " ".join(parts)[:limit]


@dataclass(frozen=True, slots=True)
class Note:
    """ディスク上の `.md` 1 つ。読み込んだ時点のスナップショット。"""

    path: Path
    text: str
    mtime_ns: int
    size_bytes: int
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_text(cls, path: Path, text: str, *, mtime_ns: int, size_bytes: int) -> "Note":
        return cls(
            path=path,
            text=text,
            mtime_ns=mtime_ns,
            size_bytes=size_bytes,
            meta=frontmatter.split(text).meta,
        )

    @classmethod
    def read(cls, path: Path) -> "Note":
        stat = path.stat()
        return cls.from_text(
            path,
            path.read_text(encoding="utf-8"),
            mtime_ns=stat.st_mtime_ns,
            size_bytes=stat.st_size,
        )

    @property
    def id(self) -> str | None:
        value = self.meta.get("id")
        return str(value) if value is not None else None

    @property
    def pinned(self) -> bool:
        return bool(self.meta.get("pinned", False))

    @property
    def title(self) -> str:
        return title_of(self.text, self.path.stem)

    @property
    def preview(self) -> str:
        return preview_of(self.text)

    @property
    def tags(self) -> list[str]:
        return tags.extract(self.text)

    @property
    def digest(self) -> str:
        """内容のハッシュ。保存直前の競合検知に使う（spec §7.5）。"""
        return hashlib.blake2b(self.text.encode("utf-8"), digest_size=16).hexdigest()

    def is_stale(self) -> bool:
        """読み込んだ後にディスク側が変わったか（spec §7.5）。"""
        try:
            return self.path.stat().st_mtime_ns != self.mtime_ns
        except OSError:
            return True

    def relative_to(self, root: Path) -> str:
        return os.fspath(self.path.relative_to(root))


def plain_text(text: str) -> str:
    """マーカーを外した本文。

    索引（§7.3）と `Cmd+Shift+C` のプレーンテキストコピー（§5.4）で共有する。
    どちらも「装飾は文章の一部ではない」という同じ判断に立つ。

    **ソース文字列そのものは一切変えない（R1）。** ここで作るのは写しであって、
    保存内容ではない。
    """
    state = BlockState()
    lines: list[str] = []

    for number, line in enumerate(frontmatter.split(text).body.split("\n")):
        info, state = classify_line(line, number, state)
        if info.type in _CODE_TYPES:
            # コードは記号ごと検索できたほうがよい
            lines.append(line)
            continue

        body = line[info.marker_len :]
        drop = bytearray(len(body))
        for span in scan(body):
            drop[span.open_start : span.open_end] = b"\x01" * span.open_len
            drop[span.close_start : span.close_end] = b"\x01" * span.close_len
        lines.append("".join(char for index, char in enumerate(body) if not drop[index]))

    return "\n".join(lines)


def searchable_text(text: str) -> str:
    """検索インデックスに入れる本文（spec §7.3）。

    ソースをそのまま索引すると `**予算**について` が 1 つの文字列として入り、
    `予算について` で引けなくなる。
    """
    return plain_text(text)
