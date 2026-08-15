"""未使用の添付を片づける（E-5）。

本文から消した画像が `attachments/` に残り続ける問題への対処。

**消さずにゴミ箱へ移す。** 判定を誤って使用中の画像を片づけてしまっても、
30 日のあいだは `.trash/` から戻せる。判定は「本文に名前が出てこない」
という消極的なもので、**取りこぼし（＝消しすぎ）が最悪の結果**になる。

だから数える対象を広く取る。ゴミ箱の中のノートも、雛形も見る。
"""

from pathlib import Path

import pytest

from hitofude.storage.vault import Vault

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    target = Vault(tmp_path / "HitofudeNotes")
    target.ensure_layout()
    return target


def put_attachment(vault: Vault, name: str) -> Path:
    path = vault.attachments_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    return path


class TestFinding:
    def test_使われていない添付が出る(self, vault) -> None:
        orphan = put_attachment(vault, "迷子.png")
        assert vault.unused_attachments() == [orphan]

    def test_使われている添付は出ない(self, vault) -> None:
        used = put_attachment(vault, "使用中.png")
        vault.create("メモ", "# メモ\n\n![](attachments/使用中.png)\n")
        assert used not in vault.unused_attachments()

    def test_添付が無ければ空(self, vault) -> None:
        assert vault.unused_attachments() == []

    def test_フォルダが無くても壊れない(self, vault, tmp_path: Path) -> None:
        assert Vault(tmp_path / "無い").unused_attachments() == []

    def test_名前順に並ぶ(self, vault) -> None:
        for name in ("b.png", "a.png"):
            put_attachment(vault, name)
        assert [p.name for p in vault.unused_attachments()] == ["a.png", "b.png"]

    def test_サブフォルダは触らない(self, vault) -> None:
        """人が自分で作ったフォルダは、こちらの判断で動かさない。"""
        nested = vault.attachments_dir / "保存" / "図.png"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_bytes(PNG)
        assert vault.unused_attachments() == []

    def test_隠しファイルは触らない(self, vault) -> None:
        """`.DS_Store` は macOS が作るもので、こちらの持ち物ではない。"""
        (vault.attachments_dir / ".DS_Store").write_bytes(b"x")
        assert vault.unused_attachments() == []


class TestWhatCounts:
    """**広く数える。** 数え漏らしはそのまま画像の消失になる。"""

    def test_ゴミ箱のノートからの参照も数える(self, vault) -> None:
        """戻したときに絵が消えていては困る。"""
        used = put_attachment(vault, "図.png")
        note = vault.create("捨てたメモ", "# 捨てたメモ\n\n![](attachments/図.png)\n")
        vault.trash(note.path)
        assert used not in vault.unused_attachments()

    def test_雛形からの参照も数える(self, vault) -> None:
        used = put_attachment(vault, "枠.png")
        vault.templates_dir.mkdir(parents=True, exist_ok=True)
        (vault.templates_dir / "日報.md").write_text(
            "# {{date}}\n\n![](attachments/枠.png)\n", encoding="utf-8"
        )
        assert used not in vault.unused_attachments()

    def test_サブフォルダのノートからの参照も数える(self, vault) -> None:
        used = put_attachment(vault, "図.png")
        nested = vault.root / "仕事" / "メモ.md"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text("![](attachments/図.png)\n", encoding="utf-8")
        assert used not in vault.unused_attachments()

    def test_コードブロックの中でも数える(self, vault) -> None:
        used = put_attachment(vault, "図.png")
        vault.create("メモ", "# メモ\n\n```\n![](attachments/図.png)\n```\n")
        assert used not in vault.unused_attachments()

    def test_読めないファイルがあっても止まらない(self, vault) -> None:
        """1 つ読めないだけで掃除が止まると、片づけられなくなる。"""
        put_attachment(vault, "迷子.png")
        broken = vault.root / "壊れた.md"
        broken.write_bytes(b"\xff\xfe\x00\x00not utf-8")
        assert [p.name for p in vault.unused_attachments()] == ["迷子.png"]


class TestTrashing:
    def test_ゴミ箱へ移る(self, vault) -> None:
        orphan = put_attachment(vault, "迷子.png")
        moved = vault.trash_attachments([orphan])
        assert not orphan.exists()
        assert moved[0].parent == vault.trash_dir
        assert moved[0].read_bytes() == PNG

    def test_消さない(self, vault) -> None:
        """30 日のあいだは戻せる（`purge_trash` が期限を見る）。"""
        orphan = put_attachment(vault, "迷子.png")
        moved = vault.trash_attachments([orphan])
        assert moved[0].is_file()

    def test_同じ名前があってもぶつからない(self, vault) -> None:
        first = put_attachment(vault, "図.png")
        vault.trash_attachments([first])
        second = put_attachment(vault, "図.png")
        moved = vault.trash_attachments([second])
        assert moved[0].is_file()
        assert len(list(vault.trash_dir.iterdir())) == 2

    def test_添付の外は動かさない(self, vault) -> None:
        """**パスは呼び出し側から来る。** ノートを片づけてしまわない。"""
        note = vault.create("大事なメモ", "# 大事なメモ\n")
        assert vault.trash_attachments([note.path]) == []
        assert note.path.is_file()

    def test_無いファイルは飛ばす(self, vault) -> None:
        assert vault.trash_attachments([vault.attachments_dir / "無い.png"]) == []

    def test_空でも壊れない(self, vault) -> None:
        assert vault.trash_attachments([]) == []
