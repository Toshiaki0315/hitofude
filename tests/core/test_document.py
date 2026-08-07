"""ノートのモデルのテスト（spec §7.2, §7.3）。"""

from pathlib import Path

import pytest

from hitofude.core.document import Note, new_id, preview_of, title_of


class TestTitle:
    """spec §7.2: 最初の H1 → 無ければ最初の非空行 → 無ければファイル名。"""

    def test_最初のH1を使う(self) -> None:
        assert title_of("# 会議メモ\n\n本文\n", "既定") == "会議メモ"

    def test_front_matterは飛ばす(self) -> None:
        text = "---\nid: 1\n---\n\n# 会議メモ\n"
        assert title_of(text, "既定") == "会議メモ"

    def test_H1が無ければ最初の非空行(self) -> None:
        assert title_of("\n\nただの本文\n\nもう一行\n", "既定") == "ただの本文"

    def test_後ろにあるH1でも優先される(self) -> None:
        """spec §7.2 は「最初の H1 → **無ければ** 最初の非空行」の順。

        位置ではなく種類が優先される。H1 はその文書の題名だという扱い。
        """
        assert title_of("前置きの文\n\n# 本当の見出し\n", "既定") == "本当の見出し"

    def test_行頭マーカーは落とす(self) -> None:
        """`- 項目` がそのままタイトルになるとノート一覧が読みにくい。"""
        assert title_of("- 項目\n", "既定") == "項目"
        assert title_of("> 引用\n", "既定") == "引用"
        assert title_of("## 小見出し\n", "既定") == "小見出し"

    def test_本文が空ならファイル名(self) -> None:
        assert title_of("", "無題") == "無題"
        assert title_of("\n\n   \n", "無題") == "無題"

    def test_H2以降より前のH1を優先する(self) -> None:
        assert title_of("## 先に出る小見出し\n\n# 本当の見出し\n", "既定") == "本当の見出し"

    def test_コードフェンス内のH1は使わない(self) -> None:
        assert title_of("```\n# コードの中\n```\n\n実際の本文\n", "既定") == "実際の本文"


class TestPreview:
    """spec §7.3: 本文先頭 200 文字（front matter / H1 を除く）。"""

    def test_H1を除いた本文を返す(self) -> None:
        assert preview_of("# 見出し\n\n本文です。\n") == "本文です。"

    def test_front_matterを除く(self) -> None:
        assert preview_of("---\nid: 1\n---\n\n本文です。\n") == "本文です。"

    def test_改行は空白にまとめる(self) -> None:
        assert preview_of("一行目\n二行目\n\n三行目\n") == "一行目 二行目 三行目"

    def test_長さで切る(self) -> None:
        assert len(preview_of("あ" * 500)) == 200

    def test_本文が無ければ空(self) -> None:
        assert preview_of("# 見出しだけ\n") == ""


class TestNote:
    def make(self, text: str, name: str = "メモ.md") -> Note:
        return Note.from_text(Path(f"/vault/{name}"), text, mtime_ns=1, size_bytes=len(text))

    def test_本文と派生情報を持つ(self) -> None:
        note = self.make("---\nid: ABC\n---\n\n# 会議メモ\n\n本文 #work\n")
        assert note.title == "会議メモ"
        assert note.preview == "本文 #work"
        assert note.tags == ["work"]
        assert note.id == "ABC"

    def test_front_matterが無くても壊れない(self) -> None:
        note = self.make("# 会議メモ\n")
        assert note.title == "会議メモ"
        assert note.id is None

    def test_タイトルが無ければファイル名(self) -> None:
        assert self.make("", "買い物リスト.md").title == "買い物リスト"

    def test_ダイジェストは内容で決まる(self) -> None:
        """spec §7.5: 競合検知に使う。"""
        assert self.make("同じ").digest == self.make("同じ").digest
        assert self.make("あ").digest != self.make("い").digest

    def test_イミュータブル(self) -> None:
        import dataclasses

        with pytest.raises(dataclasses.FrozenInstanceError):
            self.make("x").text = "y"  # type: ignore[misc]

    def test_ピン留めを読む(self) -> None:
        assert self.make("---\npinned: true\n---\n本文\n").pinned is True
        assert self.make("本文\n").pinned is False


class TestNewId:
    """spec §7.2: ULID。ファイル名変更に耐える永続 ID。"""

    def test_26文字のULID(self) -> None:
        assert len(new_id()) == 26

    def test_使う文字はCrockfordBase32(self) -> None:
        assert set(new_id()) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    def test_毎回異なる(self) -> None:
        assert len({new_id() for _ in range(500)}) == 500

    def test_時刻順に並ぶ(self) -> None:
        """ULID は辞書順が生成順と一致する。ノートの既定並び順に使える。"""
        import time

        first = new_id()
        time.sleep(0.005)
        assert first < new_id()
