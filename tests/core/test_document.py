"""ノートのモデルのテスト（spec §7.2, §7.3）。"""

from pathlib import Path

import pytest

from hitofude.core.document import Note, new_id, preview_of, title_of, with_title


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


class TestPreviewMarkers:
    """一覧のプレビューは**記号を外して出す**（ユーザー報告）。

    本文では `**` を隠しているのに、一覧には `**書き方の見本**` と
    そのまま出ていた。同じ文章の見え方が場所によって変わるのは筋が悪い。

    索引に入れる本文（`searchable_text`）と同じ判断に立つ。
    装飾は文章の一部ではない。
    """

    def test_強調の記号を外す(self) -> None:
        assert preview_of("**書き方の見本**にもなります\n") == "書き方の見本にもなります"

    def test_斜体とコードも外す(self) -> None:
        assert preview_of("*斜体* と `コード`\n") == "斜体 と コード"

    def test_リンクは文字だけ残す(self) -> None:
        assert preview_of("[仕様](https://example.com)を見る\n") == "仕様を見る"

    def test_行頭のマーカーも外す(self) -> None:
        assert preview_of("- 箇条書き\n> 引用\n") == "箇条書き 引用"

    def test_コードブロックは記号ごと残す(self) -> None:
        """検索と同じ扱い。コードは書いたままが読みたい。"""
        assert "**" in preview_of("```\n**そのまま**\n```\n")

    def test_H1は今まで通り落とす(self) -> None:
        assert preview_of("# **見出し**\n\n本文\n") == "本文"

    def test_元の文字列を変えない(self) -> None:
        text = "**強調**\n"
        preview_of(text)
        assert text == "**強調**\n"


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


class TestWithTitle:
    """タイトルを付け替える（タスク A-3）。

    タイトルは本文から導かれる（`title_of`）ので、**本文を書き換える**のが
    唯一の付け替え方。ファイル名だけ変えても一覧の表示は変わらない。
    `title_of` の探し方をそのまま裏返した実装になる。
    """

    def test_H1を書き換える(self) -> None:
        assert with_title("# 元の題\n\n本文\n", "新しい題") == "# 新しい題\n\n本文\n"

    def test_書き換えた結果がタイトルになる(self) -> None:
        got = with_title("# 元の題\n\n本文\n", "新しい題")
        assert title_of(got, "fallback") == "新しい題"

    def test_本文は変わらない(self) -> None:
        got = with_title("# 元の題\n\n**強調** と `コード`\n", "新しい題")
        assert "**強調** と `コード`" in got

    def test_後ろにあるH1でも書き換える(self) -> None:
        """`title_of` は文書のどこにある H1 でも拾う。裏返しも同じ。"""
        got = with_title("前置き\n\n# 元の題\n\n本文\n", "新しい題")
        assert title_of(got, "fallback") == "新しい題"
        assert got.startswith("前置き")

    def test_H2しか無ければH2を書き換える(self) -> None:
        """見出しの深さは保つ。文書の構造を勝手に変えない。"""
        got = with_title("## 元の題\n\n本文\n", "新しい題")
        assert got == "## 新しい題\n\n本文\n"

    def test_見出しが無ければH1を足す(self) -> None:
        """段落を書き換えると文章が消える。上に足すだけなら何も失わない。"""
        got = with_title("ただの段落です。\n", "新しい題")
        assert got == "# 新しい題\n\nただの段落です。\n"
        assert "ただの段落です。" in got

    def test_箇条書きだけのノートにも足せる(self) -> None:
        got = with_title("- りんご\n- みかん\n", "買い物")
        assert title_of(got, "fallback") == "買い物"
        assert "- りんご" in got

    def test_空のノートにも付けられる(self) -> None:
        assert title_of(with_title("", "新しい題"), "fallback") == "新しい題"

    def test_front_matterを保つ(self) -> None:
        source = "---\nid: ABC123\n---\n# 元の題\n\n本文\n"
        got = with_title(source, "新しい題")
        assert got.startswith("---\nid: ABC123\n---\n")
        assert title_of(got, "fallback") == "新しい題"

    def test_front_matterが無ければ足さない(self) -> None:
        assert not with_title("# 元の題\n", "新しい題").startswith("---")

    def test_壊れたfront_matterを消さない(self) -> None:
        """メタデータが壊れていても本文（とメタデータ自身）は必ず残す。

        壊れた YAML は `split()` が `meta={}` にするため、再ダンプ経由だと
        front matter が丸ごと消えていた（回帰）。タイトル変更のたびに
        発火しうるデータ喪失。
        """
        source = "---\n[broken yaml: [\n---\n# 元の題\n\n本文\n"
        got = with_title(source, "新しい題")
        assert got.startswith("---\n[broken yaml: [\n---\n")
        assert title_of(got, "fallback") == "新しい題"

    def test_空のfront_matterを消さない(self) -> None:
        source = "---\n---\n# 元の題\n\n本文\n"
        got = with_title(source, "新しい題")
        assert got.startswith("---\n---\n")

    def test_front_matterの書式を保つ(self) -> None:
        """YAML を再ダンプするとコメント・引用符・並びが失われ、
        タイトルを変えるたびに無関係な diff が出る（G3 に反する）。"""
        source = "---\n# 管理情報\nid: 'ABC123'\n---\n# 元の題\n"
        got = with_title(source, "新しい題")
        assert got.startswith("---\n# 管理情報\nid: 'ABC123'\n---\n")

    def test_コードブロックの中の見出しは書き換えない(self) -> None:
        source = "```\n# コードの中\n```\n\n# 元の題\n"
        got = with_title(source, "新しい題")
        assert "# コードの中" in got
        assert title_of(got, "fallback") == "新しい題"

    def test_空の題は何もしない(self) -> None:
        source = "# 元の題\n\n本文\n"
        assert with_title(source, "   ") == source

    def test_同じ題なら変わらない(self) -> None:
        source = "# 元の題\n\n本文\n"
        assert with_title(source, "元の題") == source

    def test_記号を含む題も入る(self) -> None:
        got = with_title("# 元の題\n", "a/b: c *d*")
        assert title_of(got, "fallback") == "a/b: c *d*"

    def test_改行は入れさせない(self) -> None:
        """1 行の見出しなので、改行が入ると別の行になってしまう。"""
        got = with_title("# 元の題\n", "上\n下")
        assert got.count("\n") == 1

    def test_2回かけても同じ(self) -> None:
        once = with_title("ただの段落です。\n", "題")
        assert with_title(once, "題") == once
