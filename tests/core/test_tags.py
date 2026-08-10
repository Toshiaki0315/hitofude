"""タグ抽出のテスト（タスク 1-3 / spec §6.5 規則 7, §7.2, §7.3）。

`#` は見出しマーカーでもあるため、区別の条件を厳密に固定する。
"""

import pytest

from hitofude.core.tags import (
    ancestors,
    extract,
    find_all,
    leaf,
    matches,
    normalize,
    parent,
    prefix_at,
)


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("work", "work"),
            ("Work", "work"),  # spec §7.3: 小文字フルパスへ正規化
            ("WORK/会議", "work/会議"),
            ("work//会議", "work/会議"),  # 余分な区切りを畳む
            ("/work/", "work"),
            ("会議", "会議"),  # 日本語は変化しない
        ],
    )
    def test_正規化(self, raw: str, expected: str) -> None:
        assert normalize(raw) == expected


class TestFindAll:
    def test_行頭のタグを拾う(self) -> None:
        matches = find_all("#work\n")
        assert [m.name for m in matches] == ["work"]

    def test_空白のあとのタグを拾う(self) -> None:
        matches = find_all("本文の途中に #work と書く")
        assert [m.name for m in matches] == ["work"]

    def test_位置は半開区間で返る(self) -> None:
        text = "abc #work def"
        (match,) = find_all(text)
        assert (match.start, match.end) == (4, 9)
        assert text[match.start : match.end] == "#work"

    def test_原文と正規化後の両方を持つ(self) -> None:
        (match,) = find_all("#Work/会議")
        assert match.raw == "Work/会議"
        assert match.name == "work/会議"

    @pytest.mark.parametrize(
        "text",
        [
            "# 見出し",  # `#` の直後が空白 → 見出し
            "## 見出し",  # 連続する `#` もタグではない
            "###",
            "#",
            "# ",
        ],
    )
    def test_見出しをタグと誤認しない(self, text: str) -> None:
        assert find_all(text) == []

    def test_非空白の直後はタグにしない(self) -> None:
        """spec §6.5 規則 7: `#` の直前は行頭または空白であること。

        日本語は分かち書きしないため `本文#tag` と書きたくなるが、
        v1 では拾わない。URL の `https://x.com/#anchor` を誤検出しないため。
        """
        assert find_all("本文#tag") == []
        assert find_all("https://example.com/#anchor") == []

    def test_階層タグを拾う(self) -> None:
        (match,) = find_all("#work/会議")
        assert match.name == "work/会議"

    def test_複数行から出現順に拾う(self) -> None:
        text = "#first\n\n本文 #second\n\n#third\n"
        assert [m.name for m in find_all(text)] == ["first", "second", "third"]

    def test_コードフェンスの中は無視する(self) -> None:
        """`#include` や `# comment` がタグツリーを汚さないようにする。"""
        text = "#real\n\n```c\n#include <stdio.h>\n#define X 1\n```\n\n#also_real\n"
        assert [m.name for m in find_all(text)] == ["real", "also_real"]

    def test_チルダのコードフェンスも同様(self) -> None:
        text = "~~~\n#notatag\n~~~\n#real\n"
        assert [m.name for m in find_all(text)] == ["real"]

    def test_インラインコードの中は無視する(self) -> None:
        text = "`#notatag` と #real"
        assert [m.name for m in find_all(text)] == ["real"]

    def test_インラインコードの直後はタグにしない(self) -> None:
        """マスクしても「直前が非空白」という条件が保たれること。"""
        assert find_all("`code`#tag") == []


class TestExtract:
    def test_正規化して重複を除き出現順に返す(self) -> None:
        text = "#Work やること\n\n#work もう一度\n\n#private\n"
        assert extract(text) == ["work", "private"]

    def test_タグが無ければ空(self) -> None:
        assert extract("# 見出しだけ\n\n本文。\n") == []


class TestHierarchy:
    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ("work", ["work"]),
            ("work/会議", ["work", "work/会議"]),
            ("a/b/c", ["a", "a/b", "a/b/c"]),
        ],
    )
    def test_ancestorsは自身を含む祖先を浅い順に返す(self, tag: str, expected: list[str]) -> None:
        """サイドバーのタグツリー（§5.1）を組むのに使う。"""
        assert ancestors(tag) == expected

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ("work", None),
            ("work/会議", "work"),
            ("a/b/c", "a/b"),
        ],
    )
    def test_parent(self, tag: str, expected: str | None) -> None:
        assert parent(tag) == expected

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ("work", "work"),
            ("work/会議", "会議"),
            ("a/b/c", "c"),
        ],
    )
    def test_leafは末端の名前を返す(self, tag: str, expected: str) -> None:
        assert leaf(tag) == expected


class TestPrefixAt:
    """入力中のタグを見つける（C-4 / タグ補完）。

    綴りを覚えていないと `#日報` と `#日報メモ` のような揺れが起きる。
    打ち始めたところで候補を出す。
    """

    def test_打ちかけのタグを返す(self) -> None:
        assert prefix_at("メモ #日報", 6) == "日報"

    def test_記号だけでも返す(self) -> None:
        """`#` を打った時点で候補を全部見せたい。"""
        assert prefix_at("メモ #", 4) == ""

    def test_行頭でも返す(self) -> None:
        assert prefix_at("#日報", 3) == "日報"

    def test_タグの外ではNone(self) -> None:
        assert prefix_at("ただの文章", 5) is None

    def test_語の途中の記号は拾わない(self) -> None:
        """URL の `#anchor` をタグと誤認しない（`TAG_RE` と同じ約束）。"""
        assert prefix_at("http://x/a#b", 12) is None

    def test_空白をまたがない(self) -> None:
        assert prefix_at("#日報 のメモ", 8) is None

    def test_カーソルより後ろは見ない(self) -> None:
        """`#日報` の途中にカーソルがあるとき、候補は打った分だけで絞る。"""
        assert prefix_at("#日報メモ", 2) == "日"

    def test_階層も返す(self) -> None:
        assert prefix_at("#仕事/日報", 6) == "仕事/日報"

    def test_空行ではNone(self) -> None:
        assert prefix_at("", 0) is None


KNOWN_TAGS = ["仕事", "仕事/日報", "日報", "日記", "hitofude/使い方"]


class TestMatches:
    def test_前方一致で絞る(self) -> None:
        assert matches("日", KNOWN_TAGS) == ["日報", "日記"]

    def test_空なら全部(self) -> None:
        assert matches("", KNOWN_TAGS) == KNOWN_TAGS

    def test_階層の途中でも絞る(self) -> None:
        assert matches("仕事/", KNOWN_TAGS) == ["仕事/日報"]

    def test_大文字小文字を区別しない(self) -> None:
        assert matches("HITO", KNOWN_TAGS) == ["hitofude/使い方"]

    def test_一致が無ければ空(self) -> None:
        assert matches("存在しない", KNOWN_TAGS) == []

    def test_打ったものと同じだけなら出さない(self) -> None:
        """候補が今打っているものだけなら、出しても選ぶものが無い。"""
        assert matches("日報", ["日報"]) == []
