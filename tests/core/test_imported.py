"""取り込んだ文字を Markdown に整える（F-1）。

PPTX と PDF の両方がここを通る。**ざっくり整えて手で直す**前提で、
元の見た目の再現は狙わない（TASKS.md の F 群）。

**NFKC 正規化は飾りではない。** 自分で書き出した PDF を読み戻すと
`本⽇`（U+2F47 KANGXI RADICAL SUN）が出てきて、**「本日」では検索に
掛からない**。取り込んだ瞬間に揃えないと、あとから気づけない。
"""

import pytest

from hitofude.core.imported import (
    is_page_number,
    looks_like_heading,
    normalize_text,
    to_markdown,
)


class TestNormalize:
    def test_互換文字を揃える(self) -> None:
        """PDF から出る `⽇`（部首の字）は「日」にしないと検索できない。"""
        assert normalize_text("本⽇の議題") == "本日の議題"

    def test_全角の英数字を半角にする(self) -> None:
        assert normalize_text("ＡＢＣ１２３") == "ABC123"

    def test_半角カナを全角にする(self) -> None:
        assert normalize_text("ﾊﾝｶｸ") == "ハンカク"

    def test_改行を揃える(self) -> None:
        assert normalize_text("あ\r\nい\rう") == "あ\nい\nう"

    def test_制御文字を落とす(self) -> None:
        """PDF には改ページ（`\\x0c`）や NUL が混ざる。"""
        assert normalize_text("あ\x0cい\x00う") == "あいう"

    def test_見えないハイフンを落とす(self) -> None:
        """欧文 PDF の行末に入る soft hyphen。残すと単語が割れる。"""
        assert normalize_text("hy­phen") == "hyphen"

    def test_連なる空白は1つに(self) -> None:
        assert normalize_text("あ    い") == "あ い"

    def test_行頭の空白を落とす(self) -> None:
        """**4 つ以上の空白はコードブロックになる。** 字下げを持ち込まない。"""
        assert normalize_text("    字下げ") == "字下げ"

    def test_日本語はそのまま(self) -> None:
        assert normalize_text("これは日本語です。") == "これは日本語です。"

    def test_空でも壊れない(self) -> None:
        assert normalize_text("") == ""


class TestPageNumber:
    @pytest.mark.parametrize("line", ["1", "12", "- 3 -", "— 4 —", "3 / 12", "P. 5", "6 ページ"])
    def test_ページ番号らしい(self, line: str) -> None:
        assert is_page_number(line) is True

    @pytest.mark.parametrize(
        "line", ["2026", "第 3 章", "3 つの理由", "1. はじめに", "本文", "", "12345"]
    )
    def test_ページ番号ではない(self, line: str) -> None:
        """**迷ったら残す。** 消しすぎると本文が減る。"""
        assert is_page_number(line) is False


class TestHeading:
    @pytest.mark.parametrize("line", ["まとめ", "第 1 章 はじめに", "Introduction"])
    def test_見出しらしい(self, line: str) -> None:
        assert looks_like_heading(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "これは文です。",
            "本日の議題は予算です",
            "- 箇条書き",
            "",
            "とても長い行はたとえ句点が無くても見出しには見えないので本文として扱う",
        ],
    )
    def test_見出しではない(self, line: str) -> None:
        assert looks_like_heading(line) is False


class TestToMarkdown:
    def test_題名が見出しになる(self) -> None:
        assert to_markdown(["本文"], title="講演資料").startswith("# 講演資料\n")

    def test_題名が無ければ付けない(self) -> None:
        assert not to_markdown(["これは本文です。"]).startswith("#")

    def test_ページの頭が中見出しになる(self) -> None:
        """スライドの PDF を想定。**`##` で 1 枚**（PPTX と同じ区切り）。"""
        out = to_markdown(["まとめ\n本文です。"], title="資料")
        assert "## まとめ" in out

    def test_見出しに見えなければ中見出しにしない(self) -> None:
        out = to_markdown(["これは本文です。続きます。"], title="資料")
        assert "##" not in out

    def test_ページ番号を落とす(self) -> None:
        assert "12" not in to_markdown(["本文です。\n12"])

    def test_日本語の行は詰めて繋ぐ(self) -> None:
        """PDF は行ごとに切れて出る。空白を挟むと文が割れて見える。"""
        out = to_markdown(["まとめ\n本日の議題は\n予算です。"])
        assert "本日の議題は予算です。" in out

    def test_英語の行は空白で繋ぐ(self) -> None:
        assert "hello world" in to_markdown(["Summary\nhello\nworld"])

    def test_空行で段落が分かれる(self) -> None:
        out = to_markdown(["見出し\n一つ目の段落。\n\n二つ目の段落。"])
        assert "一つ目の段落。\n\n二つ目の段落。" in out

    def test_箇条書きの記号を変換する(self) -> None:
        assert "- 項目" in to_markdown(["・項目"])

    @pytest.mark.parametrize("bullet", ["・", "•", "‣", "▪", "●", "-"])
    def test_いろいろな記号を箇条書きにする(self, bullet: str) -> None:
        assert to_markdown([f"{bullet} 項目"]).strip().endswith("- 項目")

    def test_箇条書きは繋がない(self) -> None:
        """行ごとに 1 項目。繋ぐと 1 つの長い項目になる。"""
        out = to_markdown(["・一つ目\n・二つ目"])
        assert "- 一つ目\n- 二つ目" in out

    def test_ページの区切りで段落も切れる(self) -> None:
        out = to_markdown(["一枚目の話。", "二枚目の話。"])
        assert "一枚目の話。\n\n二枚目の話。" in out

    def test_空のページは飛ばす(self) -> None:
        assert to_markdown(["本文", "", "  "]).strip().endswith("本文")

    def test_末尾は改行で終わる(self) -> None:
        assert to_markdown(["本文"], title="資料").endswith("\n")

    def test_ページが無くても壊れない(self) -> None:
        assert to_markdown([], title="空") == "# 空\n"

    def test_元のリストを変えない(self) -> None:
        pages = ["本文"]
        to_markdown(pages)
        assert pages == ["本文"]


class TestRealShape:
    """実物の PDF から取り出した形（空行が無く、折り返しだけがある）。

    自分で書き出した PDF を `QPdfDocument.getAllText()` で読み戻すと
    こう出てくる。**空行が 1 つも無い**ので、素直に繋ぐと 1 ページが
    1 段落に潰れる（最初の実装がそうなった）。
    """

    PAGE = "\n".join(
        [
            "四半期の振り返り",
            "売上",
            "本日の議題は 予算 です。数字は前年より伸びていますが、 下期",
            "の見通しは慎重に見ています。",
            "新規の契約が 12 件",
            "解約は 3 件にとどまった",
            "1",
        ]
    )

    def test_ページの題が中見出しになる(self) -> None:
        assert "## 四半期の振り返り" in to_markdown([self.PAGE], title="資料")

    def test_折り返した行は繋ぎ直す(self) -> None:
        """端まで伸びていて句点が無い行は、次の行と 1 文になっている。"""
        assert "下期の見通しは慎重に見ています。" in to_markdown([self.PAGE])

    def test_短い行は独立させる(self) -> None:
        """**繋ぐと「売上本日の議題は…」になる。** 短さが唯一の手がかり。"""
        assert "\n\n売上\n\n" in to_markdown([self.PAGE])

    def test_項目が混ざらない(self) -> None:
        out = to_markdown([self.PAGE])
        assert "\n\n新規の契約が 12 件\n\n" in out
        assert "解約は 3 件にとどまった" in out

    def test_ページ番号は残らない(self) -> None:
        assert not to_markdown([self.PAGE]).rstrip().endswith("1")


class TestRadicals:
    """部首の字を、ふつうの漢字に直す（F-2 で見つかった）。

    自分で書き出した PDF を読み戻すと `⻑い資料` になっていた。**NFKC では
    直らない。** 部首には 2 つのブロックがあり、康熙部首（U+2F00〜）は
    NFKC が面倒を見るが、CJK 部首補助（U+2E80〜）は **115 字のうち 113 字が
    素通りする**（実測）。素通りすると「長い」で検索できない。

    対応は Unicode の**字の名前から導く**（`CJK RADICAL LONG ONE` →
    `KANGXI RADICAL LONG` → NFKC → 長）。表を手で持たないので写し間違いが
    起きない。名前から導けない日本の新字体だけ、明示の表に置く。
    """

    @pytest.mark.parametrize(
        ("radical", "expected"),
        [("⻑", "長"), ("⻤", "鬼"), ("⺼", "肉"), ("⻂", "衣"), ("⻍", "辵")],
    )
    def test_名前から導ける部首(self, radical: str, expected: str) -> None:
        assert normalize_text(radical) == expected

    @pytest.mark.parametrize(
        ("radical", "expected"), [("⻭", "歯"), ("⻯", "竜"), ("⻲", "亀"), ("⻫", "斉")]
    )
    def test_日本の新字体(self, radical: str, expected: str) -> None:
        """`J-SIMPLIFIED` は名前が対応しないので表に持つ。"""
        assert normalize_text(radical) == expected

    def test_康熙部首は今まで通り(self) -> None:
        assert normalize_text("⽇") == "日"

    def test_文の中でも直る(self) -> None:
        assert normalize_text("⻑い資料の⻭車") == "長い資料の歯車"

    def test_ふつうの漢字は変わらない(self) -> None:
        assert normalize_text("長い資料の歯車") == "長い資料の歯車"
