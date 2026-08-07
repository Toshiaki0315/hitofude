"""ゴールデンテスト（タスク 2-11 / spec §10）。

サンプル文書のハイライト結果をスナップショットと突き合わせる。
個別のテストは「意図した挙動」を守るが、こちらは**意図しない変化**を捕まえる。

スナップショットを更新するとき:

    uv run python scripts/update_golden.py

差分を必ず目で確認すること。落ちたテストを更新で黙らせるのは、
このテストの存在意義を消す行為になる。
"""

import json
from pathlib import Path

import pytest

from tests.editor.golden import golden_path, snapshot

pytestmark = pytest.mark.gui

FIXTURES = ("basic", "japanese", "edge_cases")


@pytest.mark.parametrize("name", FIXTURES)
def test_ハイライト結果がスナップショットと一致する(qapp, fixtures_dir: Path, name: str) -> None:
    source = (fixtures_dir / f"{name}.md").read_text(encoding="utf-8")
    expected_path = golden_path(fixtures_dir, name)
    assert expected_path.is_file(), (
        f"{expected_path} が無い。`uv run python scripts/update_golden.py` で生成する"
    )

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = snapshot(source)

    assert len(actual) == len(expected), "行数が変わっている"
    for got, want in zip(actual, expected, strict=True):
        assert got == want, f"{name}.md の {want['line']} 行目: {want['text']!r}"


def test_スナップショットは日本語の強調を含む(qapp, fixtures_dir: Path) -> None:
    """ゴールデンが R4 の回帰を実際に見張っていることの確認。"""
    expected = json.loads(golden_path(fixtures_dir, "japanese").read_text(encoding="utf-8"))
    lines = {entry["text"]: entry for entry in expected}
    target = lines["これは**強調**です。これは*斜体*です。これは~~取り消し~~です。"]
    descriptors = [descriptor for _, _, descriptor in target["ranges"]]
    assert "bold" in descriptors
    assert "italic" in descriptors
    assert any(d.startswith("hidden:") for d in descriptors)
