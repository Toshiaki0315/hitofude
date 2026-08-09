"""Markdown → HTML（B-2）。

書き出しの土台。**`QTextDocument.setMarkdown()` をやめてここに移した**理由は、
あちらが記法を落とすため（実測値は ADR-0007）。落ちていたものを、ここで
落ちないことを確かめる。

`core/` にあるので PySide6 に依存しない（R3）。ヘッドレスで全部見られる。
"""

import pytest

from hitofude.core.html import render


class TestBasics:
    def test_見出し(self) -> None:
        assert "<h1>見出し</h1>" in render("# 見出し\n")

    def test_強調(self) -> None:
        assert "<strong>強調</strong>" in render("**強調**\n")

    def test_斜体(self) -> None:
        assert "<em>斜体</em>" in render("*斜体*\n")

    def test_打ち消し(self) -> None:
        assert "<s>消す</s>" in render("~~消す~~\n")

    def test_インラインコード(self) -> None:
        assert "<code>x</code>" in render("`x`\n")

    def test_リンク(self) -> None:
        assert '<a href="https://example.com">Qt</a>' in render("[Qt](https://example.com)\n")

    def test_箇条書き(self) -> None:
        assert "<ul>" in render("- あ\n- い\n")

    def test_番号付き(self) -> None:
        assert "<ol>" in render("1. あ\n2. い\n")

    def test_引用(self) -> None:
        assert "<blockquote>" in render("> 引用\n")

    def test_水平線(self) -> None:
        assert "<hr" in render("---\n")

    def test_空でも壊れない(self) -> None:
        assert render("") == ""

    def test_front_matterは出さない(self) -> None:
        """`id` や `modified` は管理情報で、読む人には意味がない。"""
        html = render("---\nid: abc123\n---\n\n# 見出し\n")
        assert "abc123" not in html
        assert "<h1>見出し</h1>" in html


class TestWhatSetMarkdownLost:
    """`setMarkdown()` が落としていたもの（ADR-0007 の実測表）。

    B-3〜B-5 はここが通ることの上に乗る。
    """

    def test_コードフェンスの言語が残る(self) -> None:
        """Mermaid（B-4）と行番号付きの色分けはこの class を見る。"""
        assert 'class="language-python"' in render("```python\nx = 1\n```\n")

    def test_言語の無いフェンスも出る(self) -> None:
        assert "<pre><code>" in render("```\nx = 1\n```\n")

    def test_表が出る(self) -> None:
        html = render("| 左 | 右 |\n| --- | --- |\n| a | b |\n")
        assert "<table>" in html
        assert "<th>左</th>" in html
        assert "<td>a</td>" in html

    def test_代替テキストが空の画像も残る(self) -> None:
        """`setMarkdown()` は `<img>` ごと落としていた（貼った画像がまさにこの形）。"""
        assert "<img" in render("![](attachments/x.png)\n")
        assert 'src="attachments/x.png"' in render("![](attachments/x.png)\n")

    def test_代替テキストは保つ(self) -> None:
        assert 'alt="図"' in render("![図](x.png)\n")


class TestTaskList:
    """チェックボックス。

    `setMarkdown()` は `<li class="unchecked">` にして **`[ ]` の文字を消していた**。
    スタイルを当てない限りブラウザにも PDF にも印が出ず、チェック済みかどうかが
    分からなくなる（実測）。記号そのものを置いて、どこで開いても読めるようにする。
    """

    def test_未チェックは白い四角(self) -> None:
        assert "☐ 買い物" in render("- [ ] 買い物\n")

    def test_チェック済みは印の付いた四角(self) -> None:
        assert "☑ 買い物" in render("- [x] 買い物\n")

    def test_大文字のXも見る(self) -> None:
        assert "☑ 買い物" in render("- [X] 買い物\n")

    def test_角括弧は残さない(self) -> None:
        assert "[ ]" not in render("- [ ] 買い物\n")

    def test_番号付きでも効く(self) -> None:
        assert "☐ 買い物" in render("1. [ ] 買い物\n")

    def test_入れ子でも効く(self) -> None:
        assert render("- [ ] 親\n  - [x] 子\n").count("☐") == 1

    def test_リストでない角括弧は触らない(self) -> None:
        """段落の `[ ]` はただの文字。"""
        assert "[ ] これは文字" in render("[ ] これは文字\n")

    def test_コードブロックの中は触らない(self) -> None:
        assert "- [ ] 素のまま" in render("```\n- [ ] 素のまま\n```\n")


class TestRawHtml:
    """本文の生 HTML は出さない。

    書き出した HTML は他人に渡る。ノートに紛れ込んだ `<script>` が、
    開いた相手の環境で動くのは筋が悪い。`setMarkdown()` も落としていたので
    振る舞いとしても変わらない。
    """

    def test_スクリプトタグは実行できる形にしない(self) -> None:
        assert "<script>" not in render("<script>alert(1)</script>\n")

    def test_文字としては残す(self) -> None:
        """消すと本文が黙って減る。エスケープして見せる。"""
        assert "script" in render("<script>alert(1)</script>\n")

    def test_属性の中に閉じ込められない(self) -> None:
        assert 'onerror="' not in render('<img src=x onerror="alert(1)">\n')


class TestSourceUntouched:
    """R1: 書き出しは一方通行。元の文字列を変えない。"""

    def test_元の文字列を変えない(self) -> None:
        text = "# 見出し\n\n- [ ] やること\n"
        render(text)
        assert text == "# 見出し\n\n- [ ] やること\n"

    @pytest.mark.parametrize(
        "text", ["# あ\n", "- [ ] い\n", "```\nコード\n```\n", "| a |\n| --- |\n"]
    )
    def test_同じ入力からは同じ結果(self, text: str) -> None:
        assert render(text) == render(text)


class TestQiitaNote:
    """`:::note info` の囲み（B-3 / Qiita 記法）。

    **CommonMark ではない。** 他のエディタでは素のテキストに見えるが、
    ソースが真実（R1）なので何も失わない。Qiita へ貼る用途がある以上、
    向こうで正しく出ることのほうが価値が大きい。
    """

    def test_囲みになる(self) -> None:
        html = render(":::note info\nお知らせ\n:::\n")
        assert "<div" in html
        assert "お知らせ" in html

    def test_記号は出さない(self) -> None:
        assert ":::" not in render(":::note info\nお知らせ\n:::\n")

    @pytest.mark.parametrize("kind", ["info", "warn", "alert"])
    def test_種類がクラスに出る(self, kind: str) -> None:
        assert kind in render(f":::note {kind}\n本文\n:::\n")

    def test_種類を省くと情報扱い(self) -> None:
        assert "info" in render(":::note\n本文\n:::\n")

    def test_中の記法も効く(self) -> None:
        """段落として潰れない。`setMarkdown()` はここで改行ごと潰していた。"""
        html = render(":::note info\n**強調**と`コード`\n:::\n")
        assert "<strong>強調</strong>" in html
        assert "<code>コード</code>" in html

    def test_複数行が別の段落になる(self) -> None:
        html = render(":::note info\n一段落目\n\n二段落目\n:::\n")
        assert html.count("<p>") >= 2

    def test_閉じ忘れても本文は残る(self) -> None:
        """書きかけで書き出しても内容を失わない。"""
        assert "お知らせ" in render(":::note info\nお知らせ\n")

    def test_コードブロックの中は触らない(self) -> None:
        assert ":::note info" in render("```\n:::note info\n```\n")


class TestCodeFilename:
    """` ```js:index.js `（B-3 / Qiita 記法）。

    `setMarkdown()` は情報文字列ごと落としていて、言語もファイル名も
    残らなかった（ADR-0007）。
    """

    def test_ファイル名が出る(self) -> None:
        assert "index.js" in render("```js:index.js\nx = 1\n```\n")

    def test_言語のクラスは言語だけ(self) -> None:
        """`language-js:index.js` では色分けが効かない。"""
        html = render("```js:index.js\nx = 1\n```\n")
        assert 'class="language-js"' in html
        assert "language-js:index.js" not in html

    def test_中身はそのまま(self) -> None:
        assert "x = 1" in render("```js:index.js\nx = 1\n```\n")

    def test_ファイル名だけでも書ける(self) -> None:
        """`` ```:設定 `` のように言語を省く書き方。"""
        assert "設定" in render("```:設定\nx\n```\n")

    def test_ファイル名が無ければ今まで通り(self) -> None:
        html = render("```python\nx = 1\n```\n")
        assert 'class="language-python"' in html

    def test_ファイル名はエスケープする(self) -> None:
        assert "<script>" not in render("```js:<script>\nx\n```\n")

    def test_言語が無いフェンスも壊れない(self) -> None:
        assert "<pre><code>" in render("```\nx = 1\n```\n")


class TestFootnote:
    """脚注 `[^1]`（B-3 / Qiita 記法）。

    `setMarkdown()` は `<a href="注釈">` に化けさせていた（ADR-0007）。
    """

    def test_参照がリンクになる(self) -> None:
        html = render("本文[^1]\n\n[^1]: 注釈\n")
        assert "<a" in html
        assert "href=" in html

    def test_注釈の本文が出る(self) -> None:
        assert "注釈" in render("本文[^1]\n\n[^1]: 注釈\n")

    def test_行き先が文書内(self) -> None:
        """外部を指さない。`href="注釈"` のような誤変換をしない。"""
        assert 'href="注釈"' not in render("本文[^1]\n\n[^1]: 注釈\n")

    def test_定義が無ければただの文字(self) -> None:
        assert "[^1]" in render("本文[^1]\n")
