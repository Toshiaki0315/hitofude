"""サンプル文書に対する回帰テスト（タスク 1-10 / spec §10）。

個別のテストが通っても、実際の文書を通すと壊れることがある。
ここは「コア層 3 モジュールを実文書に通して破綻しない」ことを見る層。
"""

from pathlib import Path

import pytest

from hitofude.core import frontmatter, tags
from hitofude.core.block_parser import parse
from hitofude.core.inline_scanner import scan
from hitofude.core.models import BlockType, SpanType

FIXTURES = ("basic.md", "japanese.md", "edge_cases.md", "large.md")


@pytest.fixture(params=FIXTURES)
def fixture_text(request: pytest.FixtureRequest, fixtures_dir: Path) -> str:
    return (fixtures_dir / request.param).read_text(encoding="utf-8")


class TestAllFixtures:
    def test_ブロック解析が行数と一致する(self, fixture_text: str) -> None:
        assert len(parse(fixture_text)) == len(fixture_text.split("\n"))

    def test_全行のインライン解析が例外を投げない(self, fixture_text: str) -> None:
        for line in fixture_text.split("\n"):
            scan(line)

    def test_スパンが行の範囲に収まる(self, fixture_text: str) -> None:
        for line in fixture_text.split("\n"):
            for span in scan(line):
                assert 0 <= span.start <= span.end <= len(line)

    def test_スパン同士が交差しない(self, fixture_text: str) -> None:
        """交差するとハイライトの上書き順が破綻する。"""
        for line in fixture_text.split("\n"):
            spans = scan(line)
            for i, outer in enumerate(spans):
                for inner in spans[i + 1 :]:
                    assert not (outer.start < inner.start < outer.end < inner.end)

    def test_front_matterの往復でテキストが変わらない(self, fixture_text: str) -> None:
        parsed = frontmatter.split(fixture_text)
        assert frontmatter.join(parsed.meta, parsed.body) == fixture_text


class TestBasic:
    @pytest.fixture
    def text(self, fixtures_dir: Path) -> str:
        return (fixtures_dir / "basic.md").read_text(encoding="utf-8")

    def test_front_matterを読める(self, text: str) -> None:
        parsed = frontmatter.split(text)
        assert parsed.meta["id"] == "01J9XQ2F8K7M3N5P"
        assert parsed.meta["pinned"] is False

    def test_主要なブロック種別が一通り現れる(self, text: str) -> None:
        found = {block.type for block in parse(text)}
        expected = {
            BlockType.FRONT_MATTER,
            BlockType.HEADING,
            BlockType.PARAGRAPH,
            BlockType.BULLET_LIST_ITEM,
            BlockType.ORDERED_LIST_ITEM,
            BlockType.TASK_LIST_ITEM,
            BlockType.BLOCKQUOTE,
            BlockType.CODE_FENCE_OPEN,
            BlockType.CODE_FENCE_BODY,
            BlockType.CODE_FENCE_CLOSE,
            BlockType.TABLE_ROW,
            BlockType.TABLE_DELIMITER,
            BlockType.HORIZONTAL_RULE,
            BlockType.BLANK,
        }
        assert expected <= found

    def test_見出しレベルが1から6まで揃う(self, text: str) -> None:
        levels = {b.level for b in parse(text) if b.type is BlockType.HEADING}
        assert levels == {1, 2, 3, 4, 5, 6}

    def test_主要なインライン種別が一通り現れる(self, text: str) -> None:
        found = {span.type for line in text.split("\n") for span in scan(line)}
        expected = {
            SpanType.STRONG,
            SpanType.EM,
            SpanType.STRONG_EM,
            SpanType.STRIKE,
            SpanType.HIGHLIGHT,
            SpanType.CODE,
            SpanType.LINK_TEXT,
            SpanType.LINK_URL,
            SpanType.IMAGE,
            SpanType.AUTOLINK,
            SpanType.TAG,
        }
        assert expected <= found

    def test_タグを抽出できる(self, text: str) -> None:
        assert tags.extract(text) == ["work/会議", "private"]


class TestJapanese:
    @pytest.fixture
    def text(self, fixtures_dir: Path) -> str:
        return (fixtures_dir / "japanese.md").read_text(encoding="utf-8")

    def test_句読点や括弧に隣接する強調を拾う(self, text: str) -> None:
        """spec §11 R4。ここが落ちると日本語ユーザーには主要機能が動かない。"""
        for line in ("これは**強調**です。これは*斜体*です。これは~~取り消し~~です。",):
            assert line in text
        strong_lines = [
            line
            for line in text.split("\n")
            if any(span.type is SpanType.STRONG for span in scan(line))
        ]
        assert "句読点に隣接する場合。**強調**。次に、*斜体*、そして~~取り消し~~。" in strong_lines
        assert "括弧に隣接する場合。「**強調**」と『*斜体*』と（::ハイライト::）。" in strong_lines

    def test_識別子は斜体にならない(self, text: str) -> None:
        line = "`_` は緩めない。snake_case_name や SOME_CONST は斜体にならない。"
        assert line in text
        assert [span.type for span in scan(line)] == [SpanType.CODE]

    def test_コード内とハッシュ見出しはタグにしない(self, text: str) -> None:
        assert tags.extract(text) == ["work", "work/会議", "private"]


class TestEdgeCases:
    @pytest.fixture
    def text(self, fixtures_dir: Path) -> str:
        return (fixtures_dir / "edge_cases.md").read_text(encoding="utf-8")

    def test_フェンスの中身は全てCODE_FENCE_BODYになる(self, text: str) -> None:
        """```markdown フェンスの中に書いた記法が、どれも解釈されないこと。"""
        blocks = parse(text)
        lines = text.split("\n")
        inside = {
            "# これは見出しではない",
            "- これはリストではない",
            "**これは強調ではない**",
            "#これはタグではない",
        }
        seen = {
            lines[block.line] for block in blocks if block.type is BlockType.CODE_FENCE_BODY
        } & inside
        assert seen == inside

    def test_フェンス内の見出しをHEADINGにしない(self, text: str) -> None:
        blocks = parse(text)
        lines = text.split("\n")
        for block in blocks:
            if lines[block.line] == "# これは見出しではない":
                assert block.type is BlockType.CODE_FENCE_BODY

    def test_連続するフェンスを取り違えない(self, text: str) -> None:
        opens = [b for b in parse(text) if b.type is BlockType.CODE_FENCE_OPEN]
        assert [b.lang for b in opens] == ["markdown", None, "js", None]

    def test_未閉じマーカーの行でも例外を出さない(self, text: str) -> None:
        for line in text.split("\n"):
            scan(line)


@pytest.mark.slow
class TestLarge:
    """spec §6.6 の性能基準を測るための土台。実際の閾値検証は Phase 2。"""

    @pytest.fixture
    def text(self, fixtures_dir: Path) -> str:
        return (fixtures_dir / "large.md").read_text(encoding="utf-8")

    def test_1万語のノートを解析できる(self, text: str) -> None:
        blocks = parse(text)
        assert len(blocks) > 2000

    def test_全行のインライン走査が1秒未満(self, text: str) -> None:
        """1 行あたりの走査は µs 単位であること（§3.4）。

        ここは上限がとても緩い煙感知器。厳密な 16ms 予算の検証は Phase 2。
        """
        import time

        lines = text.split("\n")
        started = time.perf_counter()
        for line in lines:
            scan(line)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0, f"{len(lines)} 行の走査に {elapsed:.3f}s"
