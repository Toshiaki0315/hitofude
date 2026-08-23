"""リンクに付く関係のラベル（M-3 / 続柄）。

BTRON の「続柄」——タグはノートに付くが、**続柄はリンクに付く**。
「参考文献として参照しているノート」を引けるようにするためのもの。

**新しい記法は作らない。** 独自記法は他のエディタで開いたときにただの
ゴミになり、R1 の趣旨（素の `.md` として読める）と噛み合わない。
**箇条書きの行の `:` より前**を続柄として読む——これはただの Markdown。
"""

import pytest

from hitofude.core import wikilink


def found(text: str) -> dict[str, str]:
    return dict(wikilink.relations(text))


class TestPlainLinks:
    def test_続柄が無ければ空(self) -> None:
        assert found("[[会議メモ]] を見る") == {"会議メモ": ""}

    def test_箇条書きでも印が無ければ空(self) -> None:
        assert found("- [[会議メモ]]") == {"会議メモ": ""}

    def test_リンクが無ければ何も返さない(self) -> None:
        assert wikilink.relations("ただの文章です。") == []


class TestRelation:
    def test_箇条書きの_コロンより前が続柄(self) -> None:
        assert found("- 参考文献: [[BTRON の仮身]]") == {"BTRON の仮身": "参考文献"}

    @pytest.mark.parametrize("marker", ["- ", "* ", "+ ", "1. ", "2) "])
    def test_いろいろな箇条書きの印(self, marker: str) -> None:
        assert found(f"{marker}元ネタ: [[日報]]") == {"日報": "元ネタ"}

    def test_字下げした箇条書きでも読む(self) -> None:
        assert found("    - 参考文献: [[本]]") == {"本": "参考文献"}

    def test_チェックボックスの行でも読む(self) -> None:
        assert found("- [ ] 宿題: [[調べもの]]") == {"調べもの": "宿題"}

    def test_全角のコロンも読む(self) -> None:
        """**日本語で書くなら全角が自然。** 半角しか読まないと使われない。"""
        assert found("- 参考文献：[[本]]") == {"本": "参考文献"}

    def test_同じ行の複数のリンクは同じ続柄(self) -> None:
        assert found("- 参考文献: [[本A]] と [[本B]]") == {"本A": "参考文献", "本B": "参考文献"}

    def test_前後の空白は落とす(self) -> None:
        assert found("-   参考文献  :  [[本]]") == {"本": "参考文献"}


class TestNotARelation:
    def test_地の文は読まない(self) -> None:
        """**誤検出のほうが害が大きい。** 無い関係が図に現れる。"""
        assert found("今日は: [[会議メモ]] を書いた") == {"会議メモ": ""}

    def test_時刻は続柄にしない(self) -> None:
        """`10:30` を「10」という続柄にしない。**半角の後ろに空白を要る**ことで防ぐ。"""
        assert found("- 10:30 の打ち合わせ [[会議メモ]]") == {"会議メモ": ""}

    def test_URL_も続柄にしない(self) -> None:
        assert found("- https://example.com と [[会議メモ]]") == {"会議メモ": ""}

    def test_リンクより後ろのコロンは見ない(self) -> None:
        assert found("- [[会議メモ]]: 来週の話") == {"会議メモ": ""}

    def test_続柄にリンクは入れない(self) -> None:
        assert found("- [[本]] の話: [[会議メモ]]") == {"本": "", "会議メモ": ""}

    def test_長すぎるものは続柄にしない(self) -> None:
        """**関係の名前は短い。** 長い一文は、たまたまコロンが入った地の文。"""
        long = "あ" * (wikilink.MAX_RELATION + 1)
        assert found(f"- {long}: [[会議メモ]]") == {"会議メモ": ""}

    def test_ちょうどの長さは通す(self) -> None:
        edge = "あ" * wikilink.MAX_RELATION
        assert found(f"- {edge}: [[会議メモ]]") == {"会議メモ": edge}

    def test_コロンの前が空なら続柄にしない(self) -> None:
        assert found("- : [[会議メモ]]") == {"会議メモ": ""}


class TestSameAsLinks:
    def test_コードの中は数えない(self) -> None:
        """`links()` と同じ規則（§6.5 規則 1）。"""
        assert wikilink.relations("```\n- 参考文献: [[本]]\n```") == []

    def test_front_matter_は見ない(self) -> None:
        text = "---\nid: 01M0\n---\n- 参考文献: [[本]]\n"
        assert found(text) == {"本": "参考文献"}

    def test_指している先は_links_と揃う(self) -> None:
        text = "- 参考文献: [[本]]\n\n[[会議メモ]] も見る\n- 元ネタ: [[本]]\n"
        assert {target for target, _ in wikilink.relations(text)} == set(wikilink.links(text))

    def test_名前は_links_と同じに揃える(self) -> None:
        assert found("- 参考文献: [[  会議  メモ  ]]") == {"会議 メモ": "参考文献"}


class TestDuplicates:
    def test_同じ続柄で二度指しても_1_つ(self) -> None:
        text = "- 参考文献: [[本]]\n- 参考文献: [[本]]\n"
        assert wikilink.relations(text) == [("本", "参考文献")]

    def test_違う続柄なら両方残す(self) -> None:
        """**同じ相手を別の関係で指せる。** 索引の主キーもそれに合わせる。"""
        text = "- 参考文献: [[本]]\n- 元ネタ: [[本]]\n"
        assert wikilink.relations(text) == [("本", "参考文献"), ("本", "元ネタ")]

    def test_出てきた順に返す(self) -> None:
        text = "- あ: [[X]]\n- い: [[Y]]\n"
        assert wikilink.relations(text) == [("X", "あ"), ("Y", "い")]
