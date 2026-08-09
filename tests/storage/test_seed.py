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


class TestReplacing:
    """「使い方のノートを置き直す」（ヘルプメニュー）。

    アプリが新しくなって説明が増えても、**既に置いたノートは古いまま**に
    なる（印があるので `seed_manual()` は二度と置かない）。手元の説明を
    最新にする道をひとつ用意する。
    """

    def test_印があっても置ける(self, vault) -> None:
        vault.seed_manual()
        assert vault.place_manual() is not None

    def test_空でなくても置ける(self, vault) -> None:
        vault.create("べつのノート", "本文\n")
        assert vault.place_manual() is not None

    def test_既にあるノートを消さない(self, vault) -> None:
        first = vault.seed_manual()
        vault.write(first.path, "# 使い方\n\n書き足したメモ\n")
        vault.place_manual()
        assert "書き足したメモ" in first.path.read_text(encoding="utf-8")

    def test_別のファイルになる(self, vault) -> None:
        first = vault.seed_manual()
        assert vault.place_manual().path != first.path

    def test_中身は最新の説明(self, vault) -> None:
        vault.seed_manual()
        placed = vault.place_manual()
        assert "書式ツールバー" in placed.path.read_text(encoding="utf-8")

    def test_印は置き直しても消えない(self, vault) -> None:
        """置き直しは**初回扱いに戻すことではない**。消したマニュアルが
        次の起動で勝手に復活したら、消した意味が無くなる。"""
        vault.seed_manual()
        vault.place_manual()
        assert (vault.managed_dir / SEED_MARKER).exists()
        assert vault.seed_manual() is None


class TestQiitaSample:
    """B-3 で足した記法もサンプルに含める。

    マニュアルは表示の見本を兼ねているので、**実際に囲みや脚注が描かれる**
    ことがそのまま動作確認になる。
    """

    @pytest.fixture
    def text(self, vault) -> str:
        return Note.read(vault.seed_manual().path).text

    def test_囲みを含む(self, text) -> None:
        state = None
        kinds = set()
        from hitofude.core.block_parser import classify_line
        from hitofude.core.models import BlockState

        state = BlockState()
        for number, line in enumerate(text.split("\n")):
            info, state = classify_line(line, number, state)
            if info.note_kind:
                kinds.add(info.note_kind)
        assert kinds == {"info", "warn", "alert"}

    def test_脚注を含む(self, text) -> None:
        from hitofude.core.inline_scanner import scan
        from hitofude.core.models import SpanType

        found = {span.type for line in text.split("\n") for span in scan(line)}
        assert SpanType.FOOTNOTE in found

    def test_ファイル名付きのコードを含む(self, text) -> None:
        assert "```js:index.js" in text
