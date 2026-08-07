"""テキスト変換コマンドのテスト（タスク 3-3, 3-5, 3-6 / spec §5.4, §5.5）。

トグルは「外す」側が本体。実装漏れると押し間違いを戻せなくなる。
"""

import pytest

from hitofude.core.models import BlockInfo, BlockType
from hitofude.editor.commands import (
    insert_link,
    is_url,
    shift_heading,
    toggle_checkbox,
    toggle_wrap,
)


def apply(text: str, replacement) -> str:
    return text[: replacement.start] + replacement.text + text[replacement.end :]


class TestToggleWrap:
    def test_選択範囲を囲む(self) -> None:
        text = "これは強調です"
        got = toggle_wrap(text, 3, 5, "**")
        assert apply(text, got) == "これは**強調**です"

    def test_囲んだあとも同じ文字が選ばれている(self) -> None:
        got = toggle_wrap("これは強調です", 3, 5, "**")
        assert (got.select_start, got.select_end) == (5, 7)

    def test_外側にマーカーがあれば外す(self) -> None:
        """`**強調**` の `強調` だけを選んだ状態。"""
        text = "これは**強調**です"
        got = toggle_wrap(text, 5, 7, "**")
        assert apply(text, got) == "これは強調です"

    def test_内側にマーカーごと選んでも外す(self) -> None:
        """`**強調**` ごと選んだ状態。"""
        text = "これは**強調**です"
        got = toggle_wrap(text, 3, 9, "**")
        assert apply(text, got) == "これは強調です"

    def test_外したあとも中身が選ばれている(self) -> None:
        got = toggle_wrap("これは**強調**です", 5, 7, "**")
        assert (got.select_start, got.select_end) == (3, 5)

    @pytest.mark.parametrize("marker", ["**", "*", "`", "~~", "::"])
    def test_囲んで外すと元に戻る(self, marker: str) -> None:
        text = "これは強調です"
        wrapped = apply(text, toggle_wrap(text, 3, 5, marker))
        got = toggle_wrap(wrapped, 3 + len(marker), 5 + len(marker), marker)
        assert apply(wrapped, got) == text

    def test_選択が無ければ記号だけ置いて間にキャレット(self) -> None:
        text = "あい"
        got = toggle_wrap(text, 1, 1, "**")
        assert apply(text, got) == "あ****い"
        assert got.select_start == got.select_end == 3


class TestInsertLink:
    def test_選択をリンクにする(self) -> None:
        text = "Qt のドキュメント"
        got = insert_link(text, 0, 2)
        assert apply(text, got) == "[Qt]() のドキュメント"

    def test_キャレットは丸括弧の中(self) -> None:
        got = insert_link("Qt", 0, 2)
        assert got.select_start == 5  # '[Qt](' の直後

    def test_URLが分かっていれば埋める(self) -> None:
        text = "Qt"
        got = insert_link(text, 0, 2, "https://qt.io")
        assert apply(text, got) == "[Qt](https://qt.io)"

    def test_URLがあるときキャレットは末尾(self) -> None:
        got = insert_link("Qt", 0, 2, "https://qt.io")
        assert got.select_start == len("[Qt](https://qt.io)")

    def test_選択が無くても空のリンクを作れる(self) -> None:
        assert apply("", insert_link("", 0, 0)) == "[]()"


class TestIsUrl:
    @pytest.mark.parametrize(
        "text", ["https://example.com", "http://x.jp/a?b=c", " https://example.com \n"]
    )
    def test_URLとみなす(self, text: str) -> None:
        assert is_url(text) is True

    @pytest.mark.parametrize(
        "text", ["ただの文字列", "https://example.com と続く文", "", "example.com"]
    )
    def test_URLとみなさない(self, text: str) -> None:
        assert is_url(text) is False


class TestShiftHeading:
    @pytest.mark.parametrize(
        ("line", "delta", "expected"),
        [
            ("段落", 1, "# 段落"),
            ("# 見出し", 1, "## 見出し"),
            ("## 見出し", -1, "# 見出し"),
            ("# 見出し", -1, "見出し"),
            ("##### 見出し", 1, "###### 見出し"),
        ],
    )
    def test_レベルを増減する(self, line: str, delta: int, expected: str) -> None:
        assert shift_heading(line, delta) == expected

    @pytest.mark.parametrize(
        ("line", "delta"), [("###### 見出し", 1), ("段落", -1), ("# 見出し", 0)]
    )
    def test_これ以上動かせないときはNone(self, line: str, delta: int) -> None:
        assert shift_heading(line, delta) is None


class TestToggleCheckbox:
    def info(self, kind: BlockType, **kwargs) -> BlockInfo:
        return BlockInfo(line=0, type=kind, **kwargs)

    def test_未チェックをチェックにする(self) -> None:
        got = toggle_checkbox("- [ ] やること", self.info(BlockType.TASK_LIST_ITEM, checked=False))
        assert got == "- [x] やること"

    def test_チェックを外す(self) -> None:
        got = toggle_checkbox("- [x] 済み", self.info(BlockType.TASK_LIST_ITEM, checked=True))
        assert got == "- [ ] 済み"

    def test_インデントを保つ(self) -> None:
        got = toggle_checkbox("  - [ ] 項目", self.info(BlockType.TASK_LIST_ITEM, checked=False))
        assert got == "  - [x] 項目"

    def test_リスト項目にチェックボックスを付ける(self) -> None:
        got = toggle_checkbox("- 項目", self.info(BlockType.BULLET_LIST_ITEM))
        assert got == "- [ ] 項目"

    def test_番号リストにも付けられる(self) -> None:
        got = toggle_checkbox("1. 項目", self.info(BlockType.ORDERED_LIST_ITEM))
        assert got == "1. [ ] 項目"

    def test_段落はリスト項目にしてから付ける(self) -> None:
        assert toggle_checkbox("ただの段落", self.info(BlockType.PARAGRAPH)) == "- [ ] ただの段落"

    @pytest.mark.parametrize("kind", [BlockType.HEADING, BlockType.CODE_FENCE_BODY])
    def test_見出しとコードは対象外(self, kind: BlockType) -> None:
        level = {"level": 1} if kind is BlockType.HEADING else {}
        assert toggle_checkbox("なにか", self.info(kind, **level)) is None

    def test_情報が無くても段落として扱う(self) -> None:
        assert toggle_checkbox("なにか", None) == "- [ ] なにか"
