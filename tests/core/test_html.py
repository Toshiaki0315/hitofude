"""Markdown → HTML（B-2）。

書き出しの土台。**`QTextDocument.setMarkdown()` をやめてここに移した**理由は、
あちらが記法を落とすため（実測値は ADR-0007）。落ちていたものを、ここで
落ちないことを確かめる。

`core/` にあるので PySide6 に依存しない（R3）。ヘッドレスで全部見られる。
"""

import re

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
        """色分け（B-6）で中身がタグに割られるので、タグを外して見る。"""
        html = render("```js:index.js\nx = 1\n```\n")
        assert "x = 1" in re.sub(r"<[^>]+>", "", html)

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


class TestUnknownNoteKind:
    """`:::note warm` のような綴り違い（ユーザー報告）。

    画面と同じ扱いにする。**片方だけ `info` に寄せると、画面では灰色なのに
    書き出しは青、という食い違いが起きる**（B-2 で作らないと決めたもの）。
    """

    def test_infoにはしない(self) -> None:
        assert "note-info" not in render(":::note warm\n本文\n:::\n")

    def test_別のクラスになる(self) -> None:
        assert "note-unknown" in render(":::note warm\n本文\n:::\n")

    def test_本文は残る(self) -> None:
        assert "本文" in render(":::note warm\n本文\n:::\n")

    def test_省略は情報扱いのまま(self) -> None:
        assert "note-info" in render(":::note\n本文\n:::\n")

    @pytest.mark.parametrize("line", [":::note warn extra", ":::note info さらに何か"])
    def test_語が2つ以上並んだら囲みにしない(self, line: str) -> None:
        """**画面側に揃える。** ここが食い違っていた（画面は囲みにせず、
        書き出しは先頭の語だけ見て warn にしていた）。"""
        html = render(f"{line}\n本文\n:::\n")
        assert "<div" not in html
        assert ":::note" in html


class TestMath:
    """数式 `$...$` / `$$...$$`（B-5）。

    **MathML にする。** JavaScript（KaTeX / MathJax）を同梱すると
    書き出した 1 ファイルごとに 1MB 以上増え、開くたびに走る。MathML なら
    今のブラウザがそのまま組んでくれて、`to_html` の「外部リソースを
    参照しない」も保てる（`latex2mathml` は 352KB・純 Python）。
    """

    def test_インラインの式が組まれる(self) -> None:
        assert "<math" in render("インライン $E = mc^2$ です\n")

    def test_独立した式が組まれる(self) -> None:
        assert "<math" in render("$$\n\\frac{a}{b}\n$$\n")

    def test_インラインと独立で表示が違う(self) -> None:
        """独立した式は中央に大きく出る。同じ扱いでは意味が変わる。"""
        assert 'display="inline"' in render("$E = mc^2$\n")
        assert 'display="block"' in render("$$\nE = mc^2\n$$\n")

    def test_記号は残さない(self) -> None:
        assert "$" not in render("$E = mc^2$\n")

    def test_構造になる(self) -> None:
        """`mc^2` の `2` が上付きとして組まれること。"""
        assert "<msup>" in render("$E = mc^2$\n")


class TestMathFalsePositives:
    """**数式でないものを数式にしない。** ここが緩いと、ふつうの文章が壊れる。"""

    def test_値段は数式にしない(self) -> None:
        """`$100 と $200` は日本語の文章として普通に出てくる。"""
        assert "<math" not in render("価格は $100 と $200 です。\n")

    def test_通貨記号が前後にあるだけなら数式にしない(self) -> None:
        assert "<math" not in render("定価 100$ から $200 まで\n")

    def test_記号の内側の空白は数式にしない(self) -> None:
        assert "<math" not in render("$ x $ 空白あり\n")

    def test_コードの中は数式にしない(self) -> None:
        assert "<math" not in render("`$x$` はコード\n")

    def test_コードブロックの中は数式にしない(self) -> None:
        assert "<math" not in render("```\n$x = 1$\n```\n")

    def test_数字を含む式は数式にする(self) -> None:
        """厳しくしすぎて本物を落とさないこと。"""
        assert "<math" in render("$1 + 1 = 2$\n")

    def test_値段が2つ並んでも数式にしない(self) -> None:
        """**ブラウザで見て見つけた取りこぼし。** 1 つ目の閉じ `$` と 2 つ目の
        開き `$` が組になり、**間の日本語ごと**数式になっていた
        （`200です。定価100` が式として組まれた）。"""
        assert "<math" not in render("価格は $100 と $200 です。定価 100$ から $200 まで。\n")

    def test_日本語を含む式は数式にしない(self) -> None:
        """数式に かな・漢字 は出てこない。入っていたら取り違えている。"""
        assert "<math" not in render("これは $日本語の文$ です\n")

    def test_日本語の文中の式は数式にする(self) -> None:
        """周りが日本語でも、式そのものに日本語が無ければ数式。"""
        assert "<math" in render("速度は $v = at$ で求まります\n")


class TestBrokenMath:
    """壊れた式で本文を失わない。"""

    def test_解釈できない式は文字として残す(self) -> None:
        html = render("$\\unknowncommand{x}$\n")
        assert "unknowncommand" in html

    def test_閉じ忘れは素のまま(self) -> None:
        assert "$E = mc^2" in render("$E = mc^2\n")


class TestMathForPdf:
    """PDF 向けの出し方（B-5）。

    **Qt のリッチテキストは MathML を解さない。** タグを捨てて中身の文字を
    つなぐだけなので、`$E = mc^2$` が `E=mc2` に、`\\frac{a}{b}` が `ab` に
    なる（実測）。**黙って間違った式**を出すくらいなら、書いたままの LaTeX を
    見せるほうがよい。
    """

    def test_元の記法のまま出す(self) -> None:
        html = render("$E = mc^2$\n", math_as_source=True)
        assert "$E = mc^2$" in html
        assert "<math" not in html

    def test_独立した式も記法のまま(self) -> None:
        html = render("$$\n\\frac{a}{b}\n$$\n", math_as_source=True)
        assert "\\frac{a}{b}" in html
        assert "<math" not in html

    def test_既定はMathML(self) -> None:
        assert "<math" in render("$E = mc^2$\n")

    def test_数式以外は変わらない(self) -> None:
        source = "# 見出し\n\n- [ ] やること\n"
        assert render(source, math_as_source=True) == render(source)


class TestCodeHighlight:
    """コードの色分け（B-6）。

    Pygments で**書き出す時点で色を焼き込む**。JavaScript は使わないので、
    ブラウザでも PDF でも同じに出る（Qt のリッチテキストは
    `<span style="color:...">` を解する。実測）。
    """

    def test_言語が分かれば色が付く(self) -> None:
        assert "color:" in render("```python\ndef f():\n    pass\n```\n")

    def test_予約語と文字列で色が違う(self) -> None:
        html = render('```python\ndef f():\n    return "文字列"\n```\n')
        colors = set(re.findall(r"color: ?(#[0-9A-Fa-f]{3,6})", html))
        assert len(colors) >= 2, colors

    def test_中身は変わらない(self) -> None:
        html = render("```python\nx = 1 + 2\n```\n")
        assert "x = 1 + 2" in re.sub(r"<[^>]+>", "", html)

    def test_言語のクラスは残す(self) -> None:
        """Mermaid（B-4）など、あとから拾う仕組みのために残す。"""
        assert 'class="language-python"' in render("```python\nx = 1\n```\n")

    def test_知らない言語は色を付けない(self) -> None:
        html = render("```なにか\nx = 1\n```\n")
        assert "color:" not in html
        assert "x = 1" in html

    def test_言語が無ければ色を付けない(self) -> None:
        assert "color:" not in render("```\nx = 1\n```\n")

    def test_ファイル名付きでも色が付く(self) -> None:
        html = render("```python:main.py\ndef f():\n    pass\n```\n")
        assert "color:" in html
        assert "main.py" in html

    def test_記号を壊さない(self) -> None:
        """`<` や `&` がそのまま出ると HTML が壊れる。"""
        html = render("```python\nif a < b & c:\n    pass\n```\n")
        assert "<b &" not in html
        assert "&lt;" in html or "&amp;" in html

    def test_暗い配色も選べる(self) -> None:
        """ダークテーマで書き出したときに、黒地に黒い字にならないこと。"""
        light = render("```python\ndef f():\n    pass\n```\n")
        dark = render("```python\ndef f():\n    pass\n```\n", dark=True)
        assert light != dark

    def test_数式と混ぜても壊れない(self) -> None:
        html = render("```python\nx = 1\n```\n\n$E = mc^2$\n")
        assert "color:" in html
        assert "<math" in html


class TestMermaid:
    """Mermaid の図（B-4）。

    **図にするのはブラウザ側の JavaScript。** Python に実装が無いので、
    書き出した HTML の中で描いてもらう（同梱するのは `editor/exporter.py`）。
    ここは「図として描く場所」を用意するところまで。
    """

    def test_図の置き場になる(self) -> None:
        assert '<pre class="mermaid">' in render("```mermaid\ngraph TD\n  A --> B\n```\n")

    def test_中身はそのまま渡す(self) -> None:
        """色分けなどの加工をしない。Mermaid が読むのは `textContent` なので、
        `-->` が `--&gt;` になっていてもブラウザが戻す。"""
        import html as html_module

        rendered = render("```mermaid\ngraph TD\n  A --> B\n```\n")
        assert "graph TD\n  A --> B" in html_module.unescape(rendered)

    def test_コードとしては出さない(self) -> None:
        """`<code>` に入れると Mermaid が拾わない。"""
        assert "<code" not in render("```mermaid\ngraph TD\n```\n")

    def test_記号はエスケープする(self) -> None:
        """`-->` の `>` がそのまま出ると HTML が壊れる。"""
        html = render("```mermaid\ngraph TD\n  A[<b>x</b>] --> B\n```\n")
        assert "<b>" not in html

    def test_色は付けない(self) -> None:
        """Pygments に通すと span だらけになって Mermaid が読めない。"""
        assert "color:" not in render("```mermaid\ngraph TD\n  A --> B\n```\n")

    def test_ファイル名付きでも図にする(self) -> None:
        html = render("```mermaid:流れ図\ngraph TD\n  A --> B\n```\n")
        assert '<pre class="mermaid">' in html
        assert "流れ図" in html

    def test_他の言語は今まで通り(self) -> None:
        assert '<pre class="mermaid">' not in render("```python\nx = 1\n```\n")
