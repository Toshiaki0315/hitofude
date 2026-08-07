"""ブロック状態のビットフラグと行単位分類のテスト（タスク 2-1, 2-2 / spec §6.3）。

`QSyntaxHighlighter` は 1 行しか見えず、前の行から引き継げるのは **int 1 個**だけ。
そこにコードフェンス / front matter / 表 / 引用の深さを詰め込む。
"""

import pytest

from hitofude.core.block_parser import classify_line
from hitofude.core.models import BlockState, BlockType


class TestBlockStateEncoding:
    def test_初期状態は0(self) -> None:
        assert BlockState().encode() == 0

    def test_未設定を表す負の値は初期状態として復元する(self) -> None:
        """`QSyntaxHighlighter.previousBlockState()` は先頭行で -1 を返す。"""
        assert BlockState.decode(-1) == BlockState()

    @pytest.mark.parametrize(
        "state",
        [
            BlockState(),
            BlockState(in_code=True, fence_char="`", fence_len=3),
            BlockState(in_code=True, fence_char="~", fence_len=5),
            BlockState(in_front_matter=True),
            BlockState(in_table=True),
            BlockState(quote_depth=1),
            BlockState(quote_depth=15),
            BlockState(in_code=True, fence_char="`", fence_len=4, quote_depth=2, in_table=True),
        ],
    )
    def test_エンコードとデコードで往復する(self, state: BlockState) -> None:
        assert BlockState.decode(state.encode()) == state

    def test_エンコード結果は非負(self) -> None:
        """-1 を「未設定」に使うため、正当な状態が負になってはいけない。"""
        assert BlockState(in_code=True, fence_char="~", fence_len=31, quote_depth=15).encode() >= 0

    def test_引用の深さは上限で頭打ちになる(self) -> None:
        assert BlockState(quote_depth=99).encode() == BlockState(quote_depth=15).encode()


class TestClassifyPlain:
    def test_段落(self) -> None:
        block, state = classify_line("ただの文章", 3, BlockState())
        assert block.type is BlockType.PARAGRAPH
        assert block.line == 3
        assert state == BlockState()

    @pytest.mark.parametrize("text", ["", "   ", "\t"])
    def test_空行(self, text: str) -> None:
        block, _ = classify_line(text, 0, BlockState())
        assert block.type is BlockType.BLANK

    @pytest.mark.parametrize(
        ("text", "level", "marker_len"),
        [("# a", 1, 2), ("### a", 3, 4), ("###### a", 6, 7)],
    )
    def test_見出し(self, text: str, level: int, marker_len: int) -> None:
        block, _ = classify_line(text, 0, BlockState())
        assert block.type is BlockType.HEADING
        assert (block.level, block.marker_len) == (level, marker_len)

    def test_7個のシャープは見出しではない(self) -> None:
        block, _ = classify_line("####### a", 0, BlockState())
        assert block.type is BlockType.PARAGRAPH

    def test_シャープだけの行は見出し(self) -> None:
        block, _ = classify_line("#", 0, BlockState())
        assert block.type is BlockType.HEADING

    @pytest.mark.parametrize("text", ["---", "***", "___", "- - -", "  ---"])
    def test_水平線(self, text: str) -> None:
        block, _ = classify_line(text, 5, BlockState())
        assert block.type is BlockType.HORIZONTAL_RULE

    @pytest.mark.parametrize(
        ("text", "kind", "marker_len"),
        [
            ("- 項目", BlockType.BULLET_LIST_ITEM, 2),
            ("* 項目", BlockType.BULLET_LIST_ITEM, 2),
            ("1. 項目", BlockType.ORDERED_LIST_ITEM, 3),
            ("12) 項目", BlockType.ORDERED_LIST_ITEM, 4),
        ],
    )
    def test_リスト(self, text: str, kind: BlockType, marker_len: int) -> None:
        block, _ = classify_line(text, 0, BlockState())
        assert block.type is kind
        assert block.marker_len == marker_len

    @pytest.mark.parametrize(("text", "checked"), [("- [ ] a", False), ("- [x] a", True)])
    def test_タスクリスト(self, text: str, checked: bool) -> None:
        block, _ = classify_line(text, 0, BlockState())
        assert block.type is BlockType.TASK_LIST_ITEM
        assert block.checked is checked
        assert block.marker_len == 6

    def test_リストの深さはインデント2文字単位の目安(self) -> None:
        """行単位では正確な入れ子が決まらない。確定値は block_parser が出す（§6.6）。"""
        assert classify_line("- a", 0, BlockState())[0].level == 1
        assert classify_line("  - a", 0, BlockState())[0].level == 2
        assert classify_line("    - a", 0, BlockState())[0].level == 3


class TestClassifyQuote:
    def test_引用の深さとマーカー長(self) -> None:
        block, state = classify_line("> 引用", 0, BlockState())
        assert block.type is BlockType.BLOCKQUOTE
        assert block.quote_depth == 1
        assert block.marker_len == 2
        assert state.quote_depth == 1

    def test_入れ子の引用(self) -> None:
        block, _ = classify_line("> > 二重", 0, BlockState())
        assert block.quote_depth == 2
        assert block.marker_len == 4

    def test_引用の中のリストはリストとして扱う(self) -> None:
        block, _ = classify_line("> - 項目", 0, BlockState())
        assert block.type is BlockType.BULLET_LIST_ITEM
        assert block.quote_depth == 1

    def test_引用の中の見出し(self) -> None:
        block, _ = classify_line("> # 見出し", 0, BlockState())
        assert block.type is BlockType.HEADING
        assert block.level == 1
        assert block.quote_depth == 1

    def test_引用が終わると状態が戻る(self) -> None:
        _, state = classify_line("通常の行", 1, BlockState(quote_depth=2))
        assert state.quote_depth == 0


class TestClassifyCodeFence:
    def test_開始で状態に入る(self) -> None:
        block, state = classify_line("```python", 0, BlockState())
        assert block.type is BlockType.CODE_FENCE_OPEN
        assert block.lang == "python"
        assert state.in_code is True
        assert (state.fence_char, state.fence_len) == ("`", 3)

    def test_中身は状態を保つ(self) -> None:
        inside = BlockState(in_code=True, fence_char="`", fence_len=3)
        block, state = classify_line("# これは見出しではない", 1, inside)
        assert block.type is BlockType.CODE_FENCE_BODY
        assert state == inside

    def test_同じ記号で閉じると状態を抜ける(self) -> None:
        inside = BlockState(in_code=True, fence_char="`", fence_len=3)
        block, state = classify_line("```", 2, inside)
        assert block.type is BlockType.CODE_FENCE_CLOSE
        assert state.in_code is False

    def test_より長いフェンスでも閉じられる(self) -> None:
        inside = BlockState(in_code=True, fence_char="`", fence_len=3)
        _, state = classify_line("`````", 2, inside)
        assert state.in_code is False

    def test_短いフェンスでは閉じない(self) -> None:
        inside = BlockState(in_code=True, fence_char="`", fence_len=5)
        block, state = classify_line("```", 2, inside)
        assert block.type is BlockType.CODE_FENCE_BODY
        assert state.in_code is True

    def test_違う記号では閉じない(self) -> None:
        inside = BlockState(in_code=True, fence_char="`", fence_len=3)
        block, state = classify_line("~~~", 2, inside)
        assert block.type is BlockType.CODE_FENCE_BODY
        assert state.in_code is True

    def test_チルダのフェンス(self) -> None:
        _, state = classify_line("~~~js", 0, BlockState())
        assert (state.in_code, state.fence_char) == (True, "~")

    def test_言語指定なし(self) -> None:
        block, _ = classify_line("```", 0, BlockState())
        assert block.lang is None


class TestClassifyFrontMatter:
    def test_1行目の区切りで状態に入る(self) -> None:
        block, state = classify_line("---", 0, BlockState())
        assert block.type is BlockType.FRONT_MATTER
        assert state.in_front_matter is True

    def test_2行目以降の区切りは水平線(self) -> None:
        block, state = classify_line("---", 1, BlockState())
        assert block.type is BlockType.HORIZONTAL_RULE
        assert state.in_front_matter is False

    def test_中身は状態を保つ(self) -> None:
        block, state = classify_line("id: 1", 1, BlockState(in_front_matter=True))
        assert block.type is BlockType.FRONT_MATTER
        assert state.in_front_matter is True

    def test_閉じ区切りで状態を抜ける(self) -> None:
        block, state = classify_line("---", 3, BlockState(in_front_matter=True))
        assert block.type is BlockType.FRONT_MATTER
        assert state.in_front_matter is False


class TestClassifyTable:
    def test_区切り行で状態に入る(self) -> None:
        block, state = classify_line("|---|---|", 1, BlockState())
        assert block.type is BlockType.TABLE_DELIMITER
        assert state.in_table is True

    def test_表の中の行(self) -> None:
        block, _ = classify_line("| 1 | 2 |", 2, BlockState(in_table=True))
        assert block.type is BlockType.TABLE_ROW

    def test_空行で表を抜ける(self) -> None:
        block, state = classify_line("", 3, BlockState(in_table=True))
        assert block.type is BlockType.BLANK
        assert state.in_table is False

    def test_揃え指定つきの区切り行(self) -> None:
        block, _ = classify_line("|:--|--:|:-:|", 1, BlockState())
        assert block.type is BlockType.TABLE_DELIMITER

    def test_水平線を表の区切りと誤認しない(self) -> None:
        block, _ = classify_line("---", 5, BlockState())
        assert block.type is BlockType.HORIZONTAL_RULE


class TestConsistencyWithBlockParser:
    """行単位分類と文書全体の解析が、単純な文書では一致すること。"""

    @pytest.mark.parametrize(
        "text",
        [
            "# 見出し\n\n本文\n",
            "```python\nx = 1\n```\n\n本文\n",
            "---\nid: 1\n---\n\n# 見出し\n",
            "> 引用\n\n本文\n",
            "- a\n- b\n\n本文\n",
        ],
    )
    def test_ブロック種別が一致する(self, text: str) -> None:
        from hitofude.core.block_parser import parse

        expected = [block.type for block in parse(text)]
        state = BlockState()
        actual = []
        for line, content in enumerate(text.split("\n")):
            block, state = classify_line(content, line, state)
            actual.append(block.type)
        assert actual == expected
