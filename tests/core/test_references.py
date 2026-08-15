"""本文が指している添付を数える（E-5）。

**取りこぼすと画像が消える。** ここは掃除の判断材料なので、
「参照を見落とす」ことが直接データの消失になる。だから**書き方を
数え上げない**。`attachments/` という文字列を含む断片をすべて拾い、
そこに現れたファイル名は使われているものとして扱う。

コードブロックの中も数える。タグやリンクと違い、ここは
「本当に使っているか」ではなく「**消しても安全か**」を判定している。
迷ったら残すのが正しい。
"""

from hitofude.core.references import attachment_names


class TestMarkdown:
    def test_画像(self) -> None:
        assert attachment_names("![](attachments/図.png)\n") == {"図.png"}

    def test_代替テキスト付きの画像(self) -> None:
        assert attachment_names("![説明](attachments/図.png)\n") == {"図.png"}

    def test_リンク(self) -> None:
        """添付は画像とは限らない（PDF を貼ることもある）。"""
        assert attachment_names("[資料](attachments/資料.pdf)\n") == {"資料.pdf"}

    def test_参照型リンク(self) -> None:
        text = "![図][a]\n\n[a]: attachments/図.png\n"
        assert attachment_names(text) == {"図.png"}

    def test_複数(self) -> None:
        text = "![](attachments/a.png)\n![](attachments/b.png)\n"
        assert attachment_names(text) == {"a.png", "b.png"}

    def test_同じものは1つ(self) -> None:
        text = "![](attachments/a.png)\n![](attachments/a.png)\n"
        assert attachment_names(text) == {"a.png"}


class TestOtherWritings:
    """**書き方を数え上げない。** 拾い漏らすと消えるので広く採る。"""

    def test_生のHTML(self) -> None:
        assert attachment_names('<img src="attachments/図.png">\n') == {"図.png"}

    def test_引用符が単一(self) -> None:
        assert attachment_names("<img src='attachments/図.png'>\n") == {"図.png"}

    def test_先頭のドット付き(self) -> None:
        assert attachment_names("![](./attachments/図.png)\n") == {"図.png"}

    def test_パーセント符号化(self) -> None:
        """空白や日本語は符号化されて書かれることがある。"""
        assert attachment_names("![](attachments/%E5%9B%B3.png)\n") == {"図.png"}

    def test_空白を含む名前(self) -> None:
        assert attachment_names("![](attachments/my%20file.png)\n") == {"my file.png"}

    def test_コードブロックの中も数える(self) -> None:
        """消してよいかの判定なので、**迷ったら残す**。"""
        assert attachment_names("```\n![](attachments/図.png)\n```\n") == {"図.png"}

    def test_ただの文として書かれていても数える(self) -> None:
        assert attachment_names("attachments/図.png を後で使う\n") == {"図.png"}

    def test_角括弧やクエリで切る(self) -> None:
        assert attachment_names("![](attachments/図.png)と[別](attachments/他.png)") == {
            "図.png",
            "他.png",
        }


class TestNotReferences:
    def test_添付以外のパスは数えない(self) -> None:
        assert attachment_names("![](images/図.png)\n") == set()

    def test_外のURLは数えない(self) -> None:
        assert attachment_names("![](https://example.com/図.png)\n") == set()

    def test_フォルダだけなら数えない(self) -> None:
        assert attachment_names("attachments/ に入ります\n") == set()

    def test_本文が空(self) -> None:
        assert attachment_names("") == set()

    def test_添付が出てこない(self) -> None:
        assert attachment_names("# 見出し\n\n本文\n") == set()


class TestSafety:
    def test_外へ出るパスは名前だけ見る(self) -> None:
        """`../` で外を指していても、**名前が一致すれば残す**。

        掃除の判定なので、変な書き方を「参照ではない」と切り捨てない。
        """
        assert attachment_names("![](attachments/../attachments/図.png)\n") == {"図.png"}

    def test_元の文字列を変えない(self) -> None:
        text = "![](attachments/図.png)\n"
        attachment_names(text)
        assert text == "![](attachments/図.png)\n"
