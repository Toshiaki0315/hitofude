"""Markdown をスライドの構造に割る（F-4）。

**書き出しの土台。** ここは純関数で、PowerPoint そのものは知らない
（組み立ては F-5 の `editor/pptx_export.py`）。

区切りは決めたとおり:

- `#` は**タイトルスライド**。その下の段落が副題になる
- `##` ごとに 1 枚
- 画像は**右側**に置くので、本文とは分けて持つ
- `>` の引用は**発表者ノート**（スライドには出さない）
"""

import pytest

from hitofude.core.slides import BlockKind, split

DECK = """# 2026 年次世代 AI プロジェクト

DX 推進チームによる業務改革のご提案

## プロジェクトの目的

AI を活用した業務効率の向上を目指します。

- 期間: 2026 年 1 月 〜 12 月
- 目標: 手作業の 80% 削減
    - まずは申請業務から

### システムの老朽化

既存システムの動作が遅い。

![](attachments/構成図.png)

> 最初の 3 分で目的を話す

## 実装の例

```python
def hello() -> str:
    return "こんにちは"
```

| 担当 | 人数 |
| --- | --- |
| DX | 5 名 |
"""


@pytest.fixture
def deck():
    return split(DECK)


class TestTitleSlide:
    def test_大見出しが題名(self, deck) -> None:
        assert deck.title == "2026 年次世代 AI プロジェクト"

    def test_その下の段落が副題(self, deck) -> None:
        assert deck.subtitle == "DX 推進チームによる業務改革のご提案"

    def test_題が無ければ空(self) -> None:
        found = split("## 1 枚目\n\n本文\n")
        assert found.title == ""
        assert found.subtitle == ""

    def test_front_matterは見ない(self) -> None:
        found = split("---\nid: ABC\n---\n\n# 題名\n")
        assert found.title == "題名"


class TestSlides:
    def test_中見出しごとに1枚(self, deck) -> None:
        assert [slide.title for slide in deck.slides] == ["プロジェクトの目的", "実装の例"]

    def test_中見出しが無ければ1枚も作らない(self) -> None:
        assert split("# 題名\n\n本文\n").slides == []

    def test_題名より前の中見出しも拾う(self) -> None:
        found = split("## 1 枚目\n\n本文\n")
        assert len(found.slides) == 1

    def test_空でも壊れない(self) -> None:
        found = split("")
        assert found.title == ""
        assert found.slides == []


class TestBlocks:
    def kinds(self, slide) -> list:
        return [block.kind for block in slide.blocks]

    def test_段落が入る(self, deck) -> None:
        first = deck.slides[0]
        assert first.blocks[0].kind is BlockKind.PARAGRAPH
        assert first.blocks[0].text == "AI を活用した業務効率の向上を目指します。"

    def test_箇条書きが入る(self, deck) -> None:
        bullets = [b for b in deck.slides[0].blocks if b.kind is BlockKind.BULLET]
        assert bullets[0].text == "期間: 2026 年 1 月 〜 12 月"

    def test_箇条書きの階層を保つ(self, deck) -> None:
        bullets = [b for b in deck.slides[0].blocks if b.kind is BlockKind.BULLET]
        assert [b.level for b in bullets] == [0, 0, 1]

    def test_小見出しが入る(self, deck) -> None:
        headings = [b for b in deck.slides[0].blocks if b.kind is BlockKind.HEADING]
        assert [b.text for b in headings] == ["システムの老朽化"]

    def test_コードが1つのブロックになる(self, deck) -> None:
        code = [b for b in deck.slides[1].blocks if b.kind is BlockKind.CODE]
        assert len(code) == 1
        assert code[0].text == 'def hello() -> str:\n    return "こんにちは"'

    def test_コードの言語を持つ(self, deck) -> None:
        code = next(b for b in deck.slides[1].blocks if b.kind is BlockKind.CODE)
        assert code.language == "python"

    def test_表が1つのブロックになる(self, deck) -> None:
        """**セルには割らない。** 割る道具は表示側にあり、層が逆向きになる。"""
        table = [b for b in deck.slides[1].blocks if b.kind is BlockKind.TABLE]
        assert len(table) == 1
        assert table[0].lines == ["| 担当 | 人数 |", "| DX | 5 名 |"]

    def test_マーカーは外す(self, deck) -> None:
        """スライドに `**` の文字を出さない。"""
        found = split("## 枚\n\n**強調**した文\n")
        assert found.slides[0].blocks[0].text == "強調した文"


class TestImages:
    def test_画像は本文と分けて持つ(self, deck) -> None:
        """右側に置くので、本文の並びに混ぜない。"""
        assert deck.slides[0].images == ["attachments/構成図.png"]

    def test_画像は本文のブロックに入らない(self, deck) -> None:
        assert all(block.kind is not BlockKind.IMAGE for block in deck.slides[0].blocks)

    def test_画像が無ければ空(self, deck) -> None:
        assert deck.slides[1].images == []

    def test_複数の画像も拾う(self) -> None:
        found = split("## 枚\n\n![](a.png)\n\n![](b.png)\n")
        assert found.slides[0].images == ["a.png", "b.png"]

    def test_文中の画像は右に出さない(self) -> None:
        """行まるごとが画像のときだけ。文の途中の絵は本文の一部。"""
        found = split("## 枚\n\n図は ![](a.png) です。\n")
        assert found.slides[0].images == []


class TestNotes:
    def test_引用は発表者ノート(self, deck) -> None:
        assert deck.slides[0].notes == "最初の 3 分で目的を話す"

    def test_ノートは本文に出さない(self, deck) -> None:
        assert all("最初の 3 分" not in block.text for block in deck.slides[0].blocks)

    def test_複数行の引用は繋ぐ(self) -> None:
        found = split("## 枚\n\n> 一行目\n> 二行目\n")
        assert found.slides[0].notes == "一行目\n二行目"

    def test_ノートが無ければ空(self, deck) -> None:
        assert deck.slides[1].notes == ""


class TestPure:
    def test_元の文字列を変えない(self) -> None:
        text = DECK
        split(text)
        assert text == DECK

    def test_同じ入力からは同じ結果(self) -> None:
        assert split(DECK) == split(DECK)
