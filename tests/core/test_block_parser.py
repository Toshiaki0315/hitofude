"""ブロックパーサのテスト（タスク 1-9 / spec §3.4, §6.2）。

`parse()` は**ソース 1 行につき BlockInfo を 1 個**返す。
`QTextBlock` と 1:1 で対応させるという設計（§6.2）を型と個数で担保する。
"""

import pytest

from hitofude.core.block_parser import classify_line, parse
from hitofude.core.models import UNKNOWN_NOTE_KIND, BlockInfo, BlockState, BlockType


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

    def test_入れ子の番号リストの後は箇条書きに戻る(self) -> None:
        """ordered フラグが単一のブールで、入れ子を閉じても戻らなかった
        （回帰）。後続の `- c` が ORDERED_LIST_ITEM / marker_len=0 になり、
        ぶら下げ描画とマーカー補正が壊れていた。"""
        blocks = parse("- a\n  1. b\n- c")
        assert blocks[2].type is BlockType.BULLET_LIST_ITEM
        assert blocks[2].marker_len == 2

    def test_入れ子の箇条書きの後は番号リストに戻る(self) -> None:
        blocks = parse("1. a\n   - b\n2. c")
        assert blocks[2].type is BlockType.ORDERED_LIST_ITEM
        assert blocks[2].marker_len == 3

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

    def test_4連フェンスは3連で閉じない(self) -> None:
        """CommonMark: 閉じは開きと同じ長さ以上の run。3 連固定で判定して
        いたため `classify_line` と食い違っていた（回帰）。"""
        blocks = parse("````\ncode\n```")
        assert blocks[2].type is BlockType.CODE_FENCE_BODY

    def test_4連フェンスは4連で閉じる(self) -> None:
        assert parse("````\ncode\n````")[2].type is BlockType.CODE_FENCE_CLOSE

    def test_閉じフェンスに文字が続くなら閉じない(self) -> None:
        assert parse("```\ncode\n``` x")[2].type is BlockType.CODE_FENCE_BODY


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


def _classified(text: str) -> list[BlockInfo]:
    """ハイライタと同じ経路（行単位）で分類する。"""
    state = BlockState()
    found = []
    for number, line in enumerate(text.split("\n")):
        info, state = classify_line(line, number, state)
        found.append(info)
    return found


class TestIndentedCode:
    """4 スペースのインデントコード（CommonMark の indented code block）。

    **一度も検証されていなかった**（書き込みの順序を入れ替える実験が
    素通りして判明）。フェンスは無いが中身はコードなので、装飾を効かせない。
    """

    def test_コードとして扱う(self) -> None:
        blocks = parse("本文\n\n    print('code')\n    x = 1\n\n本文\n")
        assert blocks[2].type is BlockType.CODE_FENCE_BODY
        assert blocks[3].type is BlockType.CODE_FENCE_BODY

    def test_前後の段落は段落のまま(self) -> None:
        blocks = parse("本文\n\n    code\n\nあと\n")
        assert blocks[0].type is BlockType.PARAGRAPH
        assert blocks[4].type is BlockType.PARAGRAPH

    def test_段落より優先しない(self) -> None:
        """**書き込みの順序に効く。** インデントコードは最も優先度が低い。

        段落の続きとして 4 スペース下げた行は、コードではなく段落。
        ここを最優先にすると、ぶら下げインデントがコードになってしまう。
        """
        blocks = parse("本文のつづきが\n    ぶら下がっている\n")
        assert blocks[1].type is BlockType.PARAGRAPH

    def test_箇条書きの中の字下げはコードにしない(self) -> None:
        blocks = parse("- 項目\n    - 入れ子の項目\n")
        assert blocks[1].type is not BlockType.CODE_FENCE_BODY

    def test_行単位の判定とも一致する(self) -> None:
        """`parse()` とハイライタで扱いが食い違わないこと。

        以前は `classify_line()` が段落と見ており、エディタ上で `**` が
        強調として描かれていた（テストを足したときに判明）。
        """
        text = "本文\n\n    **これは強調ではない**\n"
        assert parse(text)[2].type is BlockType.CODE_FENCE_BODY
        assert _classified(text)[2].type is BlockType.CODE_FENCE_BODY

    def test_中の記号は装飾として解釈しない(self) -> None:
        """コードなので `**` はただの文字。"""
        from hitofude.core.document import plain_text

        assert "**これは強調ではない**" in plain_text("本文\n\n    **これは強調ではない**\n")

    def test_タブ字下げもコードにする(self) -> None:
        blocks = parse("本文\n\n\tprint('code')\n")
        assert blocks[2].type is BlockType.CODE_FENCE_BODY

    def test_フェンスと混在しても壊れない(self) -> None:
        text = "```\nフェンスの中\n```\n\n本文\n\n    字下げのコード\n"
        blocks = parse(text)
        assert blocks[1].type is BlockType.CODE_FENCE_BODY
        assert blocks[6].type is BlockType.CODE_FENCE_BODY


class TestIndentedCodeLineByLine:
    """行単位の判定（ハイライタが使う経路）。

    行だけを見て「インデントコードの始まり」を決めるには、
    **前の行が空行か**と**リストの中か**を知る必要がある。
    """

    def test_空行の後の字下げはコード(self) -> None:
        assert _classified("本文\n\n    code\n")[2].type is BlockType.CODE_FENCE_BODY

    def test_段落のぶら下げはコードにしない(self) -> None:
        """前の行が空行でなければ、字下げは段落の続き。"""
        assert _classified("本文のつづきが\n    ぶら下がっている\n")[1].type is BlockType.PARAGRAPH

    def test_箇条書きの入れ子はコードにしない(self) -> None:
        """リストの中では字下げが入れ子を意味する（§6.4）。"""
        assert _classified("- 項目\n    - 入れ子\n")[1].type is BlockType.BULLET_LIST_ITEM

    def test_番号付きの入れ子もコードにしない(self) -> None:
        assert _classified("1. 項目\n    1. 入れ子\n")[1].type is BlockType.ORDERED_LIST_ITEM

    def test_続く字下げもコードのまま(self) -> None:
        blocks = _classified("本文\n\n    一行目\n    二行目\n")
        assert blocks[3].type is BlockType.CODE_FENCE_BODY

    def test_間の空行を挟んでも続く(self) -> None:
        blocks = _classified("本文\n\n    一行目\n\n    二行目\n")
        assert blocks[4].type is BlockType.CODE_FENCE_BODY

    def test_字下げが終わればコードも終わる(self) -> None:
        blocks = _classified("本文\n\n    code\n\nあとの本文\n")
        assert blocks[4].type is BlockType.PARAGRAPH

    def test_タブでも始まる(self) -> None:
        assert _classified("本文\n\n\tcode\n")[2].type is BlockType.CODE_FENCE_BODY

    def test_3スペースでは始まらない(self) -> None:
        """CommonMark は 4 スペース以上。3 つは段落。"""
        assert _classified("本文\n\n   まだ段落\n")[2].type is BlockType.PARAGRAPH

    def test_文書の先頭から始められる(self) -> None:
        assert _classified("    code\n")[0].type is BlockType.CODE_FENCE_BODY

    def test_フェンスの中は今まで通り(self) -> None:
        blocks = _classified("```\n    字下げされたコード\n```\n")
        assert blocks[1].type is BlockType.CODE_FENCE_BODY
        assert blocks[2].type is BlockType.CODE_FENCE_CLOSE

    def test_見出しの後でも始まる(self) -> None:
        assert _classified("# 見出し\n\n    code\n")[2].type is BlockType.CODE_FENCE_BODY

    def test_リストが終われば再び始まる(self) -> None:
        blocks = _classified("- 項目\n\nふつうの段落\n\n    code\n")
        assert blocks[4].type is BlockType.CODE_FENCE_BODY


class TestQiitaNote:
    """`:::note info` の囲み（B-3）。

    ハイライタが通る行単位の経路（`classify_line`）で見る。書き出し側は
    `tests/core/test_html.py`。**囲みの中でも他の記法は今まで通り効く**
    ことが要で、そこが崩れると囲みを使った瞬間に本文の装飾が全部死ぬ。
    """

    def test_開始行は区切りとして分類する(self) -> None:
        assert _classified(":::note info\n本文\n:::\n")[0].type is BlockType.NOTE_DELIMITER

    def test_終了行も区切り(self) -> None:
        assert _classified(":::note info\n本文\n:::\n")[2].type is BlockType.NOTE_DELIMITER

    @pytest.mark.parametrize("kind", ["info", "warn", "alert"])
    def test_種類を覚える(self, kind: str) -> None:
        assert _classified(f":::note {kind}\n本文\n:::\n")[0].note_kind == kind

    def test_種類を省くと情報扱い(self) -> None:
        assert _classified(":::note\n本文\n:::\n")[0].note_kind == "info"

    def test_知らない種類は別扱い(self) -> None:
        """綴りを間違えても囲みごと消えないが、`info` にも寄せない
        （`TestUnknownNoteKind` が理由を持っている）。"""
        assert _classified(":::note なにか\n本文\n:::\n")[0].note_kind == UNKNOWN_NOTE_KIND

    def test_中の行にも種類が付く(self) -> None:
        """縦線を引くのに要る。行ごとに描くので行ごとに知る必要がある。"""
        assert _classified(":::note warn\n本文\n:::\n")[1].note_kind == "warn"

    def test_中の行は普通に分類される(self) -> None:
        blocks = _classified(":::note info\n# 見出し\n- 項目\n:::\n")
        assert blocks[1].type is BlockType.HEADING
        assert blocks[2].type is BlockType.BULLET_LIST_ITEM

    def test_閉じたら種類は消える(self) -> None:
        assert _classified(":::note info\n本文\n:::\n外\n")[3].note_kind is None

    def test_囲みの外は何も付かない(self) -> None:
        assert _classified("段落\n")[0].note_kind is None

    def test_コードフェンスを挟んでも囲みは続く(self) -> None:
        """フェンスは状態を作り直すので、そこで囲みを落としやすい。"""
        blocks = _classified(":::note info\n```\nx\n```\n本文\n:::\n")
        assert blocks[2].type is BlockType.CODE_FENCE_BODY
        assert blocks[4].note_kind == "info"

    def test_コードフェンスの中の区切りは囲みにしない(self) -> None:
        blocks = _classified("```\n:::note info\n```\n")
        assert blocks[1].type is BlockType.CODE_FENCE_BODY

    def test_閉じ忘れても後続は壊れない(self) -> None:
        blocks = _classified(":::note info\n本文\n")
        assert blocks[1].type is BlockType.PARAGRAPH

    def test_引用の中の区切りは囲みにしない(self) -> None:
        """`> :::note` は引用の本文。行頭から始まるものだけを見る。"""
        assert _classified("> :::note info\n")[0].type is BlockType.BLOCKQUOTE


class TestUnknownNoteKind:
    """`:::note warm` のような綴り違い（ユーザー報告）。

    元は `info` に寄せていたが、**青い線が出るだけで間違いに気づけない**。
    「消えるより出るほうがよい」は正しくても、間違いを正しいものに
    見せてしまうのはやり過ぎだった。別扱いにして、見て分かるようにする。
    """

    @pytest.mark.parametrize("kind", ["warm", "infoo", "注意", "INFO"])
    def test_知らない綴りは別扱い(self, kind: str) -> None:
        assert _classified(f":::note {kind}\n本文\n:::\n")[0].note_kind == UNKNOWN_NOTE_KIND

    def test_中の行にも付く(self) -> None:
        assert _classified(":::note warm\n本文\n:::\n")[1].note_kind == UNKNOWN_NOTE_KIND

    def test_囲みとしては成立する(self) -> None:
        """本文を失わない。書いた内容は残す。"""
        assert _classified(":::note warm\n本文\n:::\n")[0].type is BlockType.NOTE_DELIMITER

    def test_省略は今まで通り情報扱い(self) -> None:
        """`:::note` だけなら書き忘れではなく省略。綴り違いとは区別する。"""
        assert _classified(":::note\n本文\n:::\n")[0].note_kind == "info"

    @pytest.mark.parametrize("line", [":::note warn extra", ":::note info さらに何か"])
    def test_語が2つ以上並んだら囲みにしない(self, line: str) -> None:
        """書き出し側と食い違っていた（画面は囲みにせず、書き出しは warn に
        していた）。画面側に揃える。"""
        assert _classified(f"{line}\n本文\n:::\n")[0].note_kind is None


class TestMathBlock:
    """複数行の `$$` ブロック（B-5）。

    書き出しでは中央に組まれるのに、画面では**ただの段落**に見えていた。
    1 行に書いた `$$x$$` は印が付くのに、複数行だと付かないのは食い違い。
    """

    def test_開始行を区切りとして分類する(self) -> None:
        assert _classified("$$\nx = 1\n$$\n")[0].type is BlockType.MATH_DELIMITER

    def test_終了行も区切り(self) -> None:
        assert _classified("$$\nx = 1\n$$\n")[2].type is BlockType.MATH_DELIMITER

    def test_中身は数式の本体(self) -> None:
        assert _classified("$$\nx = 1\n$$\n")[1].type is BlockType.MATH_BODY

    def test_複数行の中身すべてが本体(self) -> None:
        blocks = _classified("$$\na = 1\nb = 2\n$$\n")
        assert [b.type for b in blocks[1:3]] == [BlockType.MATH_BODY] * 2

    def test_閉じたら元に戻る(self) -> None:
        assert _classified("$$\nx\n$$\n段落\n")[3].type is BlockType.PARAGRAPH

    def test_中では他の記法が効かない(self) -> None:
        """数式の `#` や `_` は装飾ではない。コードブロックと同じ扱い。"""
        assert _classified("$$\n# not heading\n$$\n")[1].type is BlockType.MATH_BODY

    def test_コードフェンスの中の記号は数式にしない(self) -> None:
        assert _classified("```\n$$\nx\n```\n")[1].type is BlockType.CODE_FENCE_BODY

    def test_1行に書いたものは区切りにしない(self) -> None:
        """`$$x$$` は行内の数式（`inline_scanner` が拾う）。"""
        assert _classified("$$x = 1$$\n")[0].type is BlockType.PARAGRAPH

    def test_閉じ忘れても後続は壊れない(self) -> None:
        blocks = _classified("$$\nx = 1\n")
        assert blocks[1].type is BlockType.MATH_BODY
