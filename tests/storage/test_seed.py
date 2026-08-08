"""初回起動時の使い方ノート（ユーザー要望）。

サンプル兼マニュアル。**一度消したら復活させない**ことが要点。
"""

from pathlib import Path

import pytest

from hitofude.core.block_parser import parse
from hitofude.core.document import Note
from hitofude.core.models import BlockType
from hitofude.storage.vault import MANUAL_TITLE, SEED_MARKER, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    target = Vault(tmp_path / "HitofudeNotes")
    target.ensure_layout()
    return target


class TestSeeding:
    def test_空のvaultに置かれる(self, vault) -> None:
        note = vault.seed_manual()
        assert note is not None
        assert note.path.name == f"{MANUAL_TITLE}.md"
        assert note.path.is_file()

    def test_タイトルが読める(self, vault) -> None:
        assert vault.seed_manual().title == MANUAL_TITLE

    def test_front_matterが付く(self, vault) -> None:
        """他のノートと同じ扱いになること。"""
        note = vault.seed_manual()
        assert note.id is not None
        assert note.meta["created"]

    def test_ノートがあるvaultには置かない(self, vault) -> None:
        vault.create("既存のメモ", "# 既存のメモ\n")
        assert vault.seed_manual() is None

    def test_二度目は置かない(self, vault) -> None:
        """ユーザーが消したものを起動のたびに復活させない。"""
        first = vault.seed_manual()
        first.path.unlink()
        assert vault.seed_manual() is None

    def test_印が管理領域に残る(self, vault) -> None:
        vault.seed_manual()
        assert (vault.managed_dir / SEED_MARKER).is_file()

    def test_リソースが無くても落ちない(self, vault, monkeypatch) -> None:
        """同梱が漏れても起動を止めない。"""
        monkeypatch.setattr("hitofude.storage.vault._read_resource", lambda name: None)
        assert vault.seed_manual() is None


class TestIsEmpty:
    def test_空なら空(self, vault) -> None:
        assert vault.is_empty() is True

    def test_ノートがあれば空でない(self, vault) -> None:
        vault.create("メモ")
        assert vault.is_empty() is False

    def test_ゴミ箱の中身は数えない(self, vault) -> None:
        note = vault.create("メモ")
        vault.trash(note.path)
        assert vault.is_empty() is True


class TestManualContent:
    """マニュアルは表示のサンプルも兼ねるので、記法を一通り含むこと。"""

    @pytest.fixture
    def blocks(self, vault) -> list:
        note = vault.seed_manual()
        return parse(Note.read(note.path).text)

    @pytest.mark.parametrize(
        "kind",
        [
            BlockType.HEADING,
            BlockType.PARAGRAPH,
            BlockType.BULLET_LIST_ITEM,
            BlockType.ORDERED_LIST_ITEM,
            BlockType.TASK_LIST_ITEM,
            BlockType.BLOCKQUOTE,
            BlockType.CODE_FENCE_OPEN,
            BlockType.CODE_FENCE_BODY,
            BlockType.TABLE_ROW,
            BlockType.TABLE_DELIMITER,
        ],
    )
    def test_主要な記法を含む(self, blocks, kind: BlockType) -> None:
        assert kind in {block.type for block in blocks}

    def test_タグを含む(self, vault) -> None:
        from hitofude.core import tags

        note = vault.seed_manual()
        assert tags.extract(Note.read(note.path).text)

    def test_インライン記法を含む(self, vault) -> None:
        from hitofude.core.inline_scanner import scan
        from hitofude.core.models import SpanType

        text = Note.read(vault.seed_manual().path).text
        found = {span.type for line in text.split("\n") for span in scan(line)}
        for kind in (SpanType.STRONG, SpanType.EM, SpanType.CODE, SpanType.LINK_TEXT):
            assert kind in found

    def test_表がすでに揃っている(self, vault) -> None:
        """開いた瞬間に罫線付きで表示されること。"""
        from hitofude.editor.table import find_table, format_table

        lines = Note.read(vault.seed_manual().path).text.split("\n")
        checked = 0
        for number, _line in enumerate(lines):
            found = find_table(lines, number)
            if found is None or found[0] != number:
                continue
            block = lines[found[0] : found[1]]
            assert format_table(block) == block, f"{number} 行目の表が揃っていない"
            checked += 1
        assert checked >= 2, "表が足りない"
