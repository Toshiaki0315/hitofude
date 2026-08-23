"""リンクの図（M-2 / 仮身ネットワーク）。

BTRON の「あるファイルを起点としたリンク構造」を写したもの。
**ここは Qt も索引も知らない**（R3）——題名と行き先の対応を渡すだけ。

**絞り方は記事が持っていた**（何段階先まで表示するか）。点の数の 2 乗で
効くので（実測: 200 点 359ms / 1,000 点 9.2 秒）、絞らないと開けない。
"""

import pytest

from hitofude.core import graph

# 会議メモ → 買い物リスト → 卵の店
#   ↑ 日報が会議メモを指す。買い物リストは「まだ無いノート」も指す
LINKS = {
    "会議メモ": ["買い物リスト"],
    "買い物リスト": ["卵の店", "まだ無いノート"],
    "卵の店": [],
    "日報": ["会議メモ"],
    "無関係なノート": [],
}


def names(found: graph.Graph) -> set[str]:
    return {node.title for node in found.nodes}


def depth_of(found: graph.Graph, title: str) -> int:
    return next(node.depth for node in found.nodes if node.title == title)


class TestStart:
    def test_起点だけの図もできる(self) -> None:
        found = graph.build("無関係なノート", LINKS)
        assert names(found) == {"無関係なノート"}
        assert found.edges == []

    def test_起点は深さ_0(self) -> None:
        assert depth_of(graph.build("会議メモ", LINKS), "会議メモ") == 0

    def test_知らない題名でも図はできる(self) -> None:
        """**まだ無いノートを開いていることがある**（`[[…]]` から作る前）。"""
        found = graph.build("まだ無いノート", LINKS, depth=1)
        assert names(found) == {"まだ無いノート", "買い物リスト"}


class TestFollow:
    def test_出ていくリンクを辿る(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=1)
        assert "買い物リスト" in names(found)

    def test_指されているリンクも辿る(self) -> None:
        """**バックリンクも関係**。片方向だけだと「誰が参照しているか」が消える。"""
        found = graph.build("会議メモ", LINKS, depth=1)
        assert "日報" in names(found)

    def test_深さで止まる(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=1)
        assert "卵の店" not in names(found)

    def test_深さを増やせば届く(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=2)
        assert depth_of(found, "卵の店") == 2

    def test_関係の無いノートは入らない(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=3)
        assert "無関係なノート" not in names(found)


class TestMissingTargets:
    def test_行き先の無いリンクも点になる(self) -> None:
        """`[[まだ無いノート]]` は索引に行として残る。**見せないと繋がりが切れて見える。**"""
        found = graph.build("買い物リスト", LINKS, depth=1)
        assert "まだ無いノート" in names(found)

    def test_あるものと無いものを見分けられる(self) -> None:
        found = graph.build("買い物リスト", LINKS, depth=1)
        marks = {node.title: node.exists for node in found.nodes}
        assert marks["卵の店"] is True
        assert marks["まだ無いノート"] is False


class TestMatching:
    def test_違う題名は別の点(self) -> None:
        """**勝手に寄せない。** 似ているだけの題名を繋ぐと、無い関係が生まれる。"""
        found = graph.build("かいぎメモ", LINKS, depth=1)
        assert "買い物リスト" not in names(found)

    def test_大文字小文字は同じものとして扱う(self) -> None:
        """`resolve` が casefold で照合する（E-6）ので、図もそれに揃える。"""
        links = {"Meeting": ["Notes"], "Notes": []}
        found = graph.build("meeting", links, depth=1)
        assert "Notes" in names(found)

    def test_前後の空白は無視する(self) -> None:
        """E-6 の「前後の空白は気にしなくて大丈夫」と揃える。"""
        links = {"会議メモ": ["買い物リスト"], "買い物リスト": []}
        found = graph.build("会議メモ", {**links, "日報": ["  会議メモ  "]}, depth=1)
        assert "日報" in names(found)

    def test_起点の書き方が揺れても届く(self) -> None:
        found = graph.build("会議メモ ", LINKS, depth=1)
        assert "買い物リスト" in names(found)


class TestLoops:
    def test_自分を指しても点は増えない(self) -> None:
        found = graph.build("ひとりごと", {"ひとりごと": ["ひとりごと"]}, depth=2)
        assert names(found) == {"ひとりごと"}

    def test_輪になっていても止まる(self) -> None:
        links = {"あ": ["い"], "い": ["う"], "う": ["あ"]}
        found = graph.build("あ", links, depth=5)
        assert names(found) == {"あ", "い", "う"}

    def test_同じ線を二重に持たない(self) -> None:
        links = {"あ": ["い", "い"], "い": []}
        found = graph.build("あ", links, depth=1)
        assert len(found.edges) == 1


class TestEdges:
    def test_線は点の番号で持つ(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=1)
        for source, target in found.edges:
            assert 0 <= source < len(found.nodes)
            assert 0 <= target < len(found.nodes)

    def test_向きを保つ(self) -> None:
        """**どちらが指しているか**は関係の意味そのもの。"""
        found = graph.build("会議メモ", LINKS, depth=1)
        titles = [node.title for node in found.nodes]
        pairs = {(titles[a], titles[b]) for a, b in found.edges}
        assert ("会議メモ", "買い物リスト") in pairs
        assert ("日報", "会議メモ") in pairs

    def test_落とした点の線は残さない(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=1)
        titles = [node.title for node in found.nodes]
        assert "卵の店" not in titles


class TestLimit:
    def _wide(self, count: int) -> dict[str, list[str]]:
        return {"中心": [f"子{i}" for i in range(count)], **{f"子{i}": [] for i in range(count)}}

    def test_上限を超えたら落とす(self) -> None:
        found = graph.build("中心", self._wide(300), depth=1, limit=50)
        assert len(found.nodes) == 50

    def test_落とした数を伝える(self) -> None:
        """**黙って減らさない。** 減ったことが分からないと図を信じてしまう。"""
        found = graph.build("中心", self._wide(300), depth=1, limit=50)
        assert found.dropped == 301 - 50

    def test_起点は落とさない(self) -> None:
        found = graph.build("中心", self._wide(300), depth=1, limit=1)
        assert names(found) == {"中心"}

    def test_近いものから残す(self) -> None:
        links = {"中心": ["近い"], "近い": [f"遠い{i}" for i in range(50)]}
        links.update({f"遠い{i}": [] for i in range(50)})
        found = graph.build("中心", links, depth=2, limit=3)
        assert {"中心", "近い"} <= names(found)

    def test_落としていなければ_0(self) -> None:
        assert graph.build("会議メモ", LINKS, depth=2).dropped == 0


# **同じ点に複数から入ってくる形**でないと、並べ替えの有無が現れない
# （最初に書いた検査は素通りした——実装の並べ替えを外しても緑だった）
MANY = {
    "中心": [],
    "あ": ["中心"],
    "い": ["中心"],
    "う": ["中心"],
    "え": ["中心"],
}


class TestDeterministic:
    def test_同じ入力なら同じ図(self) -> None:
        """図を開くたびに形が変わると、見比べられない。"""
        first = graph.build("会議メモ", LINKS, depth=3)
        second = graph.build("会議メモ", LINKS, depth=3)
        assert [node.title for node in first.nodes] == [node.title for node in second.nodes]
        assert first.edges == second.edges

    @pytest.mark.parametrize(
        "links",
        [
            LINKS,
            MANY,
            {**MANY, "中心": ["か", "き", "く"], "か": [], "き": [], "く": []},
        ],
    )
    def test_渡す順が違っても同じ図(self, links: dict) -> None:
        """**図を開くたびに点の並びが変わらない。** 上限で切るときにも効く。"""
        start = "会議メモ" if links is LINKS else "中心"
        shuffled = dict(reversed(list(links.items())))
        first = graph.build(start, links, depth=3)
        second = graph.build(start, shuffled, depth=3)
        assert [node.title for node in first.nodes] == [node.title for node in second.nodes]
        assert first.edges == second.edges

    def test_渡す順が違っても同じものが残る(self) -> None:
        """上限で切る位置がずれると、**別のノートが消える**。"""
        links = {"中心": [], **{f"子{i}": ["中心"] for i in range(20)}}
        shuffled = dict(reversed(list(links.items())))
        first = graph.build("中心", links, depth=1, limit=5)
        second = graph.build("中心", shuffled, depth=1, limit=5)
        assert [node.title for node in first.nodes] == [node.title for node in second.nodes]


class TestLayout:
    def test_全部の点に場所がつく(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=3)
        assert len(graph.layout(found)) == len(found.nodes)

    def test_枠に収まる(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=3)
        for x, y in graph.layout(found):
            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0

    def test_同じ図なら同じ場所(self) -> None:
        """**乱数を使わない。** 開くたびに動くと、前に見た形と比べられない。"""
        found = graph.build("会議メモ", LINKS, depth=3)
        assert graph.layout(found) == graph.layout(found)

    def test_点が重ならない(self) -> None:
        found = graph.build("会議メモ", LINKS, depth=3)
        places = graph.layout(found)
        assert len(set(places)) == len(places)

    def test_点が_1_つでも落ちない(self) -> None:
        found = graph.build("無関係なノート", LINKS)
        assert len(graph.layout(found)) == 1

    def test_繋がっているほうが近い(self) -> None:
        """力学モデルが効いていること。**離れていたら図として読めない。**"""
        links = {"あ": ["い"], "い": [], "遠1": ["遠2"], "遠2": []}
        found = graph.build("あ", {**links, "い": ["遠1"]}, depth=3)
        places = dict(zip([n.title for n in found.nodes], graph.layout(found), strict=True))

        def distance(one: str, other: str) -> float:
            (x1, y1), (x2, y2) = places[one], places[other]
            return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

        assert distance("あ", "い") < distance("あ", "遠2")
