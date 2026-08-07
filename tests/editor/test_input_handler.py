"""入力補助の判断ロジックのテスト（タスク 3-1, 3-2 / spec §5.5）。

Qt を介さない純関数として検査する。キーイベントとの結線は
`test_editor_input.py` が見る。
"""

import pytest

from hitofude.core.models import BlockInfo, BlockType
from hitofude.editor.input_handler import EnterKind, enter_action, indent_action


def info(kind: BlockType, **kwargs) -> BlockInfo:
    return BlockInfo(line=0, type=kind, **kwargs)


class TestListContinuation:
    """spec §5.5-1: `- item` の行末で Enter → 次行に `- ` を自動挿入。"""

    def test_箇条書きを継承する(self) -> None:
        action = enter_action("- 項目", 4, info(BlockType.BULLET_LIST_ITEM, marker_len=2))
        assert action.kind is EnterKind.CONTINUE
        assert action.text == "- "

    def test_インデントを継承する(self) -> None:
        action = enter_action("    - 項目", 8, info(BlockType.BULLET_LIST_ITEM, marker_len=6))
        assert action.text == "    - "

    def test_別のマーカーも保つ(self) -> None:
        action = enter_action("* 項目", 4, info(BlockType.BULLET_LIST_ITEM, marker_len=2))
        assert action.text == "* "

    def test_行の途中で改行しても継承する(self) -> None:
        action = enter_action("- 項目", 3, info(BlockType.BULLET_LIST_ITEM, marker_len=2))
        assert action.kind is EnterKind.CONTINUE

    def test_マーカーより前では通常の改行(self) -> None:
        action = enter_action("- 項目", 1, info(BlockType.BULLET_LIST_ITEM, marker_len=2))
        assert action.kind is EnterKind.DEFAULT


class TestOrderedList:
    """spec §5.5-3: 番号は +1 する。以降の番号は振り直さない。"""

    @pytest.mark.parametrize(
        ("line", "expected"),
        [("1. 項目", "2. "), ("9. 項目", "10. "), ("12) 項目", "13) "), ("  3. 項目", "  4. ")],
    )
    def test_番号を1つ進める(self, line: str, expected: str) -> None:
        marker_len = len(line) - len(line.split(" ", 1)[-1])
        action = enter_action(
            line, len(line), info(BlockType.ORDERED_LIST_ITEM, marker_len=marker_len)
        )
        assert action.text == expected


class TestTaskList:
    def test_未チェックの項目を継承する(self) -> None:
        action = enter_action(
            "- [ ] やること", 10, info(BlockType.TASK_LIST_ITEM, marker_len=6, checked=False)
        )
        assert action.text == "- [ ] "

    def test_チェック済みでも次はチェックを外す(self) -> None:
        """済んだ項目の次に済んだ項目が来るのはおかしい。"""
        action = enter_action(
            "- [x] 済み", 8, info(BlockType.TASK_LIST_ITEM, marker_len=6, checked=True)
        )
        assert action.text == "- [ ] "


class TestEmptyItemReset:
    """spec §5.5-2: 空リスト項目で Enter → 2 段階で段落に戻す。"""

    def test_インデントされた空項目は1段浅くなる(self) -> None:
        action = enter_action("  - ", 4, info(BlockType.BULLET_LIST_ITEM, marker_len=4))
        assert action.kind is EnterKind.RESET
        assert action.text == "- "

    def test_インデントのない空項目は段落に戻る(self) -> None:
        action = enter_action("- ", 2, info(BlockType.BULLET_LIST_ITEM, marker_len=2))
        assert action.kind is EnterKind.RESET
        assert action.text == ""

    def test_空の番号リストも段落に戻る(self) -> None:
        action = enter_action("1. ", 3, info(BlockType.ORDERED_LIST_ITEM, marker_len=3))
        assert action.kind is EnterKind.RESET
        assert action.text == ""

    def test_空のタスク項目も段落に戻る(self) -> None:
        action = enter_action(
            "- [ ] ", 6, info(BlockType.TASK_LIST_ITEM, marker_len=6, checked=False)
        )
        assert action.kind is EnterKind.RESET
        assert action.text == ""


class TestQuoteContinuation:
    """spec §5.5-6: `> ` を継承。空なら解除。"""

    def test_引用を継承する(self) -> None:
        action = enter_action("> 引用", 4, info(BlockType.BLOCKQUOTE, marker_len=2, quote_depth=1))
        assert action.kind is EnterKind.CONTINUE
        assert action.text == "> "

    def test_入れ子の引用も継承する(self) -> None:
        action = enter_action(
            "> > 二重", 6, info(BlockType.BLOCKQUOTE, marker_len=4, quote_depth=2)
        )
        assert action.text == "> > "

    def test_空の引用は1段浅くなる(self) -> None:
        action = enter_action("> > ", 4, info(BlockType.BLOCKQUOTE, marker_len=4, quote_depth=2))
        assert action.kind is EnterKind.RESET
        assert action.text == "> "

    def test_空の引用が1段なら解除される(self) -> None:
        action = enter_action("> ", 2, info(BlockType.BLOCKQUOTE, marker_len=2, quote_depth=1))
        assert action.kind is EnterKind.RESET
        assert action.text == ""


class TestNoContinuation:
    @pytest.mark.parametrize(
        "kind",
        [
            BlockType.PARAGRAPH,
            BlockType.HEADING,
            BlockType.BLANK,
            BlockType.CODE_FENCE_BODY,
            BlockType.CODE_FENCE_OPEN,
            BlockType.TABLE_ROW,
            BlockType.HORIZONTAL_RULE,
        ],
    )
    def test_継承しないブロック(self, kind: BlockType) -> None:
        level = {"level": 1} if kind is BlockType.HEADING else {}
        action = enter_action("なにか", 3, info(kind, **level))
        assert action.kind is EnterKind.DEFAULT

    def test_情報が無ければ通常の改行(self) -> None:
        """ハイライト前のブロックでも壊れないこと。"""
        assert enter_action("- 項目", 4, None).kind is EnterKind.DEFAULT


class TestIndent:
    """spec §5.5 / §5.4: Tab はリスト行のときだけインデントに使う。"""

    @pytest.mark.parametrize(
        "kind",
        [BlockType.BULLET_LIST_ITEM, BlockType.ORDERED_LIST_ITEM, BlockType.TASK_LIST_ITEM],
    )
    def test_リスト行は字下げできる(self, kind: BlockType) -> None:
        assert indent_action("- 項目", info(kind, marker_len=2), forward=True) == "  - 項目"

    def test_リスト行は字上げできる(self) -> None:
        got = indent_action(
            "    - 項目", info(BlockType.BULLET_LIST_ITEM, marker_len=6), forward=False
        )
        assert got == "  - 項目"

    def test_これ以上戻せないときは何もしない(self) -> None:
        got = indent_action("- 項目", info(BlockType.BULLET_LIST_ITEM, marker_len=2), forward=False)
        assert got is None

    @pytest.mark.parametrize("forward", [True, False])
    def test_リストでない行は対象外(self, forward: bool) -> None:
        """通常のタブ挿入に任せる（spec §5.4）。"""
        assert indent_action("ただの段落", info(BlockType.PARAGRAPH), forward=forward) is None

    def test_情報が無ければ対象外(self) -> None:
        assert indent_action("- 項目", None, forward=True) is None
