"""大文字小文字だけ変えた改名（S-3）。

**APFS は大文字小文字を区別しない。** `Meeting.md` と `meeting.md` は
同じファイルなので、改名先が「既に在る」ように見える——見えている相手は
**自分自身**なのに、`unique_path` はそれを衝突と数えて `-2` を付けていた。

後を引く。以後ファイル名（`meeting-2`）とタイトル（`meeting`）が食い違う
ため、`save_controller._rename_if_title_changed` の条件により**そのノートは
二度とファイル名がタイトルに追従しない**。

日本語のタイトルは無傷で、`TODO` → `Todo` のような英字だけの話。
区別するファイルシステムでは元から衝突しないので、そちらでも同じ結果に
なることを見ている。
"""

import pytest

from hitofude.storage.vault import Vault, unique_path


@pytest.fixture
def vault(tmp_path):
    found = Vault(tmp_path / "vault")
    found.ensure_layout()
    return found


class TestCaseOnlyRename:
    def test_番号を付けない(self, vault) -> None:
        """**これが本題。** 衝突相手がいないのに `-2` を付けない。"""
        note = vault.create("Meeting", "# Meeting\n\n本文\n")
        target = vault.rename(note.path, "meeting")
        assert target.name == "meeting.md"

    def test_ファイルは1つのまま(self, vault) -> None:
        note = vault.create("Meeting", "# Meeting\n\n本文\n")
        vault.rename(note.path, "meeting")
        assert [p.name for p in sorted(vault.root.glob("*.md"))] == ["meeting.md"]

    def test_中身は無傷(self, vault) -> None:
        note = vault.create("Meeting", "# Meeting\n\n本文\n")
        target = vault.rename(note.path, "meeting")
        assert "本文" in target.read_text(encoding="utf-8")


class TestRealCollisionStillNumbers:
    """**直しすぎない。** 本物の衝突には今までどおり番号を付ける。"""

    def test_別のノートとぶつかれば番号(self, vault) -> None:
        vault.create("会議", "# 会議\n\n一本目\n")
        other = vault.create("日誌", "# 日誌\n\n二本目\n")
        target = vault.rename(other.path, "会議")
        assert target.name == "会議-2.md"

    def test_大文字小文字違いの別ノートとも番号(self, vault) -> None:
        """自分自身でなければ、同じ綴りに見えても別のノート。"""
        vault.create("Meeting", "# Meeting\n\n一本目\n")
        other = vault.create("日誌", "# 日誌\n\n二本目\n")
        target = vault.rename(other.path, "meeting")
        assert target.name != "meeting.md"


class TestUniquePath:
    def test_自分自身は衝突ではない(self, vault) -> None:
        path = vault.root / "Meeting.md"
        path.write_text("x", encoding="utf-8")
        assert unique_path(vault.root, "meeting", ignoring=path).name == "meeting.md"

    def test_渡さなければ今までどおり(self, vault) -> None:
        path = vault.root / "会議.md"
        path.write_text("x", encoding="utf-8")
        assert unique_path(vault.root, "会議").name == "会議-2.md"
