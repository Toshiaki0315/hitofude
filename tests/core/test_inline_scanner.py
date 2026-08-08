"""インラインスキャナのテスト（タスク 1-4〜1-8 / spec §6.5, ADR-0001）。

`scan()` は **1 行**を受け取り `list[InlineSpan]` を返す純関数。
`highlightBlock()` から毎キー入力ごとに呼ばれるため、挙動をここで固定する。
"""

import pytest

from hitofude.core.inline_scanner import image_only_line, scan
from hitofude.core.models import InlineSpan, SpanType


def types(text: str) -> list[SpanType]:
    return [span.type for span in scan(text)]


def only(text: str) -> InlineSpan:
    spans = scan(text)
    assert len(spans) == 1, f"1 個のはずが {len(spans)} 個: {spans}"
    return spans[0]


def content(text: str, span: InlineSpan) -> str:
    return text[span.content_start : span.content_end]


class TestCode:
    def test_インラインコードを確定する(self) -> None:
        text = "a `code` b"
        span = only(text)
        assert span.type is SpanType.CODE
        assert content(text, span) == "code"
        assert (span.start, span.end) == (2, 8)

    def test_コードの中では他の記法を解釈しない(self) -> None:
        """spec §6.5 規則 1: コード範囲内では他の記法を一切解釈しない。"""
        assert types("`**not bold**`") == [SpanType.CODE]
        assert types("`#nottag`") == [SpanType.CODE]
        assert types("`[a](b)`") == [SpanType.CODE]

    def test_二重バッククォートで内側のバッククォートを囲める(self) -> None:
        text = "``a ` b``"
        span = only(text)
        assert span.type is SpanType.CODE
        assert content(text, span) == "a ` b"

    def test_閉じないバッククォートは無視する(self) -> None:
        assert scan("`unclosed") == []


class TestImageAndLink:
    def test_リンクは本文とURLの2つに分かれる(self) -> None:
        text = "[Qt](https://doc.qt.io/)"
        spans = scan(text)
        assert [s.type for s in spans] == [SpanType.LINK_TEXT, SpanType.LINK_URL]
        assert content(text, spans[0]) == "Qt"
        assert content(text, spans[1]) == "https://doc.qt.io/"

    def test_リンクのURLはpayloadにも入る(self) -> None:
        spans = scan("[Qt](https://doc.qt.io/)")
        assert all(s.payload == "https://doc.qt.io/" for s in spans)

    def test_リンク内のURLを裸のURLとして重複検出しない(self) -> None:
        """ADR-0001: リンクを裸の URL より先に確定する。

        逆順（spec §6.5 の原文）だと URL が先にマスクされ、リンクが成立しない。
        """
        spans = scan("[Qt](https://doc.qt.io/)")
        assert SpanType.AUTOLINK not in [s.type for s in spans]
        assert len(spans) == 2

    def test_画像はリンクと区別される(self) -> None:
        text = "![図](img.png)"
        spans = scan(text)
        assert [s.type for s in spans] == [SpanType.IMAGE, SpanType.LINK_URL]
        assert content(text, spans[0]) == "図"

    def test_画像の開きマーカーは2文字(self) -> None:
        (image, _url) = scan("![図](img.png)")
        assert image.open_len == 2  # '!['

    def test_リンク本文の中の強調は生きる(self) -> None:
        assert SpanType.STRONG in types("[**強調**つき](x.md)")

    def test_空のリンク本文を許容する(self) -> None:
        assert [s.type for s in scan("[](x.md)")] == [SpanType.LINK_TEXT, SpanType.LINK_URL]


class TestAutolink:
    def test_山括弧の自動リンク(self) -> None:
        text = "<https://example.com>"
        span = only(text)
        assert span.type is SpanType.AUTOLINK
        assert content(text, span) == "https://example.com"
        assert span.open_len == 1

    def test_裸のURL(self) -> None:
        text = "詳細は https://example.com/a を見て"
        span = only(text)
        assert span.type is SpanType.AUTOLINK
        assert text[span.start : span.end] == "https://example.com/a"

    def test_裸のURLにはマーカーが無い(self) -> None:
        span = only("https://example.com")
        assert span.open_len == 0
        assert span.close_len == 0

    def test_コード内のURLは拾わない(self) -> None:
        assert types("`https://example.com`") == [SpanType.CODE]


class TestEmphasis:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("**bold**", SpanType.STRONG),
            ("*em*", SpanType.EM),
            ("***both***", SpanType.STRONG_EM),
            ("__bold__", SpanType.STRONG),
            ("_em_", SpanType.EM),
            ("___both___", SpanType.STRONG_EM),
            ("~~del~~", SpanType.STRIKE),
            ("::hl::", SpanType.HIGHLIGHT),
        ],
    )
    def test_デリミタごとの種別(self, text: str, expected: SpanType) -> None:
        assert only(text).type is expected

    def test_マーカーの内側だけが内容(self) -> None:
        text = "**bold**"
        span = only(text)
        assert content(text, span) == "bold"
        assert span.open_len == 2
        assert span.close_len == 2


class TestJapaneseEmphasis:
    """spec §11 R4 / §6.5 規則 4: 日本語は前後が空白にならない。"""

    def test_前後が空白でなくても強調になる(self) -> None:
        text = "これは**強調**です"
        span = only(text)
        assert span.type is SpanType.STRONG
        assert content(text, span) == "強調"

    def test_全角括弧に隣接しても強調になる(self) -> None:
        """CommonMark の flanking 規則だと、句読点隣接で開きと認められず落ちる。"""
        assert only("「**強調**」").type is SpanType.STRONG

    def test_句点の直前でも強調になる(self) -> None:
        assert only("**強調**。").type is SpanType.STRONG

    def test_斜体も同様(self) -> None:
        assert only("これは*斜体*です").type is SpanType.EM


class TestUnderscoreKeepsSnakeCase:
    """`_` は緩めない。緩めると識別子が壊れる（spec §6.5 規則 4）。"""

    @pytest.mark.parametrize("text", ["foo_bar_baz", "SOME_CONST_NAME", "a_b_c_d"])
    def test_単語内のアンダースコアは強調にならない(self, text: str) -> None:
        assert scan(text) == []

    def test_単語の外なら強調になる(self) -> None:
        assert only("これは _em_ です").type is SpanType.EM


class TestUnclosed:
    @pytest.mark.parametrize(
        "text",
        ["**未閉じ", "*未閉じ", "~~未閉じ", "::未閉じ", "abc**", "[未閉じ](", "![alt]("],
    )
    def test_閉じていないマーカーは無視する(self, text: str) -> None:
        assert scan(text) == []

    def test_空白の直後は開きにならない(self) -> None:
        assert scan("a ** b ** c") == []


class TestTag:
    def test_タグを確定する(self) -> None:
        text = "本文 #work/会議 の続き"
        span = only(text)
        assert span.type is SpanType.TAG
        assert span.payload == "work/会議"
        assert text[span.start : span.end] == "#work/会議"

    def test_タグにはマーカーが無い(self) -> None:
        """spec §6.4: `#` を含めて隠さない（ピル表示の一部）。"""
        span = only("#work")
        assert span.open_len == 0
        assert span.close_len == 0

    def test_見出しはタグにしない(self) -> None:
        assert scan("# 見出し") == []
        assert scan("## 見出し") == []


class TestNesting:
    def test_強調の中の斜体を拾う(self) -> None:
        text = "**bold *em* here**"
        spans = scan(text)
        assert [s.type for s in spans] == [SpanType.STRONG, SpanType.EM]
        assert content(text, spans[0]) == "bold *em* here"
        assert content(text, spans[1]) == "em"

    def test_斜体の中の強調を拾う(self) -> None:
        assert types("*em **bold** here*") == [SpanType.EM, SpanType.STRONG]

    def test_強調の中のコードを拾う(self) -> None:
        # 返り値は開始位置の昇順。STRONG が 0、CODE が 7 から始まる
        assert types("**bold `code` here**") == [SpanType.STRONG, SpanType.CODE]

    def test_コードの中の強調は拾わない(self) -> None:
        assert types("`code **bold** here`") == [SpanType.CODE]


class TestOrdering:
    def test_出現位置の昇順で返る(self) -> None:
        spans = scan("*a* `b` #c")
        starts = [s.start for s in spans]
        assert starts == sorted(starts)

    def test_同じ位置なら外側が先(self) -> None:
        """ハイライタが外側から順に setFormat() できるようにする。"""
        spans = scan("***x***")
        assert spans[0].type is SpanType.STRONG_EM


class TestEdgeCases:
    def test_空行(self) -> None:
        assert scan("") == []

    def test_装飾の無い行(self) -> None:
        assert scan("ただの日本語の文章です。") == []

    def test_全てのオフセットが行の長さに収まる(self) -> None:
        text = "**a** `b` [c](d) <https://e.f> #g ~~h~~ ::i::"
        for span in scan(text):
            assert 0 <= span.start <= span.end <= len(text)

    def test_スパン同士はネストか排他のどちらかになる(self) -> None:
        """部分的に重なる（交差する）スパンが出るとハイライトが破綻する。"""
        spans = scan("**a *b* c** `d` [e](f) #g")
        for i, outer in enumerate(spans):
            for inner in spans[i + 1 :]:
                crossing = outer.start < inner.start < outer.end < inner.end
                assert not crossing, f"{outer} と {inner} が交差している"


class TestImageOnlyLine:
    """行まるごとが画像 1 つのときだけ、本文中に絵として描く（タスク A-2 後半）。

    段落の途中にある画像は対象にしない。行の途中に高さを作るのは別の
    難しさで、実用上ほぼ「1 行 1 画像」のため。
    """

    def test_画像だけの行はURLを返す(self) -> None:
        assert image_only_line("![](attachments/写真.png)") == "attachments/写真.png"

    def test_代替テキストがあってもよい(self) -> None:
        assert image_only_line("![図](a.png)") == "a.png"

    def test_前後の空白は無視する(self) -> None:
        assert image_only_line("  ![](a.png)  ") == "a.png"

    def test_文の途中の画像は対象にしない(self) -> None:
        assert image_only_line("これは ![](a.png) です") is None

    def test_2枚並んでいたら対象にしない(self) -> None:
        assert image_only_line("![](a.png)![](b.png)") is None

    def test_ただのリンクは対象にしない(self) -> None:
        assert image_only_line("[文字](a.png)") is None

    def test_空行はNone(self) -> None:
        assert image_only_line("") is None

    def test_URLが空ならNone(self) -> None:
        """描くものが無い。"""
        assert image_only_line("![]()") is None

    def test_箇条書きの中は対象にしない(self) -> None:
        """行頭マーカーは意味を持つ（§6.4）。潰すと箇条書きが消える。"""
        assert image_only_line("- ![](a.png)") is None

    def test_絶対URLも返す(self) -> None:
        """描けるかは呼び出し側が決める。ここは形だけ見る。"""
        assert image_only_line("![](https://example.com/a.png)") == "https://example.com/a.png"
