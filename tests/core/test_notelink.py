"""`[[ノート名]]` の打ちかけ判定と候補絞り（ユーザー要望）。

`[[会議メモ]]` は書けるのに**候補が出なかった**ので、正確な名前を覚えて
いるか、別のノートを開いて確かめる必要があった。タグ（`#`）と同じ形で
補完する。判定はここ（Qt に触れない純関数）。
"""

import pytest

from hitofude.core import notelink

TITLES = ["会議メモ", "会計メモ", "買い物リスト", "Meeting notes"]


class TestPrefixAt:
    @pytest.mark.parametrize(
        ("line", "column", "expected"),
        [
            ("[[", 2, ""),
            ("[[会議", 4, "会議"),
            ("本文の途中で [[会議", 11, "会議"),
            ("[[会議メモ]] のあと", 5, "会議メ"),
        ],
    )
    def test_打ちかけを拾う(self, line: str, column: int, expected: str) -> None:
        assert notelink.prefix_at(line, column) == expected

    @pytest.mark.parametrize(
        ("line", "column"),
        [
            ("ふつうの本文", 3),
            ("[ 1 つだけ", 5),
            ("#タグ", 3),
            ("[[会議]] のあと", 10),  # 閉じたあとは打ちかけではない
            ("[[会議\nメモ", 9),  # 行をまたがない
        ],
    )
    def test_リンクの外なら拾わない(self, line: str, column: int) -> None:
        assert notelink.prefix_at(line, column) is None

    def test_別名の記法は拾わない(self) -> None:
        """`[[名前|表示]]` は未対応（`inline_scanner` と揃える）。
        中途半端に補完すると名前が壊れる。"""
        assert notelink.prefix_at("[[会議|表示", 7) is None

    def test_カーソルより後ろは見ない(self) -> None:
        """直そうとしている綴りで絞ってしまわないため（タグと同じ）。"""
        assert notelink.prefix_at("[[会議メモ", 4) == "会議"


class TestMatches:
    def test_前方一致で絞る(self) -> None:
        assert notelink.matches("会議", TITLES) == ["会議メモ"]

    def test_空なら全部(self) -> None:
        """`[[` と打った直後は、何から選べるかを見せる。"""
        assert notelink.matches("", TITLES) == TITLES

    def test_大文字小文字は区別しない(self) -> None:
        assert notelink.matches("meeting", TITLES) == ["Meeting notes"]

    def test_同じものしか無いなら出さない(self) -> None:
        """選ぶものが無いのに一覧が出ていると、Enter が決定なのか改行なのか
        分からなくなる（タグ補完と同じ理由）。"""
        assert notelink.matches("会議メモ", TITLES) == []

    def test_無ければ空(self) -> None:
        assert notelink.matches("存在しない", TITLES) == []


class TestClosingTail:
    """閉じ `]]` までに残っている名前の長さ（コードレビュー指摘の修正）。"""

    @pytest.mark.parametrize(
        ("rest", "expected"),
        [
            ("メモ]] のあと", 2),  # 名前の途中
            ("]]", 0),  # 閉じの直前
            ("]] のあと", 0),
            (" のあと", None),  # 閉じが無い（開きかけ）
            ("", None),
            ("メモ| 別名]]", None),  # 別名記法は未対応（食べない）
        ],
    )
    def test_長さ(self, rest, expected) -> None:
        from hitofude.core.notelink import closing_tail

        assert closing_tail(rest) == expected
