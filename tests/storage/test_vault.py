"""vault の走査と CRUD のテスト（タスク 4-1, 4-2 / spec §7.1, §7.6）。"""

from pathlib import Path

import pytest

from hitofude.storage.vault import (
    ATTACHMENTS_DIR,
    MANAGED_DIR,
    TRASH_DIR,
    Vault,
    sanitize_filename,
)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "HitofudeNotes")


class TestSanitize:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("会議メモ", "会議メモ"),
            ("2026/08/08 の記録", "2026-08-08 の記録"),  # `/` はパス区切り
            ("メモ: 続き", "メモ- 続き"),  # `:` は macOS で使えない
            ("  前後の空白  ", "前後の空白"),
            ("複数   の   空白", "複数 の 空白"),
            (".隠しファイル", "隠しファイル"),  # 先頭のドットは隠しファイルになる
            ("", "無題"),
            ("   ", "無題"),
            ("...", "無題"),
        ],
    )
    def test_ファイル名にできる形へ直す(self, title: str, expected: str) -> None:
        assert sanitize_filename(title) == expected

    def test_改行や制御文字を落とす(self) -> None:
        assert sanitize_filename("一行目\n二行目\t続き") == "一行目 二行目 続き"

    def test_長すぎる名前を切る(self) -> None:
        """macOS のファイル名上限は 255 バイト。日本語は 1 文字 3 バイト。"""
        name = sanitize_filename("あ" * 200)
        assert len(name.encode("utf-8")) <= 200


class TestLayout:
    def test_必要なディレクトリを作る(self, vault) -> None:
        vault.ensure_layout()
        assert vault.root.is_dir()
        assert (vault.root / ATTACHMENTS_DIR).is_dir()
        assert (vault.root / TRASH_DIR).is_dir()
        assert (vault.root / MANAGED_DIR).is_dir()

    def test_二度呼んでも壊れない(self, vault) -> None:
        vault.ensure_layout()
        vault.ensure_layout()
        assert vault.root.is_dir()


class TestScan:
    def test_マークダウンだけを拾う(self, vault) -> None:
        vault.ensure_layout()
        (vault.root / "メモ.md").write_text("a", encoding="utf-8")
        (vault.root / "画像.png").write_bytes(b"x")
        (vault.root / "readme.txt").write_text("b", encoding="utf-8")
        assert [p.name for p in vault.scan()] == ["メモ.md"]

    def test_管理領域とゴミ箱は除く(self, vault) -> None:
        """spec §7.1: `.trash` と `.hitofude` はユーザーのノートではない。"""
        vault.ensure_layout()
        (vault.root / "メモ.md").write_text("a", encoding="utf-8")
        (vault.root / TRASH_DIR / "捨てた.md").write_text("b", encoding="utf-8")
        (vault.root / MANAGED_DIR / "内部.md").write_text("c", encoding="utf-8")
        assert [p.name for p in vault.scan()] == ["メモ.md"]

    def test_手で作ったサブフォルダは再帰的に読む(self, vault) -> None:
        """spec §7.1: アプリからは作らせないが、あれば読む。"""
        vault.ensure_layout()
        nested = vault.root / "仕事" / "2026"
        nested.mkdir(parents=True)
        (nested / "資料.md").write_text("a", encoding="utf-8")
        assert [p.name for p in vault.scan()] == ["資料.md"]

    def test_空のvaultでも壊れない(self, vault) -> None:
        vault.ensure_layout()
        assert list(vault.scan()) == []

    def test_存在しないvaultでも例外にしない(self, vault) -> None:
        assert list(vault.scan()) == []


class TestCreate:
    def test_タイトルからファイルを作る(self, vault) -> None:
        note = vault.create("会議メモ")
        assert note.path == vault.root / "会議メモ.md"
        assert note.path.is_file()

    def test_front_matterにIDと日時が入る(self, vault) -> None:
        """spec §7.2: `id` はファイル名変更に耐える永続 ID。"""
        note = vault.create("会議メモ")
        assert len(note.id) == 26
        assert note.meta["created"]
        assert note.meta["modified"]

    def test_本文を渡せる(self, vault) -> None:
        note = vault.create("会議メモ", "# 会議メモ\n\n本文\n")
        assert "# 会議メモ" in note.text

    def test_名前が衝突したら連番を付ける(self, vault) -> None:
        """spec §7.1: 重複時は `-2`, `-3`。"""
        first = vault.create("メモ")
        second = vault.create("メモ")
        third = vault.create("メモ")
        assert first.path.name == "メモ.md"
        assert second.path.name == "メモ-2.md"
        assert third.path.name == "メモ-3.md"

    def test_タイトルが空でも作れる(self, vault) -> None:
        assert vault.create("").path.name == "無題.md"


class TestWrite:
    def test_保存すると読み直せる(self, vault) -> None:
        note = vault.create("メモ")
        vault.write(note.path, "書き換えた本文\n")
        assert vault.read(note.path).text == "書き換えた本文\n"

    def test_保存後にmtimeが更新される(self, vault) -> None:
        note = vault.create("メモ")
        vault.write(note.path, "新しい内容\n")
        assert vault.read(note.path).mtime_ns >= note.mtime_ns

    def test_一時ファイルを残さない(self, vault) -> None:
        """spec §7.4: アトミック書き込みの痕跡が vault に残ってはいけない。"""
        note = vault.create("メモ")
        vault.write(note.path, "内容\n")
        assert [p.name for p in vault.root.iterdir() if p.suffix == ".tmp"] == []


class TestRename:
    def test_タイトル変更でファイル名も変わる(self, vault) -> None:
        note = vault.create("古い名前")
        new_path = vault.rename(note.path, "新しい名前")
        assert new_path.name == "新しい名前.md"
        assert not note.path.exists()

    def test_中身は保たれる(self, vault) -> None:
        note = vault.create("古い名前", "本文はそのまま\n")
        new_path = vault.rename(note.path, "新しい名前")
        assert "本文はそのまま" in vault.read(new_path).text

    def test_旧名はゴミ箱に残さない(self, vault) -> None:
        """spec §7.1: リネームは削除ではない。"""
        note = vault.create("古い名前")
        vault.rename(note.path, "新しい名前")
        assert list((vault.root / TRASH_DIR).iterdir()) == []

    def test_同じ名前なら何もしない(self, vault) -> None:
        note = vault.create("名前")
        assert vault.rename(note.path, "名前") == note.path

    def test_衝突したら連番を付ける(self, vault) -> None:
        vault.create("既にある")
        note = vault.create("これから")
        assert vault.rename(note.path, "既にある").name == "既にある-2.md"


class TestTrash:
    def test_ゴミ箱へ移す(self, vault) -> None:
        note = vault.create("消すメモ")
        moved = vault.trash(note.path)
        assert moved.parent == vault.root / TRASH_DIR
        assert not note.path.exists()

    def test_走査対象から外れる(self, vault) -> None:
        note = vault.create("消すメモ")
        vault.trash(note.path)
        assert list(vault.scan()) == []

    def test_同名が既にあればタイムスタンプを付ける(self, vault) -> None:
        """spec §7.6: ファイル名衝突時はタイムスタンプを付与。"""
        first = vault.create("メモ")
        vault.trash(first.path)
        second = vault.create("メモ")
        moved = vault.trash(second.path)
        assert moved.name != "メモ.md"
        assert len(list((vault.root / TRASH_DIR).iterdir())) == 2

    def test_復元できる(self, vault) -> None:
        note = vault.create("消すメモ")
        moved = vault.trash(note.path)
        restored = vault.restore(moved)
        assert restored.parent == vault.root
        assert restored.is_file()


class TestPurgeTrash:
    def test_期限を過ぎたものを消す(self, vault) -> None:
        """spec §7.6: 30 日以上経過したものを起動時に削除。"""
        import os
        import time

        note = vault.create("古いメモ")
        moved = vault.trash(note.path)
        old = time.time() - 31 * 24 * 3600
        os.utime(moved, (old, old))

        removed = vault.purge_trash(days=30)
        assert removed == [moved]
        assert not moved.exists()

    def test_期限内は残す(self, vault) -> None:
        note = vault.create("最近のメモ")
        moved = vault.trash(note.path)
        assert vault.purge_trash(days=30) == []
        assert moved.exists()

    def test_ゴミ箱が無くても壊れない(self, vault) -> None:
        assert vault.purge_trash(days=30) == []


class TestEmptyTrash:
    """ゴミ箱を今すぐ空にする（G-3）。

    今は 30 日待つしかない。**見られたくないものを捨てたときに困る**ので、
    自分の意思で今すぐ消せる道を用意する。
    """

    def test_中身を全部消す(self, vault) -> None:
        moved = [vault.trash(vault.create(name).path) for name in ("あ", "い")]
        removed = vault.empty_trash()
        assert sorted(removed) == sorted(moved)
        assert not any(path.exists() for path in moved)

    def test_ゴミ箱の外は消さない(self, vault) -> None:
        note = vault.create("残るメモ")
        vault.trash(vault.create("消すメモ").path)
        vault.empty_trash()
        assert note.path.is_file()

    def test_添付も消える(self, vault) -> None:
        """添付も `.trash` へ入る（E-5）。空にするなら一緒に消える。"""
        vault.attachments_dir.mkdir(parents=True, exist_ok=True)
        image = vault.attachments_dir / "図.png"
        image.write_bytes(b"png")
        moved = vault.trash_attachments([image])
        vault.empty_trash()
        assert not any(path.exists() for path in moved)

    def test_ゴミ箱が無くても壊れない(self, vault) -> None:
        assert vault.empty_trash() == []


class TestDeletePermanently:
    """1 件だけ完全に削除する（G-3）。"""

    def test_消える(self, vault) -> None:
        moved = vault.trash(vault.create("消すメモ").path)
        vault.delete_permanently(moved)
        assert not moved.exists()

    def test_ゴミ箱の外は消せない(self, vault) -> None:
        """**保管フォルダのノートを消す道を作らない。** 誤って渡されたら
        黙って消さずに止める。ゴミ箱に入れるのは UI 側の仕事。"""
        note = vault.create("大事なメモ")
        with pytest.raises(ValueError):
            vault.delete_permanently(note.path)
        assert note.path.is_file()

    def test_無いファイルでも壊れない(self, vault) -> None:
        moved = vault.trash(vault.create("消すメモ").path)
        vault.delete_permanently(moved)
        vault.delete_permanently(moved)


class TestSetPinned:
    """ピン留め（サイドバーの「お気に入り」に入れる操作）。

    front matter の `pinned` を書き換える。`modified` は触らない。
    ピン留めは本文の編集ではないので、一覧の並び順を動かすのは筋が悪い。
    """

    def test_ピン留めできる(self, vault: Vault) -> None:
        note = vault.create("メモ", "本文\n")
        assert vault.set_pinned(note.path, True).pinned is True

    def test_ピン留めを外せる(self, vault: Vault) -> None:
        note = vault.create("メモ", "本文\n")
        vault.set_pinned(note.path, True)
        assert vault.set_pinned(note.path, False).pinned is False

    def test_外すと鍵ごと消える(self, vault: Vault) -> None:
        """`pinned: false` を残さない。書いていないことは書かない。"""
        note = vault.create("メモ", "本文\n")
        vault.set_pinned(note.path, True)
        vault.set_pinned(note.path, False)
        assert "pinned" not in note.path.read_text(encoding="utf-8")

    def test_往復するとファイルが元に戻る(self, vault: Vault) -> None:
        note = vault.create("メモ", "本文\n")
        before = note.path.read_text(encoding="utf-8")
        vault.set_pinned(note.path, True)
        vault.set_pinned(note.path, False)
        assert note.path.read_text(encoding="utf-8") == before

    def test_本文を変えない(self, vault: Vault) -> None:
        note = vault.create("メモ", "# 見出し\n\n**強調** と `コード`\n")
        vault.set_pinned(note.path, True)
        assert "**強調** と `コード`" in note.path.read_text(encoding="utf-8")

    def test_modifiedを動かさない(self, vault: Vault) -> None:
        """ピン留めは編集ではない。一覧の並びが変わるのはおかしい。"""
        note = vault.create("メモ", "本文\n")
        before = note.meta.get("modified")
        assert vault.set_pinned(note.path, True).meta.get("modified") == before

    def test_front_matterが無いノートにも付けられる(self, vault: Vault) -> None:
        vault.ensure_layout()
        path = vault.root / "素のノート.md"
        path.write_text("見出しも何もない本文\n", encoding="utf-8")
        updated = vault.set_pinned(path, True)
        assert updated.pinned is True
        assert "見出しも何もない本文" in path.read_text(encoding="utf-8")

    def test_front_matterが壊れていても本文を失わない(self, vault: Vault) -> None:
        """G3: メタデータを理由に本文を失わせない。"""
        vault.ensure_layout()
        path = vault.root / "壊れたノート.md"
        path.write_text("---\n: : 壊れた YAML\n---\n大事な本文\n", encoding="utf-8")
        vault.set_pinned(path, True)
        assert "大事な本文" in path.read_text(encoding="utf-8")

    def test_同じ値を二度書いても壊れない(self, vault: Vault) -> None:
        note = vault.create("メモ", "本文\n")
        vault.set_pinned(note.path, True)
        assert vault.set_pinned(note.path, True).pinned is True


class TestAttachments:
    """画像などの添付（タスク A-2）。

    `attachments/` は作るだけで一度も使われていなかった。
    貼り付けた画像をここへ置き、本文からは**相対パス**で参照する。
    """

    def test_保存できる(self, vault: Vault) -> None:
        path = vault.add_attachment(b"\x89PNG fake", ".png")
        assert path.is_file()
        assert path.read_bytes() == b"\x89PNG fake"

    def test_attachmentsの中に置く(self, vault: Vault) -> None:
        path = vault.add_attachment(b"data", ".png")
        assert path.parent == vault.attachments_dir

    def test_ノートの一覧に出てこない(self, vault: Vault) -> None:
        """`.md` ではないし、`scan()` は attachments を除く。"""
        vault.add_attachment(b"data", ".png")
        assert list(vault.scan()) == []

    def test_同じ名前でも上書きしない(self, vault: Vault) -> None:
        first = vault.add_attachment("ひとつめ".encode(), ".png")
        second = vault.add_attachment("ふたつめ".encode(), ".png")
        assert first != second
        assert first.read_bytes() == "ひとつめ".encode()

    def test_拡張子を保つ(self, vault: Vault) -> None:
        assert vault.add_attachment(b"data", ".jpg").suffix == ".jpg"

    def test_点を付け忘れても効く(self, vault: Vault) -> None:
        assert vault.add_attachment(b"data", "png").suffix == ".png"

    def test_拡張子が無ければpngにする(self, vault: Vault) -> None:
        assert vault.add_attachment(b"data", "").suffix == ".png"

    @pytest.mark.parametrize("bad", ["../evil", "a/b", ".p g", ".md ", ".PNG"])
    def test_変な拡張子を持ち込ませない(self, vault: Vault, bad: str) -> None:
        path = vault.add_attachment(b"data", bad)
        assert path.parent == vault.attachments_dir
        assert "/" not in path.name
        assert path.suffix.islower()

    def test_名前は時刻から作る(self, vault: Vault) -> None:
        """並べたときに撮った順になるほうが探しやすい。"""
        name = vault.add_attachment(b"data", ".png").stem
        assert name[:8].isdigit()

    def test_相対リンクを作れる(self, vault: Vault) -> None:
        path = vault.add_attachment(b"data", ".png")
        assert vault.attachment_link(path) == f"![]({ATTACHMENTS_DIR}/{path.name})"

    def test_リンクはvaultからの相対(self, vault: Vault) -> None:
        """絶対パスで書くと、フォルダごと移したときに全部切れる。"""
        link = vault.attachment_link(vault.add_attachment(b"data", ".png"))
        assert str(vault.root) not in link

    def test_中身が空でも落ちない(self, vault: Vault) -> None:
        assert vault.add_attachment(b"", ".png").is_file()


class TestSymlinkedNotes:
    """保管フォルダの外へ出るシンボリックリンクは辿らない。

    辿ると外のノートが索引に入り、編集やゴミ箱移動の対象になる。
    ゴミ箱移動はボリュームをまたぐこともあり、vault が自己完結しなくなる。
    """

    def test_外へ出るリンクは拾わない(self, vault: Vault, tmp_path: Path) -> None:
        vault.ensure_layout()
        outside = tmp_path / "外部"
        outside.mkdir()
        (outside / "他人のメモ.md").write_text("# 他人のメモ\n", encoding="utf-8")
        (vault.root / "抜け道").symlink_to(outside)

        assert [p.name for p in vault.scan()] == []

    def test_中のノートは今まで通り拾う(self, vault: Vault) -> None:
        vault.create("ふつうのノート", "# ふつうのノート\n")
        (vault.root / "下位").mkdir()
        (vault.root / "下位" / "深いノート.md").write_text("# 深いノート\n", encoding="utf-8")

        assert len(list(vault.scan())) == 2

    def test_中を指すリンクは辿る(self, vault: Vault) -> None:
        """vault の中で完結しているなら、自己完結は崩れない。"""
        vault.ensure_layout()
        (vault.root / "本体").mkdir()
        (vault.root / "本体" / "メモ.md").write_text("# メモ\n", encoding="utf-8")
        (vault.root / "別名").symlink_to(vault.root / "本体")

        assert len(list(vault.scan())) == 2

    def test_外のファイルを指すリンクも拾わない(self, vault: Vault, tmp_path: Path) -> None:
        vault.ensure_layout()
        outside = tmp_path / "外.md"
        outside.write_text("# 外\n", encoding="utf-8")
        (vault.root / "リンク.md").symlink_to(outside)

        assert [p.name for p in vault.scan()] == []
