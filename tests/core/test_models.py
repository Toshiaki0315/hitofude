"""データモデルのテスト（タスク 1-1 / spec §6.2）。

オフセットは**すべて `[start, end)` の半開区間**という約束を、型の側で守らせる。
ここが崩れるとハイライタの `setFormat(start, length)` が静かにずれる。
"""

import dataclasses

import pytest

from hitofude.core.models import BlockInfo, BlockType, InlineSpan, SpanType


class TestBlockInfo:
    def test_行番号と種別だけで作れる(self) -> None:
        block = BlockInfo(line=0, type=BlockType.PARAGRAPH)
        assert block.level == 0
        assert block.marker_len == 0
        assert block.checked is None
        assert block.lang is None
        assert block.quote_depth == 0

    def test_イミュータブルである(self) -> None:
        block = BlockInfo(line=0, type=BlockType.PARAGRAPH)
        with pytest.raises(dataclasses.FrozenInstanceError):
            block.line = 1  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("line", -1),
            ("level", -1),
            ("marker_len", -1),
            ("quote_depth", -1),
        ],
    )
    def test_負の値を拒否する(self, field: str, value: int) -> None:
        kwargs = {"line": 0, "type": BlockType.PARAGRAPH, field: value}
        with pytest.raises(ValueError, match=field):
            BlockInfo(**kwargs)  # type: ignore[arg-type]

    def test_見出しはレベルとマーカー長を持つ(self) -> None:
        # '## ' は marker_len=3（記号 2 文字 + 空白 1 文字）
        block = BlockInfo(line=3, type=BlockType.HEADING, level=2, marker_len=3)
        assert block.level == 2
        assert block.marker_len == 3

    @pytest.mark.parametrize("level", [0, 7])
    def test_見出しのレベルは1から6まで(self, level: int) -> None:
        with pytest.raises(ValueError, match="level"):
            BlockInfo(line=0, type=BlockType.HEADING, level=level)

    @pytest.mark.parametrize("checked", [True, False])
    def test_タスクリストはチェック状態を持つ(self, checked: bool) -> None:
        block = BlockInfo(line=0, type=BlockType.TASK_LIST_ITEM, marker_len=6, checked=checked)
        assert block.checked is checked

    def test_コードフェンスは言語を持てる(self) -> None:
        block = BlockInfo(line=0, type=BlockType.CODE_FENCE_OPEN, lang="python")
        assert block.lang == "python"


class TestInlineSpan:
    def _strong(self) -> InlineSpan:
        # "a **bold** b" の '**bold**' 部分
        return InlineSpan(
            type=SpanType.STRONG, open_start=2, open_end=4, close_start=8, close_end=10
        )

    def test_イミュータブルである(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            self._strong().open_start = 0  # type: ignore[misc]

    def test_内容の範囲はマーカーの内側(self) -> None:
        span = self._strong()
        assert (span.content_start, span.content_end) == (4, 8)

    def test_全体の範囲はマーカーを含む(self) -> None:
        span = self._strong()
        assert (span.start, span.end) == (2, 10)

    def test_マーカーの長さを取れる(self) -> None:
        span = self._strong()
        assert span.open_len == 2
        assert span.close_len == 2

    @pytest.mark.parametrize(
        "offsets",
        [
            (4, 2, 8, 10),  # open_end < open_start
            (2, 9, 8, 10),  # open_end > close_start
            (2, 4, 10, 8),  # close_end < close_start
            (-1, 4, 8, 10),  # 負のオフセット
        ],
    )
    def test_順序が壊れた区間を拒否する(self, offsets: tuple[int, int, int, int]) -> None:
        open_start, open_end, close_start, close_end = offsets
        with pytest.raises(ValueError):
            InlineSpan(
                type=SpanType.STRONG,
                open_start=open_start,
                open_end=open_end,
                close_start=close_start,
                close_end=close_end,
            )

    def test_マーカーを持たない範囲も表現できる(self) -> None:
        """タグ `#work` は `#` ごと表示するのでマーカー長が 0（spec §6.4）。"""
        span = InlineSpan(
            type=SpanType.TAG, open_start=0, open_end=0, close_start=5, close_end=5, payload="work"
        )
        assert span.open_len == 0
        assert span.close_len == 0
        assert (span.content_start, span.content_end) == (0, 5)

    @pytest.mark.parametrize(
        ("position", "expected"),
        [
            (1, False),  # 直前
            (2, True),  # 開きマーカーの先頭＝閉区間の左端
            (5, True),  # 内容の中
            (10, True),  # 閉じマーカーの直後＝閉区間の右端
            (11, False),  # 通り過ぎた
        ],
    )
    def test_containsはリビール用の閉区間で判定する(self, position: int, expected: bool) -> None:
        """spec §6.4: キャレットが `[open_start, close_end]` の**閉区間**内にあれば現す。

        右端を含むので、マーカー直後にカーソルを置いた状態で編集を続けられる。
        """
        assert self._strong().contains(position) is expected

    def test_payloadは既定で空文字列(self) -> None:
        assert self._strong().payload == ""
