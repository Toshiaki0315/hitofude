"""コードフェンスの言語補完（ユーザー要望）。

候補の源は Pygments の別名一覧 = 実際に色が付く名前（core/code_tokens.py と
同じ）。絞り込みと「どこで発火するか」は純関数で GUI なしで検証する（R3）。
"""

import pytest

from hitofude.core.code_langs import known_langs, matches, prefix_at


class TestPrefixAt:
    @pytest.mark.parametrize(
        ("line", "column", "expected"),
        [
            ("```py", 5, "py"),  # 打ちかけ
            ("```p", 4, "p"),
            ("```python", 9, "python"),
            ("```py:aaa.py", 5, "py"),  # ファイル名の手前
            ("````py", 6, "py"),  # 長いフェンスも開始行
        ],
    )
    def test_発火する(self, line, column, expected) -> None:
        assert prefix_at(line, column) == expected

    @pytest.mark.parametrize(
        ("line", "column"),
        [
            ("```", 3),  # 何も打っていない（Enter を奪わない）
            ("``py", 4),  # フェンスではない
            ("本文 ```py", 8),  # 行頭ではない
            ("```python", 5),  # トークンの途中（末尾でだけ出す）
            ("```py:aaa.py", 12),  # ファイル名の中
            ("#タグ", 2),  # タグの行はタグ補完の領分
        ],
    )
    def test_発火しない(self, line, column) -> None:
        assert prefix_at(line, column) is None


class TestMatches:
    def test_前方一致で絞る(self) -> None:
        found = matches("pyth")
        assert found
        assert all(name.startswith("pyth") for name in found)
        assert "python" in found

    def test_よく使う言語が先頭に来る(self) -> None:
        # `j` は java / javascript / json などが jags 等の稀な言語より先
        found = matches("j")
        assert found.index("json") < 5
        assert found.index("javascript") < 5

    def test_打ったものと同じだけなら出さない(self) -> None:
        """タグ補完と同じ理屈。選ぶものが無いのに Enter を奪わない。"""
        exact_only = "python3"  # 完全一致し、それより長い別名が無い綴りを探す
        candidates = [n for n in known_langs() if n.startswith(exact_only)]
        if candidates != [exact_only]:
            pytest.skip("前提の別名が変わった")
        assert matches(exact_only) == []

    def test_知らない接頭辞は空(self) -> None:
        assert matches("zzzzzz") == []


class TestKnownLangs:
    def test_色が付く名前だけが載る(self) -> None:
        """補完に出た名前は必ず色が付く（code_tokens と同じ源）。"""
        from hitofude.core.code_tokens import tokenize

        assert "python" in known_langs()
        assert tokenize("import os", "python")  # 色が付く

    def test_二回目からはキャッシュ(self) -> None:
        assert known_langs() is known_langs()
