"""選択範囲を別のノートに切り出す（M-1 / 仮身化）。

BTRON の「選択した部分が新しい実身として切り出され、元の場所には仮身が
残る」を Markdown に写したもの。**ここは Qt を知らない**（R3）ので、
カーソルもファイルも無しで振る舞いを固定できる。

**いちばん大事なのは「書いたリンクが必ず届く」こと。** 題名は本文から
決まる（`document.title_of`）ので、切り詰めたり文字を落としたりすると、
`[[…]]` の先が行方不明になる。最後の不変条件テストがそこを見ている。
"""

import pytest

from hitofude.core import extract
from hitofude.core.document import UNTITLED, title_of


class TestNothingToExtract:
    @pytest.mark.parametrize("selection", ["", "   ", "\n\n", "\t \n "])
    def test_中身が無ければ切り出さない(self, selection) -> None:
        """空のノートを作らない（取り込みと同じ約束）。"""
        assert extract.extract(selection) is None


class TestTitle:
    def test_見出しがあればそれを題名にする(self) -> None:
        found = extract.extract("# 買い物リスト\n\n- 卵\n- 牛乳")
        assert found is not None
        assert found.title == "買い物リスト"

    def test_見出しが無ければ最初の行(self) -> None:
        found = extract.extract("来週の予算について話した。\n\n続きの話。")
        assert found is not None
        assert found.title == "来週の予算について話した。"

    def test_行頭のマーカーは落とす(self) -> None:
        """`- 買い物` が題名になると一覧が読みにくい（`title_of` と同じ流儀）。"""
        found = extract.extract("- 買い物に行く\n- 掃除")
        assert found is not None
        assert found.title == "買い物に行く"

    def test_長すぎる題名は切る(self) -> None:
        found = extract.extract("あ" * 200)
        assert found is not None
        assert len(found.title) == extract.MAX_TITLE_LENGTH

    @pytest.mark.parametrize("bad", ["[", "]", "|"])
    def test_リンクを壊す文字は落とす(self, bad) -> None:
        """`[[…]]` の中に入ると、そこでリンクが切れて別物を指す。"""
        found = extract.extract(f"予算{bad}の話")
        assert found is not None
        assert bad not in found.title

    def test_題名にできる文字が無ければ無題(self) -> None:
        found = extract.extract("[[|]]")
        assert found is not None
        assert found.title == UNTITLED


class TestLink:
    def test_跡に残すのは_wikilink(self) -> None:
        found = extract.extract("# 買い物リスト\n\n- 卵")
        assert found is not None
        assert found.link == "[[買い物リスト]]"


class TestBody:
    def test_選んだ文はそのまま持っていく(self) -> None:
        """**書いた文を書き換えない**（R1 の感覚）。"""
        found = extract.extract("# 買い物リスト\n\n- 卵\n- 牛乳")
        assert found is not None
        assert found.text == "# 買い物リスト\n\n- 卵\n- 牛乳"

    def test_前後の空白は落とす(self) -> None:
        found = extract.extract("\n\n  # 買い物リスト\n\n- 卵  \n\n")
        assert found is not None
        assert found.text.startswith("# 買い物リスト")
        assert found.text.endswith("- 卵")

    def test_題名を作り直したときは見出しを足す(self) -> None:
        """切り詰めた題名のままだと、`[[…]]` の先が見つからない。"""
        found = extract.extract("あ" * 200)
        assert found is not None
        assert found.text.startswith(f"# {found.title}\n\n")
        assert "あ" * 200 in found.text


class TestTakenTitles:
    """**同じ題名を 2 つ作らない**（作った側が曖昧なリンクを作らない）。

    `[[…]]` は題名で解決する（E-6）ので、同じ題名が 2 つあるとどちらへ
    飛ぶか決まらない。ファイル名は `unique_path` が避けてくれるが、
    **題名は本文から決まる**ので避けてくれない。
    """

    def test_ぶつかったら番号を足す(self) -> None:
        found = extract.extract("# 買い物リスト\n\n- 卵", taken=["買い物リスト"])
        assert found is not None
        assert found.title == "買い物リスト 2"

    def test_何度もぶつかったら数を進める(self) -> None:
        found = extract.extract("# 買い物リスト\n\n- 卵", taken=["買い物リスト", "買い物リスト 2"])
        assert found is not None
        assert found.title == "買い物リスト 3"

    def test_大文字小文字の違いもぶつかりと見なす(self) -> None:
        """`resolve` が casefold で照合する（E-6）ので、揃えておく。"""
        found = extract.extract("# Meeting\n\n話した", taken=["meeting"])
        assert found is not None
        assert found.title == "Meeting 2"

    def test_ぶつからなければ触らない(self) -> None:
        found = extract.extract("# 買い物リスト\n\n- 卵", taken=["別のノート"])
        assert found is not None
        assert found.title == "買い物リスト"


SAMPLES = [
    "# 買い物リスト\n\n- 卵\n- 牛乳",
    "来週の予算について話した。",
    "- 買い物に行く\n- 掃除",
    "あ" * 200,
    "予算[の]話|です",
    "[[|]]",
    "> 引用から始まる\n\n本文",
    "```python\nprint(1)\n```",
    "1. 最初の項目\n2. 次の項目",
]


class TestLinkAlwaysResolves:
    """**不変条件**: 書いたリンクの先が、切り出したノートの題名と一致する。

    ここが崩れると `[[…]]` を押しても届かず、しかも**リンク先が無いので
    もう 1 つ作られる**（E-6 の「無ければ作る」）。気づきにくい壊れ方。
    """

    @pytest.mark.parametrize("selection", SAMPLES)
    def test_切り出した本文の題名と一致する(self, selection) -> None:
        found = extract.extract(selection)
        assert found is not None
        assert title_of(found.text, UNTITLED) == found.title

    @pytest.mark.parametrize("selection", SAMPLES)
    def test_ぶつかりを避けた後も一致する(self, selection) -> None:
        first = extract.extract(selection)
        assert first is not None
        second = extract.extract(selection, taken=[first.title])
        assert second is not None
        assert second.title != first.title
        assert title_of(second.text, UNTITLED) == second.title

    @pytest.mark.parametrize("selection", SAMPLES)
    def test_リンクは題名をそのまま包む(self, selection) -> None:
        found = extract.extract(selection)
        assert found is not None
        assert found.link == f"[[{found.title}]]"
