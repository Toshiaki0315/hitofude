"""見出しの一覧（C-2 / アウトライン）。

長いノートで迷子にならないよう、見出しへ飛べるようにする。
`core/` にあるので PySide6 に依存しない（R3）。
"""

import pytest

from hitofude.core.outline import headings


class TestExtract:
    def test_見出しを拾う(self) -> None:
        found = headings("# 大見出し\n\n本文\n\n## 中見出し\n")
        assert [h.text for h in found] == ["大見出し", "中見出し"]

    def test_深さを返す(self) -> None:
        found = headings("# 一\n## 二\n### 三\n")
        assert [h.level for h in found] == [1, 2, 3]

    def test_行番号を返す(self) -> None:
        """飛び先に使うので、0 始まりの行番号が要る。"""
        assert [h.line for h in headings("本文\n\n## 見出し\n")] == [2]

    def test_記号は含めない(self) -> None:
        assert headings("### 見出し ###\n")[0].text == "見出し"

    def test_装飾は残す(self) -> None:
        """`**強調**` を消すと元の行と対応が取れなくなる。"""
        assert headings("# **強調**した見出し\n")[0].text == "**強調**した見出し"

    def test_見出しが無ければ空(self) -> None:
        assert headings("ただの段落\n") == []

    def test_空でも落ちない(self) -> None:
        assert headings("") == []


class TestNotHeadings:
    """見出しでないものを拾わない。"""

    def test_コードブロックの中は拾わない(self) -> None:
        assert headings("```\n# コメント\n```\n") == []

    def test_タグは拾わない(self) -> None:
        assert headings("#タグ だけの行\n") == []

    def test_front_matterの中は拾わない(self) -> None:
        assert headings("---\nid: x\n---\n\n# 見出し\n")[0].text == "見出し"

    def test_引用の中の見出しは拾わない(self) -> None:
        """引用は「引用元の文章」で、このノートの構造ではない。"""
        assert headings("> # 引用の中\n") == []

    def test_7個のシャープは見出しではない(self) -> None:
        assert headings("####### 見出しではない\n") == []


class TestPreview:
    def test_中身が空の見出しも拾う(self) -> None:
        found = headings("## \n")
        assert len(found) == 1
        assert found[0].text == ""

    @pytest.mark.parametrize("source", ["# 一\n" * 50, "本文\n" * 200])
    def test_大きくても落ちない(self, source: str) -> None:
        headings(source)
