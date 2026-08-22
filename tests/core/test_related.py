"""関連するノートを並べる（L-3）。

**LLM に選ばせない。** 関係の根拠は既に索引の中にある（同じタグ・
`[[…]]` の指し合い・題名の語）。モデルに選ばせると、**なぜ関係するのか
確かめられない**うえ、待たされ、Ollama が無い人には何も出ない。

ここは並べ方だけを決める純関数。**何を信号とするかは呼ぶ側**（索引を
引くのは `storage/`）。
"""

from hitofude.core.related import LINK, SHARED_TAG, TEXT, Signal, rank


def signal(key: str, reason: str = "同じタグ #仕事", weight: int = SHARED_TAG) -> Signal:
    return Signal(key=key, reason=reason, weight=weight)


class TestRank:
    def test_信号のあるノートが並ぶ(self) -> None:
        found = rank([signal("仕事/会議.md")], exclude="今.md")
        assert [item.key for item in found] == ["仕事/会議.md"]

    def test_自分は出さない(self) -> None:
        """**自分に関係するノートは自分ではない。**"""
        assert rank([signal("今.md")], exclude="今.md") == []

    def test_強い信号が上に来る(self) -> None:
        found = rank(
            [
                signal("語だけ.md", "題名の語が出てくる", TEXT),
                signal("指している.md", "このノートを指している", LINK),
            ],
            exclude="今.md",
        )
        assert [item.key for item in found] == ["指している.md", "語だけ.md"]

    def test_信号が重なるほど上に来る(self) -> None:
        """タグも語も一致するノートは、片方だけのノートより関係が濃い。"""
        found = rank(
            [
                signal("片方.md", "同じタグ #仕事", SHARED_TAG),
                signal("両方.md", "同じタグ #仕事", SHARED_TAG),
                signal("両方.md", "題名の語が出てくる", TEXT),
            ],
            exclude="今.md",
        )
        assert [item.key for item in found] == ["両方.md", "片方.md"]

    def test_理由をまとめて持つ(self) -> None:
        """**なぜ出たのかを画面に出す。** 出ない理由は探せない。"""
        found = rank(
            [
                signal("両方.md", "同じタグ #仕事", SHARED_TAG),
                signal("両方.md", "題名の語が出てくる", TEXT),
            ],
            exclude="今.md",
        )
        assert found[0].reasons == ("同じタグ #仕事", "題名の語が出てくる")

    def test_同じ理由は重ねない(self) -> None:
        found = rank(
            [signal("両方.md", "同じタグ #仕事"), signal("両方.md", "同じタグ #仕事")],
            exclude="今.md",
        )
        assert found[0].reasons == ("同じタグ #仕事",)

    def test_数を絞れる(self) -> None:
        """**画面に入らない数を出さない。** 上から数件で足りる。"""
        found = rank([signal(f"{n}.md") for n in range(20)], exclude="今.md", limit=5)
        assert len(found) == 5

    def test_信号が無ければ空(self) -> None:
        assert rank([], exclude="今.md") == []


class TestOrderIsStable:
    """同じ強さなら、渡された順のまま（索引は更新順で返す）。"""

    def test_同点は渡された順(self) -> None:
        found = rank([signal("先.md"), signal("後.md")], exclude="今.md")
        assert [item.key for item in found] == ["先.md", "後.md"]
