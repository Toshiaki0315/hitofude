"""4 字下げをコードとして扱うかの切り替え（ユーザー要望 2026-08-28）。

**既定は今までどおり on**（CommonMark 準拠。spec §1.3 の方針）。
貼り付けで意図せずコードに化けるのが煩わしい人のために、off にできる。

`core/` は設定を知らない（R3）ので、**呼ぶ側が旗を渡す**。
"""

from hitofude.core.block_parser import BlockState, classify_line, parse
from hitofude.core.models import BlockType
from hitofude.core.slides import Block, BlockKind, split

INDENTED = "本文\n\n    字下げした行\n"


def kinds(text: str, **options) -> list[BlockType]:
    return [block.type for block in parse(text, **options)]


class TestParse:
    def test_既定はコード(self) -> None:
        assert kinds(INDENTED)[2] is BlockType.CODE_FENCE_BODY

    def test_offなら段落(self) -> None:
        assert kinds(INDENTED, indented_code=False)[2] is BlockType.PARAGRAPH

    def test_フェンスは止めない(self) -> None:
        """**止めるのは字下げだけ。** ``` は関係ない。"""
        text = "本文\n\n```python\nprint(1)\n```\n"
        found = kinds(text, indented_code=False)
        assert found[2] is BlockType.CODE_FENCE_OPEN
        assert found[3] is BlockType.CODE_FENCE_BODY
        assert found[4] is BlockType.CODE_FENCE_CLOSE

    def test_リストの入れ子は元から段落(self) -> None:
        """on でも off でも変わらない（元からコードではない）。"""
        text = "- 項目\n\n    続き\n"
        assert kinds(text)[2] is kinds(text, indented_code=False)[2]


class TestClassifyLine:
    """ハイライタは 1 行ずつ見る（`parse` とは別の口）。両方を揃える。"""

    def state(self) -> BlockState:
        return BlockState(after_blank=True)

    def test_既定はコード(self) -> None:
        block, _ = classify_line("    字下げした行", 2, self.state())
        assert block.type is BlockType.CODE_FENCE_BODY

    def test_offなら段落(self) -> None:
        block, _ = classify_line("    字下げした行", 2, self.state(), indented_code=False)
        assert block.type is BlockType.PARAGRAPH

    def test_続きも段落のまま(self) -> None:
        """off のとき、2 行目以降も引きずられない。"""
        state = self.state()
        _, state = classify_line("    1 行目", 2, state, indented_code=False)
        second, _ = classify_line("    2 行目", 3, state, indented_code=False)
        assert second.type is BlockType.PARAGRAPH


class TestSlides:
    """スライド分割（F-4）でも同じにする。フェンスが無いコードを黙って落とさない。"""

    def blocks(self, body: str) -> list[Block]:
        return split(f"# 題\n\n## 頁\n\n{body}").slides[0].blocks

    def test_字下げコードがスライドに載る(self) -> None:
        """回帰: CLOSE 行が来ないため溜めたまま捨てられ、blocks が空になっていた。"""
        found = self.blocks("    字下げした行\n")
        assert [b.kind for b in found] == [BlockKind.CODE]
        assert found[0].text == "字下げした行"

    def test_既定では段落にならない(self) -> None:
        assert all(b.kind is not BlockKind.PARAGRAPH for b in self.blocks("    字下げした行\n"))

    def test_言語は持たない(self) -> None:
        assert self.blocks("    x = 1\n")[0].language == ""

    def test_前のフェンスの言語を引きずらない(self) -> None:
        found = self.blocks("```python\nprint(1)\n```\n\n    字下げ\n")
        assert [b.language for b in found] == ["python", ""]

    def test_連続する行は1つのブロック(self) -> None:
        found = self.blocks("    1 行目\n    2 行目\n")
        assert [b.kind for b in found] == [BlockKind.CODE]
        assert found[0].text == "1 行目\n2 行目"

    def test_空行を挟んでも1つのブロック(self) -> None:
        """空行はコードを終わらせない（CommonMark）。"""
        found = self.blocks("    1 行目\n\n    2 行目\n")
        assert [b.kind for b in found] == [BlockKind.CODE]
        assert found[0].text == "1 行目\n\n2 行目"

    def test_後続の段落とは分かれる(self) -> None:
        found = self.blocks("    コード\n\n普通の文\n")
        assert [b.kind for b in found] == [BlockKind.CODE, BlockKind.PARAGRAPH]


class TestHtml:
    """書き出しも同じにする。**画面と食い違わせない。**"""

    def test_offなら段落として書き出す(self) -> None:
        from hitofude.core.html import render

        assert "<pre>" in render(INDENTED)
        assert "<pre>" not in render(INDENTED, indented_code=False)


class TestSlides:
    """スライドの分解も同じ旗に従う（レビュー指摘 2026-08-31）。

    既定（on）ではフェンスの無いコード本文をスライドに載せない
    （`_Builder` は ``` で開いたときだけコードを溜める）ので、
    off にしたときに**段落として現れる**ことを見る。
    """

    TEXT = "# 題\n\n## 頁\n\n    字下げした行\n"

    def blocks(self, **options) -> list:
        from hitofude.core.slides import split

        deck = split(self.TEXT, **options)
        return deck.slides[0].blocks

    def test_既定では段落にならない(self) -> None:
        from hitofude.core.slides import BlockKind

        assert not any(
            block.kind is BlockKind.PARAGRAPH and "字下げした行" in block.text
            for block in self.blocks()
        )

    def test_offなら段落として載る(self) -> None:
        from hitofude.core.slides import BlockKind

        assert any(
            block.kind is BlockKind.PARAGRAPH and "字下げした行" in block.text
            for block in self.blocks(indented_code=False)
        )
