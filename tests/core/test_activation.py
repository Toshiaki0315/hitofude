"""クリックで開くもの（D-1 / D-2）。

`Cmd+クリック` したときに何を起こすかを決める純関数。`core/` にあるので
PySide6 に依存しない（R3）。開く先の絞り込みはここで完結させる。
"""

import pytest

from hitofude.core.activation import Activation, ActivationKind, activation_at


def spans(line: str):
    from hitofude.core.inline_scanner import scan

    return scan(line)


def at(line: str, column: int) -> Activation | None:
    return activation_at(spans(line), column)


class TestLinks:
    def test_リンクの文字で開く(self) -> None:
        found = at("[Qt](https://qt.io) を見る", 2)
        assert found == Activation(ActivationKind.LINK, "https://qt.io")

    def test_URLの部分でも開く(self) -> None:
        assert at("[Qt](https://qt.io)", 10).payload == "https://qt.io"

    def test_自動リンクも開く(self) -> None:
        assert at("<https://example.com>", 5).payload == "https://example.com"

    def test_裸のURLも開く(self) -> None:
        assert at("https://example.com を見る", 3).payload == "https://example.com"

    def test_リンクの外は何も起きない(self) -> None:
        assert at("[Qt](https://qt.io) を見る", 22) is None

    def test_ただの文では何も起きない(self) -> None:
        assert at("ただの文章です", 3) is None


class TestSafety:
    """**本文は手で編集できる。** 開く先を絞らないと、思わぬものが動く。"""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:x",
        ],
    )
    def test_危ないスキームは開かない(self, url: str) -> None:
        assert at(f"[危険]({url})", 2) is None

    def test_メールは開く(self) -> None:
        assert at("[連絡](mailto:a@example.com)", 2).payload == "mailto:a@example.com"

    def test_大文字小文字は問わない(self) -> None:
        assert at("[Qt](HTTPS://qt.io)", 2) is not None

    def test_相対パスは開かない(self) -> None:
        """`![](attachments/…)` のような vault 内の参照。外へ出す話ではない。"""
        assert at("[画像](attachments/a.png)", 2) is None


class TestTags:
    def test_タグで絞り込む(self) -> None:
        assert at("メモ #日報 です", 4) == Activation(ActivationKind.TAG, "日報")

    def test_階層タグも絞り込む(self) -> None:
        assert at("#仕事/日報", 3).payload == "仕事/日報"

    def test_タグの外は何も起きない(self) -> None:
        assert at("メモ #日報 です", 0) is None


class TestBoundaries:
    def test_先頭の文字でも効く(self) -> None:
        assert at("#日報", 0) is not None

    def test_末尾の直後は効かない(self) -> None:
        """範囲は `[start, end)`。終端は次の文字。"""
        assert at("#日報 続き", 3) is None

    def test_コードの中のURLは開かない(self) -> None:
        assert at("`https://example.com`", 5) is None
