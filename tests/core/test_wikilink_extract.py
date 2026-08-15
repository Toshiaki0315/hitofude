"""本文から `[[ノート名]]` を集める（E-6 ②）。

索引の `links` テーブルに入れる元。**コードの中は数えない。**
`` ```[[a]]``` `` はリンクではなく、コード例としてそう書いたもの
（§6.5 規則 1「コード範囲内では他の記法を一切解釈しない」と同じ方針。
タグの `find_all` もこの形）。
"""

from hitofude.core.wikilink import links


class TestBasics:
    def test_見つかる(self) -> None:
        assert links("[[会議メモ]] を見て\n") == ["会議メモ"]

    def test_出現順(self) -> None:
        assert links("[[あ]]\n\n[[い]]\n") == ["あ", "い"]

    def test_重複は1つ(self) -> None:
        """同じノートを 3 回指しても、繋がりは 1 本。"""
        assert links("[[あ]] [[あ]]\n[[あ]]\n") == ["あ"]

    def test_名前は揃える(self) -> None:
        """`normalize()` を通す。索引の突き合わせがここで決まる。"""
        assert links("[[ 会議  メモ ]]\n") == ["会議 メモ"]

    def test_大小の違うものは別に数える(self) -> None:
        """解決は大小を無視するが、**集めるときは書いた通り**を残す。

        潰すと、どちらの綴りで書いたか分からなくなる。
        """
        assert links("[[ABC]] [[abc]]\n") == ["ABC", "abc"]

    def test_無ければ空(self) -> None:
        assert links("# 見出し\n\n本文\n") == []

    def test_空でも壊れない(self) -> None:
        assert links("") == []


class TestNotLinks:
    def test_コードフェンスの中(self) -> None:
        assert links("```\n[[会議メモ]]\n```\n") == []

    def test_言語付きのフェンスの中(self) -> None:
        assert links("```python\n[[会議メモ]]\n```\n") == []

    def test_インラインコードの中(self) -> None:
        assert links("`[[会議メモ]]` と書きます\n") == []

    def test_フェンスの外は数える(self) -> None:
        assert links("```\n[[中]]\n```\n\n[[外]]\n") == ["外"]

    def test_front_matterは見ない(self) -> None:
        """`id` や `created` はアプリの管理情報。リンクは書かれない。"""
        assert links("---\nid: ABC\nalias: '[[別名]]'\n---\n\n[[本文]]\n") == ["本文"]

    def test_ふつうのリンクは数えない(self) -> None:
        assert links("[題名](https://example.com)\n") == []

    def test_画像は数えない(self) -> None:
        assert links("![](attachments/図.png)\n") == []


class TestPure:
    def test_元の文字列を変えない(self) -> None:
        text = "[[会議メモ]]\n"
        links(text)
        assert text == "[[会議メモ]]\n"

    def test_同じ入力からは同じ結果(self) -> None:
        text = "[[あ]]\n```\n[[い]]\n```\n[[う]]\n"
        assert links(text) == links(text)
