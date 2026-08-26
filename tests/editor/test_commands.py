"""テキスト変換コマンドのテスト（タスク 3-3, 3-5, 3-6 / spec §5.4, §5.5）。

トグルは「外す」側が本体。実装漏れると押し間違いを戻せなくなる。
"""

import pytest

from hitofude.core.models import BlockInfo, BlockType
from hitofude.editor.commands import (
    cycle_heading,
    insert_link,
    insert_table,
    is_url,
    shift_heading,
    toggle_bullet,
    toggle_checkbox,
    toggle_ordered,
    toggle_quote,
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


class TestToggleBullet:
    """箇条書きのトグル（B-1 のツールバー）。

    ツールバーは**複数行を選んで押す**のが普通なので、1 行だけの
    `toggle_checkbox` とは別に、行の並びを受け取る形にする。
    """

    def test_付ける(self) -> None:
        assert toggle_bullet(["りんご", "みかん"]) == ["- りんご", "- みかん"]

    def test_全部付いていれば外す(self) -> None:
        assert toggle_bullet(["- りんご", "- みかん"]) == ["りんご", "みかん"]

    def test_一部だけ付いていれば揃える(self) -> None:
        """半端な状態で押したら、外すのではなく揃うほうが期待に近い。"""
        assert toggle_bullet(["- りんご", "みかん"]) == ["- りんご", "- みかん"]

    def test_字下げは保つ(self) -> None:
        assert toggle_bullet(["  りんご"]) == ["  - りんご"]

    def test_番号付きから乗り換える(self) -> None:
        """入れ子にせず置き換える。`- 1. りんご` は誰も望んでいない。"""
        assert toggle_bullet(["1. りんご", "2. みかん"]) == ["- りんご", "- みかん"]

    def test_空行は触らない(self) -> None:
        """`- ` だけの行が増えても書き手の役に立たない。"""
        assert toggle_bullet(["りんご", "", "みかん"]) == ["- りんご", "", "- みかん"]

    def test_空行しか無ければ付ける(self) -> None:
        """何も書いていない行で押したのは「これから書く」という意思。"""
        assert toggle_bullet([""]) == ["- "]

    @pytest.mark.parametrize("marker", ["- ", "* ", "+ "])
    def test_どの記号でも外せる(self, marker: str) -> None:
        assert toggle_bullet([f"{marker}りんご"]) == ["りんご"]

    def test_チェックボックスは保つ(self) -> None:
        """`- [ ] 買う` から `- ` だけ外すと `[ ] 買う` が残って壊れる。"""
        assert toggle_bullet(["- [ ] 買う"]) == ["[ ] 買う"]


class TestToggleOrdered:
    def test_付ける(self) -> None:
        assert toggle_ordered(["りんご", "みかん"]) == ["1. りんご", "2. みかん"]

    def test_全部付いていれば外す(self) -> None:
        assert toggle_ordered(["1. りんご", "2. みかん"]) == ["りんご", "みかん"]

    def test_番号を振り直す(self) -> None:
        assert toggle_ordered(["5. りんご", "9. みかん"]) == ["りんご", "みかん"]

    def test_箇条書きから乗り換える(self) -> None:
        assert toggle_ordered(["- りんご", "- みかん"]) == ["1. りんご", "2. みかん"]

    def test_空行を飛ばしても番号は続く(self) -> None:
        assert toggle_ordered(["りんご", "", "みかん"]) == ["1. りんご", "", "2. みかん"]

    def test_字下げは保つ(self) -> None:
        assert toggle_ordered(["  りんご"]) == ["  1. りんご"]

    def test_閉じ括弧の記法も外せる(self) -> None:
        assert toggle_ordered(["1) りんご"]) == ["りんご"]


class TestToggleQuote:
    def test_付ける(self) -> None:
        assert toggle_quote(["引用"]) == ["> 引用"]

    def test_外す(self) -> None:
        assert toggle_quote(["> 引用"]) == ["引用"]

    def test_入れ子は一段だけ外す(self) -> None:
        assert toggle_quote(["> > 引用"]) == ["> 引用"]

    def test_空行にも付ける(self) -> None:
        """引用の中の空行は引用の一部。抜けると引用が途切れて別々の引用になる。
        リストが空行を飛ばすのとは逆だが、Markdown の仕様がこうなっている。"""
        assert toggle_quote(["一段目", "", "二段目"]) == ["> 一段目", "> ", "> 二段目"]

    def test_一部だけ付いていれば揃える(self) -> None:
        """既に引用の行は一段のまま。押すたびに深くならない。"""
        assert toggle_quote(["> 引用", "地の文"]) == ["> 引用", "> 地の文"]

    def test_全部引用なら深くせず外す(self) -> None:
        """**このボタンでは入れ子を作れない。** 3 つのボタンで手応えを
        揃えるほうを採った（深くしたいときは `>` を打てばよい）。"""
        assert toggle_quote(["> 一段目", "> 二段目"]) == ["一段目", "二段目"]

    def test_空行は付いているかの判定に入れない(self) -> None:
        """空行のせいで「付いていない」と見なされると、外したいのに深くなる。"""
        assert toggle_quote(["> 一段目", "", "> 二段目"]) == ["一段目", "", "二段目"]

    def test_記号だけの行も外せる(self) -> None:
        assert toggle_quote([">"]) == [""]


class TestLineTogglesShareRules:
    """3 つとも同じ約束で動くこと。ツールバーのボタンとして並ぶので、
    押したときの手応えが違うと使う側が覚えられない。"""

    @pytest.mark.parametrize("toggle", [toggle_bullet, toggle_ordered, toggle_quote])
    def test_二度押すと元に戻る(self, toggle) -> None:
        lines = ["りんご", "みかん"]
        assert toggle(toggle(lines)) == lines

    @pytest.mark.parametrize("toggle", [toggle_bullet, toggle_ordered, toggle_quote])
    def test_元の並びを壊さない(self, toggle) -> None:
        lines = ["りんご", "みかん"]
        toggle(lines)
        assert lines == ["りんご", "みかん"]

    @pytest.mark.parametrize("toggle", [toggle_bullet, toggle_ordered, toggle_quote])
    def test_行数は変わらない(self, toggle) -> None:
        assert len(toggle(["あ", "", "い", "う"])) == 4


class TestCycleHeading:
    """ツールバーの「見出し」ボタン（B-1）。

    `shift_heading` は上げ下げの 2 方向で、ボタン 1 つには収まらない。
    段落 → H1 → H2 → H3 → 段落 と一周させる。H4〜H6 はツールバーからは
    出さない（`Cmd+Ctrl+↑↓` で届く）。押すたびに深くなるだけのボタンは、
    H6 で行き止まりになって戻せない。
    """

    def test_段落は見出しになる(self) -> None:
        assert cycle_heading("メモ") == "# メモ"

    @pytest.mark.parametrize(
        ("line", "expected"),
        [("# メモ", "## メモ"), ("## メモ", "### メモ"), ("### メモ", "メモ")],
    )
    def test_一周する(self, line: str, expected: str) -> None:
        assert cycle_heading(line) == expected

    @pytest.mark.parametrize("line", ["#### メモ", "##### メモ", "###### メモ"])
    def test_深い見出しは段落へ戻す(self, line: str) -> None:
        """手で打った H4〜H6 で行き止まりにしない。"""
        assert cycle_heading(line) == "メモ"

    def test_四回押すと元に戻る(self) -> None:
        line = "メモ"
        for _ in range(4):
            line = cycle_heading(line)
        assert line == "メモ"

    def test_空行でも見出しにできる(self) -> None:
        assert cycle_heading("") == "# "


class TestInsertTable:
    """表を差し込む（ユーザー要望 2026-08-26）。行と列の数はダイアログが聞く。"""

    def test_空の行にそのまま置く(self) -> None:
        got = insert_table("", 0, 0, rows=1, columns=2)
        assert apply("", got).splitlines()[:2] == [
            "| 見出し1 | 見出し2 |",
            "| ------- | ------- |",
        ]

    def test_書きかけの行の下から始める(self) -> None:
        """行の途中で押しても、その行を壊さない。"""
        text = "本文の続き"
        got = insert_table(text, 5, 5, rows=1, columns=1)
        lines = apply(text, got).splitlines()
        assert lines[0] == "本文の続き"
        assert lines[1] == ""  # 段落と表のあいだは空ける（GFM が表と認めない）

    def test_後ろに空行を残す(self) -> None:
        """表の直後から本文を書き続けられるように。"""
        got = apply("", insert_table("", 0, 0, rows=1, columns=1))
        assert got.endswith("\n\n")

    def test_最初の見出しを選ぶ(self) -> None:
        """打てばそのまま置き換わる（目印を消す手間を省く）。"""
        text = ""
        got = insert_table(text, 0, 0, rows=1, columns=2)
        updated = apply(text, got)
        assert updated[got.select_start : got.select_end] == "見出し1"

    def test_選択していた文字は消さない(self) -> None:
        text = "大事な文"
        got = insert_table(text, 0, 4, rows=1, columns=1)
        assert "大事な文" in apply(text, got)
