"""ブロックパーサのテスト（タスク 1-9 / spec §3.4, §6.2）。

`parse()` は**ソース 1 行につき BlockInfo を 1 個**返す。
`QTextBlock` と 1:1 で対応させるという設計（§6.2）を型と個数で担保する。
"""

import pytest

from hitofude.core.block_parser import parse
from hitofude.core.models import BlockType


def types(text: str) -> list[BlockType]:
    return [block.type for block in parse(text)]


class TestShape:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "a\n",
            "a\nb\nc\n",
            "# 見出し\n\n本文\n\n- リスト\n",
        ],
    )
    def test_行数と同じ個数を返す(self, text: str) -> None:
        assert len(parse(text)) == len(text.replace("\r\n", "\n").split("\n"))

    def test_行番号は0始まりで連番(self) -> None:
        blocks = parse("a\nb\nc\n")
        assert [b.line for b in blocks] == [0, 1, 2, 3]

    def test_CRLFを正規化して扱う(self) -> None:
        assert types("# 見出し\r\n\r\n本文\r\n") == [
            BlockType.HEADING,
            BlockType.BLANK,
            BlockType.PARAGRAPH,
            BlockType.BLANK,
        ]


class TestHeading:
    @pytest.mark.parametrize(
        ("text", "level", "marker_len"),
        [
            ("# 見出し", 1, 2),
            ("## 見出し", 2, 3),
            ("###### 見出し", 6, 7),
        ],
    )
    def test_レベルとマーカー長(self, text: str, level: int, marker_len: int) -> None:
        block = parse(text)[0]
        assert block.type is BlockType.HEADING
        assert block.level == level
        assert block.marker_len == marker_len

    def test_7個のシャープは見出しではない(self) -> None:
        assert parse("####### x")[0].type is BlockType.PARAGRAPH


class TestList:
    @pytest.mark.parametrize("marker", ["-", "*", "+"])
    def test_箇条書き(self, marker: str) -> None:
        block = parse(f"{marker} 項目")[0]
        assert block.type is BlockType.BULLET_LIST_ITEM
        assert block.level == 1
        assert block.marker_len == 2

    def test_番号リスト(self) -> None:
        block = parse("1. 項目")[0]
        assert block.type is BlockType.ORDERED_LIST_ITEM
        assert block.marker_len == 3

    def test_入れ子の深さ(self) -> None:
        blocks = parse("- 親\n    - 子\n        - 孫\n")
        assert [b.level for b in blocks[:3]] == [1, 2, 3]

    @pytest.mark.parametrize(
        ("text", "checked"),
        [("- [ ] やること", False), ("- [x] 済み", True), ("- [X] 済み", True)],
    )
    def test_タスクリスト(self, text: str, checked: bool) -> None:
        block = parse(text)[0]
        assert block.type is BlockType.TASK_LIST_ITEM
        assert block.checked is checked
        assert block.marker_len == 6

    def test_チェックボックスでない箇条書きはcheckedがNone(self) -> None:
        assert parse("- 項目")[0].checked is None


class TestCodeFence:
    def test_開始と中身と終了を区別する(self) -> None:
        assert types("```python\nx = 1\n```\n") == [
            BlockType.CODE_FENCE_OPEN,
            BlockType.CODE_FENCE_BODY,
            BlockType.CODE_FENCE_CLOSE,
            BlockType.BLANK,
        ]

    def test_言語を取り出す(self) -> None:
        assert parse("```python\nx = 1\n```\n")[0].lang == "python"

    def test_言語なしのフェンス(self) -> None:
        assert parse("```\nx\n```\n")[0].lang is None

    def test_フェンスの中は装飾対象にならない(self) -> None:
        """`# コメント` が見出しに、`- x` がリストに化けないこと。"""
        blocks = parse("```sh\n# コメント\n- x\n```\n")
        assert blocks[1].type is BlockType.CODE_FENCE_BODY
        assert blocks[2].type is BlockType.CODE_FENCE_BODY

    def test_閉じていないフェンスでも壊れない(self) -> None:
        assert types("```python\nx = 1\n") == [
            BlockType.CODE_FENCE_OPEN,
            BlockType.CODE_FENCE_BODY,
            BlockType.BLANK,
        ]

    def test_チルダのフェンス(self) -> None:
        assert parse("~~~js\nx\n~~~\n")[0].type is BlockType.CODE_FENCE_OPEN


class TestBlockquote:
    def test_引用の深さ(self) -> None:
        block = parse("> 引用")[0]
        assert block.type is BlockType.BLOCKQUOTE
        assert block.quote_depth == 1
        assert block.marker_len == 2

    def test_入れ子の引用(self) -> None:
        block = parse("> > 二重")[0]
        assert block.quote_depth == 2
        assert block.marker_len == 4

    def test_引用の中のリストはリストとして扱う(self) -> None:
        """種別は最も内側の構造、引用の深さは別フィールドで持つ。"""
        block = parse("> - 項目")[0]
        assert block.type is BlockType.BULLET_LIST_ITEM
        assert block.quote_depth == 1


class TestOthers:
    @pytest.mark.parametrize("text", ["---", "***", "___", "- - -"])
    def test_水平線(self, text: str) -> None:
        assert parse(f"段落\n\n{text}\n")[2].type is BlockType.HORIZONTAL_RULE

    def test_空行(self) -> None:
        assert parse("a\n\nb")[1].type is BlockType.BLANK

    def test_空白だけの行も空行(self) -> None:
        assert parse("a\n   \nb")[1].type is BlockType.BLANK

    def test_段落(self) -> None:
        assert parse("ただの文章")[0].type is BlockType.PARAGRAPH


class TestTable:
    TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"

    def test_見出し行と区切り行と本体行(self) -> None:
        assert types(self.TABLE) == [
            BlockType.TABLE_ROW,
            BlockType.TABLE_DELIMITER,
            BlockType.TABLE_ROW,
            BlockType.BLANK,
        ]

    def test_表の直後の段落は表ではない(self) -> None:
        assert parse(self.TABLE + "\n本文\n")[4].type is BlockType.PARAGRAPH


class TestFrontMatter:
    TEXT = "---\nid: 1\npinned: false\n---\n\n# 見出し\n"

    def test_front_matterの行を区別する(self) -> None:
        assert types(self.TEXT)[:4] == [BlockType.FRONT_MATTER] * 4

    def test_front_matterの後ろは通常どおり解析する(self) -> None:
        blocks = parse(self.TEXT)
        assert blocks[5].type is BlockType.HEADING
        assert blocks[5].line == 5

    def test_front_matterが無ければ水平線として扱う(self) -> None:
        blocks = parse("本文\n\n---\n\n続き\n")
        assert BlockType.FRONT_MATTER not in [b.type for b in blocks]
