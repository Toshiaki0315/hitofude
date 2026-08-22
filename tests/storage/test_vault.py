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


class TestSubfolder:
    """**手で作ったサブフォルダのノートが、そこに留まること**（K-1）。

    §7.1 は「アプリからは作らせないが、手で作ったサブフォルダは再帰的に
    読み込む」と決めている。読めるのに、名前を変えると vault 直下へ出て
    しまっていた（実測）。分類したのに名前を変えただけで箱から飛び出す。
    """

    def put(self, vault, folder: str, title: str):
        target = vault.root / folder
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{title}.md"
        path.write_text(f"# {title}\n\n本文\n", encoding="utf-8")
        return path

    def test_名前を変えても同じフォルダ(self, vault) -> None:
        path = self.put(vault, "仕事", "改名前")
        renamed = vault.rename(path, "改名後")
        assert renamed == vault.root / "仕事" / "改名後.md"

    def test_深い階層でも留まる(self, vault) -> None:
        path = self.put(vault, "仕事/2026/08", "改名前")
        renamed = vault.rename(path, "改名後")
        assert renamed.parent == vault.root / "仕事" / "2026" / "08"

    def test_同名の衝突も同じフォルダで見る(self, vault) -> None:
        """**直下の同名とはぶつからない。** 別のフォルダなら別のノート。"""
        vault.ensure_layout()
        (vault.root / "既にある.md").write_text("# 既にある\n", encoding="utf-8")
        path = self.put(vault, "仕事", "改名前")
        renamed = vault.rename(path, "既にある")
        assert renamed == vault.root / "仕事" / "既にある.md"

    def test_同じフォルダの同名は避ける(self, vault) -> None:
        self.put(vault, "仕事", "既にある")
        path = self.put(vault, "仕事", "改名前")
        renamed = vault.rename(path, "既にある")
        assert renamed == vault.root / "仕事" / "既にある-2.md"

    def test_直下のノートは今まで通り(self, vault) -> None:
        note = vault.create("直下のメモ")
        renamed = vault.rename(note.path, "変えた名前")
        assert renamed == vault.root / "変えた名前.md"

    def test_フォルダを指定して作れる(self, vault) -> None:
        """複製がこれを使う（元と同じ場所に作る）。"""
        note = vault.create("新しいメモ", folder=vault.root / "仕事")
        assert note.path == vault.root / "仕事" / "新しいメモ.md"

    def test_vaultの外には作らせない(self, vault) -> None:
        """**保管フォルダの外へ書かない。** 渡し間違いを黙って通さない。"""
        with pytest.raises(ValueError):
            vault.create("外のメモ", folder=vault.root.parent)


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

    def test_古いノートを今日捨てても期限まで残る(self, vault) -> None:
        """期限は「捨ててから」数える。「最後に編集してから」ではない。

        rename は mtime を変えないので、書いてから 30 日以上経った
        ノートを捨てると次回起動で即座に完全削除されていた（回帰）。
        """
        import os
        import time

        note = vault.create("昔書いたメモ")
        old = time.time() - 40 * 24 * 3600
        os.utime(note.path, (old, old))

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


class TestDeletePermanentlyGuard:
    """完全削除はゴミ箱の中だけ（G-3 の安全弁）。"""

    def test_ゴミ箱の外を指す相対パスは消せない(self, vault) -> None:
        """`.trash/../メモ.md` は parents に .trash を含むため字句判定を
        通過し、vault 直下の実体が消えていた（回帰）。"""
        import pytest

        note = vault.create("残るメモ")
        vault.trash(vault.create("ダミー").path)  # .trash を作る
        sneaky = vault.trash_dir / ".." / note.path.name

        with pytest.raises(ValueError):
            vault.delete_permanently(sneaky)
        assert note.path.exists()


class TestScanSymlinkLoop:
    def test_中を指すディレクトリリンクで無限に潜らない(self, vault) -> None:
        """`vault/loop -> vault` のような自己参照リンクは `_inside()` が
        True を返すため辿ってしまい、再帰が止まらなかった（回帰）。"""
        note = vault.create("メモ")
        (vault.root / "loop").symlink_to(vault.root, target_is_directory=True)

        found = list(vault.scan())
        # リンクを辿った先の `loop/メモ.md` `loop/loop/メモ.md` … が
        # 重複して出てはいけない。同じ実体は 1 回だけ
        assert found == [note.path]


class TestEmptyTrashWithDirectories:
    def test_手で入れたフォルダも消える(self, vault) -> None:
        """empty_trash がファイルしか見ず、Finder で .trash に入れた
        フォルダが永久に残っていた（回帰）。「空にする」と言った以上は空にする。"""
        vault.trash(vault.create("メモ").path)
        stray = vault.trash_dir / "手で入れた"
        stray.mkdir()
        (stray / "中身.txt").write_text("x", encoding="utf-8")

        removed = vault.empty_trash()
        assert list(vault.trash_dir.iterdir()) == []
        assert stray in removed


class TestSweepTempFiles:
    """クラッシュで残った一時ファイルの掃除（H-1 層 1）。"""

    def stale(self, path: Path) -> Path:
        import os
        import time

        path.write_text("残骸", encoding="utf-8")
        old = time.time() - 2 * 3600
        os.utime(path, (old, old))
        return path

    def test_古い孤児を消す(self, vault) -> None:
        vault.ensure_layout()
        orphan = self.stale(vault.root / ".メモ.md.abc123.tmp")
        assert vault.sweep_temp_files() == [orphan]
        assert not orphan.exists()

    def test_書き込み中かもしれない新しいものは残す(self, vault) -> None:
        """別マシンが同期越しに同じ vault を触っている場合の保険。"""
        vault.ensure_layout()
        fresh = vault.root / ".メモ.md.def456.tmp"
        fresh.write_text("書き込み中", encoding="utf-8")
        assert vault.sweep_temp_files() == []
        assert fresh.exists()

    def test_サブフォルダの孤児も消す(self, vault) -> None:
        vault.ensure_layout()
        nested = vault.root / "仕事"
        nested.mkdir()
        orphan = self.stale(nested / ".資料.md.xyz.tmp")
        vault.sweep_temp_files()
        assert not orphan.exists()

    def test_旧形式の固定名の残骸も消す(self, vault) -> None:
        vault.ensure_layout()
        legacy = self.stale(vault.root / "メモ.md.tmp")
        vault.sweep_temp_files()
        assert not legacy.exists()

    def test_ノートは触らない(self, vault) -> None:
        note = vault.create("大事なメモ")
        vault.sweep_temp_files()
        assert note.path.exists()


class TestCreateIdentity:
    """create は**新しいノートを作る**。持ち込まれた front matter が
    ULID を乗っ取ってはいけない（コードレビュー指摘 / 回帰）。"""

    def test_持ち込んだidは新しいULIDに置き換わる(self, vault) -> None:
        source = vault.create("元ノート", "本文\n")
        text = source.path.read_text(encoding="utf-8")

        copy = vault.create("写し", text)
        assert copy.id is not None
        assert copy.id != source.id, "複製が元の ULID を引き継いでいる"

    def test_id以外のメタは持ち込める(self, vault) -> None:
        note = vault.create("旗つき", "---\npinned: true\n---\n本文\n")
        assert note.pinned is True


class TestRegisterTemplate:
    """ノートをテンプレートとして登録する（ユーザー要望）。

    一覧の右クリック → テンプレートに登録。以後 Cmd+Shift+N の一覧に出る。
    """

    def test_templatesに入り一覧に出る(self, vault) -> None:
        note = vault.create("議事録", "# 議事録\n\n- 日時: {{date}}\n")
        target = vault.register_template(note.path, "会議の雛形")
        assert target.parent == vault.templates_dir
        assert target.stem == "会議の雛形"
        assert target in vault.templates()

    def test_front_matterは持ち込まない(self, vault) -> None:
        """id を写すと、この雛形から作るノートに管理情報が紛れ込む。"""
        note = vault.create("元", "# 元\n\n本文\n")
        target = vault.register_template(note.path, "雛形")
        text = target.read_text(encoding="utf-8")
        assert "id:" not in text
        assert "本文" in text
        # 見出しは {{title}} へ（同梱の雛形と同じ流儀）。元の題名のままだと
        # この雛形から作るノートが全部「元」になる
        assert "# {{title}}" in text

    def test_同名は上書きしない(self, vault) -> None:
        import pytest as _pytest

        note = vault.create("元", "# 元\n\n一回目\n")
        vault.register_template(note.path, "雛形")
        with _pytest.raises(FileExistsError):
            vault.register_template(note.path, "雛形")

    def test_上書きを明示すれば置き換える(self, vault) -> None:
        note = vault.create("元", "# 元\n\n一回目\n")
        vault.register_template(note.path, "雛形")
        note2 = vault.create("次", "# 次\n\n二回目\n")
        target = vault.register_template(note2.path, "雛形", overwrite=True)
        assert "二回目" in target.read_text(encoding="utf-8")

    def test_登録した雛形から作れる(self, vault) -> None:
        """往復の確認。プレースホルダも生きている。"""
        from datetime import datetime

        note = vault.create("日誌のもと", "# 日誌のもと\n\n- 日付: {{date}}\n")
        target = vault.register_template(note.path, "日誌")
        created = vault.create_from_template(target, now=datetime(2026, 8, 20))
        assert created.note.title == "日誌"
        assert "2026-08-20" in created.note.text

    def test_保管フォルダの外は拒む(self, vault, tmp_path) -> None:
        import pytest as _pytest

        outsider = tmp_path / "外.md"
        outsider.write_text("# 外\n", encoding="utf-8")
        with _pytest.raises(ValueError):
            vault.register_template(outsider, "雛形")


class TestDeleteTemplate:
    """テンプレートの削除（ユーザー要望）。"""

    def test_消せる(self, vault) -> None:
        note = vault.create("元", "# 元\n\n本文\n")
        target = vault.register_template(note.path, "使い捨て")
        vault.delete_template(target)
        assert target not in vault.templates()
        assert not target.exists()

    def test_templates以外は拒む(self, vault) -> None:
        import pytest as _pytest

        note = vault.create("本物", "# 本物\n\n本文\n")
        with _pytest.raises(ValueError):
            vault.delete_template(note.path)
        assert note.path.exists()


class TestWritableFolderGuards:
    """書き込み先ガードの強化（コードレビュー指摘）。

    「保管フォルダの外」だけでなく、予約フォルダ（.trash / .hitofude /
    templates / attachments）も弾く。生きたノートがそこへ入ると、走査
    （scan）から見えない迷子になる。
    """

    @pytest.mark.parametrize("reserved", [".trash", ".hitofude", "templates", "attachments"])
    def test_予約フォルダには作れない(self, vault, reserved) -> None:
        with pytest.raises(ValueError):
            vault.create("迷子", "# 迷子\n", folder=vault.root / reserved)

    def test_予約フォルダの子孫も弾く(self, vault) -> None:
        with pytest.raises(ValueError):
            vault.create("迷子", "# 迷子\n", folder=vault.root / ".hitofude" / "history")

    def test_renameは保管フォルダの外を弾く(self, vault, tmp_path) -> None:
        outsider = tmp_path / "外.md"
        outsider.write_text("# 外\n", encoding="utf-8")
        with pytest.raises(ValueError):
            vault.rename(outsider, "新しい名前")

    def test_ゴミ箱の中のrenameは通る(self, vault) -> None:
        """ゴミ箱のノートの見出し編集で使う経路。塞がない。"""
        note = vault.create("捨てる", "# 捨てる\n")
        trashed = vault.trash(note.path)
        renamed = vault.rename(trashed, "改名後")
        assert renamed.parent == vault.trash_dir


class TestMoveNote:
    """ノートをフォルダへ移す（K-3 / ADR-0024）。"""

    def test_既存のフォルダへ移せる(self, vault) -> None:
        note = vault.create("会議メモ", "# 会議メモ\n\n本文\n")
        (vault.root / "仕事").mkdir()
        moved = vault.move_note(note.path, "仕事")
        assert moved == vault.root / "仕事" / "会議メモ.md"
        assert moved.exists() and not note.path.exists()

    def test_新しいフォルダはその場で作られる(self, vault) -> None:
        note = vault.create("メモ", "# メモ\n")
        moved = vault.move_note(note.path, "新規/2026")
        assert moved.parent == vault.root / "新規" / "2026"

    def test_直下へ戻せる(self, vault) -> None:
        (vault.root / "仕事").mkdir(parents=True)
        path = vault.root / "仕事" / "メモ.md"
        path.write_text("# メモ\n", encoding="utf-8")
        moved = vault.move_note(path, "")
        assert moved == vault.root / "メモ.md"

    def test_同名があれば連番を付ける(self, vault) -> None:
        note = vault.create("メモ", "# メモ\n")
        (vault.root / "仕事").mkdir()
        (vault.root / "仕事" / "メモ.md").write_text("# 先客\n", encoding="utf-8")
        moved = vault.move_note(note.path, "仕事")
        assert moved.name == "メモ-2.md"

    def test_本文は変わらない(self, vault) -> None:
        """R1: 添付リンクは vault ルート基準で解決するので書き換え不要。"""
        note = vault.create("絵入り", "# 絵入り\n\n![](attachments/a.png)\n")
        moved = vault.move_note(note.path, "仕事")
        assert "![](attachments/a.png)" in moved.read_text(encoding="utf-8")

    def test_予約フォルダへは移せない(self, vault) -> None:
        note = vault.create("メモ", "# メモ\n")
        for reserved in (".trash", ".hitofude", "templates", "attachments"):
            with pytest.raises(ValueError):
                vault.move_note(note.path, reserved)

    def test_保管フォルダの外のノートは拒む(self, vault, tmp_path) -> None:
        outsider = tmp_path / "外.md"
        outsider.write_text("# 外\n", encoding="utf-8")
        with pytest.raises(ValueError):
            vault.move_note(outsider, "仕事")

    def test_フォルダ名は掃除される(self, vault) -> None:
        note = vault.create("メモ", "# メモ\n")
        moved = vault.move_note(note.path, " 仕事 / 2026 ")
        assert moved.parent == vault.root / "仕事" / "2026"

    def test_空になった元フォルダは残る(self, vault) -> None:
        """**フォルダは消さない**（ユーザー決定 / ADR-0024 追記 2）。

        フォルダは作るもの・管理するものになったので、最後のノートを
        移しただけで消えると「勝手に無くなった」になる。
        """
        path = vault.root / "古い" / "深い" / "メモ.md"
        path.parent.mkdir(parents=True)
        path.write_text("# メモ\n", encoding="utf-8")
        vault.move_note(path, "")
        assert (vault.root / "古い" / "深い").is_dir()

    def test_中身が残る元フォルダは消えない(self, vault) -> None:
        keep = vault.root / "古い" / "残る.md"
        keep.parent.mkdir(parents=True)
        keep.write_text("# 残る\n", encoding="utf-8")
        path = vault.root / "古い" / "メモ.md"
        path.write_text("# メモ\n", encoding="utf-8")
        vault.move_note(path, "")
        assert keep.exists() and keep.parent.is_dir()


class TestTrashKeepsFolder:
    """ゴミ箱の中でも階層を保つ（K-5）。

    ゴミ箱は平らだったので、戻すと全部 vault 直下に出ていた。
    真実をファイル側に置いたまま（R1 の精神）、.trash/ の中に同じ階層を
    作れば「誰がどこにいたか」をファイル自身が覚えている。
    """

    def foldered_note(self, vault, relative="仕事/2026/会議メモ.md"):
        path = vault.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")
        return path

    def test_捨てると階層ごと入る(self, vault) -> None:
        path = self.foldered_note(vault)
        trashed = vault.trash(path)
        assert trashed == vault.trash_dir / "仕事" / "2026" / "会議メモ.md"

    def test_戻すと元のフォルダに戻る(self, vault) -> None:
        path = self.foldered_note(vault)
        trashed = vault.trash(path)
        restored = vault.restore(trashed)
        assert restored == vault.root / "仕事" / "2026" / "会議メモ.md"

    def test_元のフォルダが消えていても作り直して戻す(self, vault) -> None:
        path = self.foldered_note(vault, "古い/メモ.md")
        trashed = vault.trash(path)
        (vault.root / "古い").rmdir()  # 手で消した想定（フォルダは自動では消えない）
        restored = vault.restore(trashed)
        assert restored == vault.root / "古い" / "メモ.md"

    def test_直下のノートは今まで通り(self, vault) -> None:
        note = vault.create("直下", "# 直下\n")
        trashed = vault.trash(note.path)
        assert trashed.parent == vault.trash_dir
        assert vault.restore(trashed).parent == vault.root

    def test_古い平らなゴミ箱の中身も直下へ戻せる(self, vault) -> None:
        """K-5 より前に捨てたもの（.trash 直下）の互換。"""
        vault.ensure_layout()
        vault.trash_dir.mkdir(parents=True, exist_ok=True)
        old = vault.trash_dir / "昔の.md"
        old.write_text("# 昔の\n", encoding="utf-8")
        assert vault.restore(old).parent == vault.root

    def test_期限切れの掃除は階層の中も見る(self, vault) -> None:
        import os as _os
        import time as _time

        path = self.foldered_note(vault)
        trashed = vault.trash(path)
        stale = _time.time() - 40 * 24 * 3600
        _os.utime(trashed, (stale, stale))
        removed = vault.purge_trash(30)
        assert trashed in removed
        assert not (vault.trash_dir / "仕事").exists()  # 空になった殻も残さない

    def test_空にするは階層ごと消す(self, vault) -> None:
        path = self.foldered_note(vault)
        vault.trash(path)
        vault.empty_trash()
        assert list(vault.trash_dir.iterdir()) == []

    def test_戻したあとのゴミ箱に殻を残さない(self, vault) -> None:
        path = self.foldered_note(vault)
        trashed = vault.trash(path)
        vault.restore(trashed)
        assert not (vault.trash_dir / "仕事").exists()


class TestCreateFolder:
    """フォルダを作る（ユーザー要望。ADR-0024 の「移動の副産物としてのみ」を広げる）。"""

    def test_直下に作れる(self, vault) -> None:
        created = vault.create_folder("日報")
        assert created == vault.root / "日報"
        assert created.is_dir()

    def test_フォルダの中に作れる(self, vault) -> None:
        vault.create_folder("仕事")
        created = vault.create_folder("仕事/2026")
        assert created == vault.root / "仕事" / "2026"

    def test_名前は掃除される(self, vault) -> None:
        created = vault.create_folder(" 日報 / 2026 ")
        assert created == vault.root / "日報" / "2026"

    def test_同じ名前があれば拒む(self, vault) -> None:
        vault.create_folder("日報")
        with pytest.raises(FileExistsError):
            vault.create_folder("日報")

    def test_予約フォルダは作れない(self, vault) -> None:
        for reserved in (".trash", ".hitofude", "templates", "attachments"):
            with pytest.raises(ValueError):
                vault.create_folder(reserved)

    def test_空の名前は拒む(self, vault) -> None:
        with pytest.raises(ValueError):
            vault.create_folder("   ")


class TestFolderList:
    """フォルダの一覧はディスクから引く（空フォルダも見せるため）。"""

    def test_空のフォルダも並ぶ(self, vault) -> None:
        vault.create_folder("空っぽ")
        assert "空っぽ" in vault.folders()

    def test_入れ子は全階層が出る(self, vault) -> None:
        vault.create_folder("仕事/2026/期末")
        found = vault.folders()
        assert found == ["仕事", "仕事/2026", "仕事/2026/期末"]

    def test_予約フォルダと隠しフォルダは出さない(self, vault) -> None:
        vault.ensure_layout()
        (vault.root / ".obsidian").mkdir(parents=True, exist_ok=True)
        found = vault.folders()
        for hidden in (".trash", ".hitofude", "templates", "attachments", ".obsidian"):
            assert hidden not in found

    def test_ノートが入っているフォルダも出る(self, vault) -> None:
        path = vault.root / "仕事" / "メモ.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# メモ\n", encoding="utf-8")
        assert "仕事" in vault.folders()


class TestFoldersSurvive:
    """フォルダは空になっても残す（ユーザー決定 / ADR-0024 追記 2）。"""

    def test_ノートを捨てても元フォルダは残る(self, vault) -> None:
        path = vault.root / "日報" / "2026" / "メモ.md"
        path.parent.mkdir(parents=True)
        path.write_text("# メモ\n", encoding="utf-8")
        vault.trash(path)
        assert (vault.root / "日報" / "2026").is_dir()

    def test_ゴミ箱の中の殻は今まで通り片づける(self, vault) -> None:
        """こちらは目に見えない裏側なので、空の階層を残さない。"""
        path = vault.root / "仕事" / "メモ.md"
        path.parent.mkdir(parents=True)
        path.write_text("# メモ\n", encoding="utf-8")
        trashed = vault.trash(path)
        vault.restore(trashed)
        assert not (vault.trash_dir / "仕事").exists()


class TestDeleteFolder:
    """フォルダを消す（残る仕様にした分、消す手段を用意する）。"""

    def test_空のフォルダを消せる(self, vault) -> None:
        vault.create_folder("空っぽ")
        vault.delete_folder("空っぽ")
        assert not (vault.root / "空っぽ").exists()

    def test_中が空フォルダだけなら消せる(self, vault) -> None:
        vault.create_folder("親/子/孫")
        vault.delete_folder("親")
        assert not (vault.root / "親").exists()

    def test_ノートが入っていたら消さない(self, vault) -> None:
        path = vault.root / "仕事" / "メモ.md"
        path.parent.mkdir(parents=True)
        path.write_text("# メモ\n", encoding="utf-8")
        with pytest.raises(ValueError):
            vault.delete_folder("仕事")
        assert path.exists()

    def test_DS_Storeは無視して消せる(self, vault) -> None:
        vault.create_folder("掃除")
        (vault.root / "掃除" / ".DS_Store").write_bytes(b"x")
        vault.delete_folder("掃除")
        assert not (vault.root / "掃除").exists()

    def test_予約フォルダは消せない(self, vault) -> None:
        vault.ensure_layout()
        for reserved in (".trash", ".hitofude", "templates", "attachments"):
            with pytest.raises(ValueError):
                vault.delete_folder(reserved)
        assert vault.trash_dir.exists()

    def test_無いフォルダは拒む(self, vault) -> None:
        with pytest.raises(ValueError):
            vault.delete_folder("存在しない")


class TestTrashBoundary:
    """**vault の外のファイルを動かさない**（コードレビュー指摘 / 高）。

    `delete_permanently` には境界の検査があるのに、捨てる・戻すには無かった。
    呼び出し側の誤りや、これから足す機能が**ユーザーの任意のファイルを
    黙って移動できてしまう**。
    """

    def test_外のファイルは捨てられない(self, vault, tmp_path) -> None:
        outside = tmp_path / "外の大事なファイル.md"
        outside.write_text("# 大事\n", encoding="utf-8")
        with pytest.raises(ValueError):
            vault.trash(outside)
        assert outside.exists(), "外のファイルが動いた"

    def test_中のノートは今まで通り捨てられる(self, vault) -> None:
        note = vault.create("捨てる", "# 捨てる\n")
        moved = vault.trash(note.path)
        assert moved.is_relative_to(vault.trash_dir)

    def test_ゴミ箱の外からは戻せない(self, vault, tmp_path) -> None:
        outside = tmp_path / "よそのファイル.md"
        outside.write_text("# よそ\n", encoding="utf-8")
        with pytest.raises(ValueError):
            vault.restore(outside)
        assert outside.exists(), "外のファイルが動いた"

    def test_vaultの中でもゴミ箱の外からは戻せない(self, vault) -> None:
        """**「戻す」はゴミ箱からの操作。** 普通のノートを二重に動かさない。"""
        note = vault.create("普通のノート", "# 普通のノート\n")
        with pytest.raises(ValueError):
            vault.restore(note.path)
        assert note.path.exists()

    def test_ゴミ箱の中は今まで通り戻せる(self, vault) -> None:
        note = vault.create("戻す", "# 戻す\n")
        moved = vault.trash(note.path)
        back = vault.restore(moved)
        assert back.is_relative_to(vault.root)
        assert not back.is_relative_to(vault.trash_dir)


class TestScanSurvivesUnreadable:
    """読めないフォルダが 1 つあっても走査を止めない（コードレビュー指摘 / 中）。

    索引の同期はまるごと 1 回の処理なので、**途中で例外が出ると他の正常な
    ノートまで索引に入らない**。`folders()` は既にディレクトリ単位で
    握りつぶしている。走査もそれに揃える。
    """

    def test_読めないフォルダを飛ばして続ける(self, vault) -> None:
        vault.ensure_layout()
        good = vault.root / "読める"
        good.mkdir()
        (good / "ノート.md").write_text("# ノート\n", encoding="utf-8")
        blocked = vault.root / "読めない"
        blocked.mkdir()
        (blocked / "隠れたノート.md").write_text("# 隠れた\n", encoding="utf-8")
        blocked.chmod(0o000)
        try:
            found = [path.name for path in vault.scan()]
        finally:
            blocked.chmod(0o755)  # 後片づけ（消せなくなる）
        assert "ノート.md" in found

    def test_根が読めなければ空(self, vault) -> None:
        """**落ちない。** 読めないなら 0 件として扱う。"""
        vault.ensure_layout()
        vault.root.chmod(0o000)
        try:
            found = list(vault.scan())
        finally:
            vault.root.chmod(0o755)
        assert found == []


class TestRenameFolder:
    """フォルダの名前を変える（ユーザー要望 2026-08-22）。

    **中身ごと動かさない。** ディレクトリの名前を変えるだけなので、
    中のノートは 1 バイトも触らない（front matter も履歴の鍵も無傷）。
    """

    def prepared(self, vault):
        vault.ensure_layout()
        vault.create_folder("仕事")
        note = vault.create("会議", "# 会議\n\n本文\n", folder=vault.root / "仕事")
        return note

    def test_名前が変わる(self, vault) -> None:
        self.prepared(vault)
        moved = vault.rename_folder("仕事", "業務")
        assert moved == vault.root / "業務"
        assert not (vault.root / "仕事").exists()

    def test_中のノートはそのまま(self, vault) -> None:
        note = self.prepared(vault)
        before = note.path.read_text(encoding="utf-8")
        vault.rename_folder("仕事", "業務")
        assert (vault.root / "業務" / note.path.name).read_text(encoding="utf-8") == before

    def test_親は変わらない(self, vault) -> None:
        """**動かすのではなく名前を変える。** 深いところのフォルダも同じ。"""
        vault.ensure_layout()
        vault.create_folder("仕事/2026")
        moved = vault.rename_folder("仕事/2026", "2027")
        assert moved == vault.root / "仕事" / "2027"

    def test_使えない文字は直す(self, vault) -> None:
        self.prepared(vault)
        moved = vault.rename_folder("仕事", "業務/2026")
        assert moved.parent == vault.root
        assert "/" not in moved.name

    def test_空の名前は断る(self, vault) -> None:
        self.prepared(vault)
        with pytest.raises(ValueError):
            vault.rename_folder("仕事", "   ")

    def test_同じ名前が既にあれば断る(self, vault) -> None:
        """**混ぜない。** 黙って中身が合流すると、どちらのノートか分からなくなる。"""
        self.prepared(vault)
        vault.create_folder("業務")
        with pytest.raises(FileExistsError):
            vault.rename_folder("仕事", "業務")
        assert (vault.root / "仕事").is_dir()

    def test_予約フォルダは変えられない(self, vault) -> None:
        vault.ensure_layout()
        with pytest.raises(ValueError):
            vault.rename_folder(".trash", "ごみ")

    def test_無いフォルダは断る(self, vault) -> None:
        vault.ensure_layout()
        with pytest.raises(ValueError):
            vault.rename_folder("無い", "ある")

    def test_同じ名前なら何もしない(self, vault) -> None:
        self.prepared(vault)
        assert vault.rename_folder("仕事", "仕事") == vault.root / "仕事"
