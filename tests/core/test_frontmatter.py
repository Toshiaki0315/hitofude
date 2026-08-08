"""YAML front matter の分離と再結合のテスト（タスク 1-2 / spec §7.2）。

front matter は**任意**。無くても壊れずに開けることが最優先で、
不正な YAML でもノートを人質に取らない（本文は必ず返す）。
"""

import pytest

from hitofude.core.frontmatter import FrontMatter, body_offset, join, split

BASIC = """---
id: 01J9XQ2F8K7M3N5P
pinned: false
---

# 会議メモ

本文。
"""


class TestSplit:
    def test_front_matterを辞書として取り出す(self) -> None:
        fm = split(BASIC)
        assert fm.meta == {"id": "01J9XQ2F8K7M3N5P", "pinned": False}

    def test_本文はfront_matterを除いた残り(self) -> None:
        fm = split(BASIC)
        assert fm.body.startswith("\n# 会議メモ")
        assert "id:" not in fm.body

    def test_body_offsetから元の文字列を復元できる(self) -> None:
        """ハイライタが「本文の N 文字目」を元テキストの位置へ戻すのに使う。"""
        fm = split(BASIC)
        assert BASIC[fm.body_offset :] == fm.body

    def test_front_matterが無ければ全体が本文(self) -> None:
        text = "# 見出しだけ\n\n本文。\n"
        fm = split(text)
        assert fm.meta == {}
        assert fm.body == text
        assert fm.body_offset == 0
        assert fm.present is False

    def test_空文字列でも壊れない(self) -> None:
        fm = split("")
        assert fm.meta == {}
        assert fm.body == ""
        assert fm.body_offset == 0

    def test_本文中の水平線をfront_matterと誤認しない(self) -> None:
        """`---` は 1 行目に無ければ front matter ではない（ただの水平線）。"""
        text = "# 見出し\n\n---\n\nid: これは本文\n\n---\n"
        fm = split(text)
        assert fm.present is False
        assert fm.body == text

    def test_閉じ区切りが無ければfront_matterとして扱わない(self) -> None:
        text = "---\nid: 1\n\n本文がそのまま続く\n"
        fm = split(text)
        assert fm.present is False
        assert fm.body == text

    def test_不正なYAMLでも本文は失われない(self) -> None:
        """壊れたメタデータのせいでノートが開けなくなるのが最悪の事故。"""
        text = "---\nid: [壊れた\n---\n\n本文は無事。\n"
        fm = split(text)
        assert fm.present is True
        assert fm.meta == {}
        assert fm.invalid is True
        assert fm.body == "\n本文は無事。\n"

    def test_YAMLが辞書でない場合も空の辞書にする(self) -> None:
        text = "---\n- リスト\n- になっている\n---\n本文\n"
        fm = split(text)
        assert fm.meta == {}
        assert fm.invalid is True

    def test_空のfront_matterを許容する(self) -> None:
        text = "---\n---\n本文\n"
        fm = split(text)
        assert fm.present is True
        assert fm.meta == {}
        assert fm.invalid is False
        assert fm.body == "本文\n"

    def test_CRLFを正規化して扱う(self) -> None:
        """spec §7.2: 改行は LF 固定。読み込み時に CRLF を正規化する。"""
        text = "---\r\nid: 1\r\n---\r\n\r\n本文\r\n"
        fm = split(text)
        assert fm.meta == {"id": 1}
        assert "\r" not in fm.body
        assert fm.body == "\n本文\n"

    def test_BOM付きでも読める(self) -> None:
        """spec §7.2: 読み込み時のみ BOM 付きを許容する。"""
        fm = split("﻿---\nid: 1\n---\n本文\n")
        assert fm.meta == {"id": 1}
        assert fm.body == "本文\n"

    def test_区切りの直後に文字があるものは区切りではない(self) -> None:
        text = "----\nid: 1\n---\n本文\n"
        fm = split(text)
        assert fm.present is False


class TestJoin:
    def test_メタデータと本文を結合する(self) -> None:
        result = join({"id": "X"}, "本文\n")
        assert result.startswith("---\n")
        assert "id: X" in result
        assert result.endswith("本文\n")

    def test_メタデータが空なら本文だけを返す(self) -> None:
        assert join({}, "本文\n") == "本文\n"

    def test_ISO8601の日時を文字列のまま往復する(self) -> None:
        """PyYAML の既定は日時を datetime に変換してしまう（回帰テスト）。

        変換されると書き戻しで書式が変わり、**保存のたびにファイルの diff が出る**。
        §3.3 で `toMarkdown()` を却下した理由 4 と同じ事故なので、ここで塞ぐ。
        """
        text = "---\ncreated: 2026-08-07T09:12:00+09:00\n---\n本文\n"
        fm = split(text)
        assert fm.meta["created"] == "2026-08-07T09:12:00+09:00"
        assert isinstance(fm.meta["created"], str)
        assert join(fm.meta, fm.body) == text

    def test_日本語をエスケープしない(self) -> None:
        """`\\u30bf` のような表記でファイルに書かれるとユーザーが読めない。"""
        result = join({"title": "会議メモ"}, "本文\n")
        assert "会議メモ" in result

    @pytest.mark.parametrize(
        "text",
        [
            BASIC,
            "本文だけ\n",
            "---\nid: 1\n---\n本文\n",
        ],
    )
    def test_splitしてjoinすると元に戻る(self, text: str) -> None:
        """往復でファイルが書き換わらないこと。G3 の担保に直結する。"""
        fm = split(text)
        assert join(fm.meta, fm.body) == text


class TestFrontMatter:
    def test_イミュータブルである(self) -> None:
        import dataclasses

        fm = split(BASIC)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fm.body = ""  # type: ignore[misc]

    def test_値の取得にデフォルトを指定できる(self) -> None:
        fm = split(BASIC)
        assert fm.get("pinned", True) is False
        assert fm.get("存在しない", "既定") == "既定"

    def test_FrontMatterは直接構築もできる(self) -> None:
        fm = FrontMatter(meta={}, body="x", body_offset=0)
        assert fm.present is False
        assert fm.invalid is False


class TestBodyOffset:
    """本文の開始位置だけを引く（打鍵のたびに呼ぶので YAML は読まない）。"""

    def test_front_matterの後ろを指す(self) -> None:
        text = "---\nid: ABC\n---\n本文\n"
        assert body_offset(text) == text.index("本文")

    def test_無ければ0(self) -> None:
        assert body_offset("ただの本文\n") == 0

    def test_閉じていなければ0(self) -> None:
        """水平線で始まる本文を front matter と誤認しない。"""
        assert body_offset("---\nid: ABC\n本文\n") == 0

    def test_空でも落ちない(self) -> None:
        assert body_offset("") == 0

    def test_YAMLが壊れていても位置は返す(self) -> None:
        """G3: メタデータが読めないことと、本文の位置は別の話。"""
        text = "---\n: : 壊れた\n---\n本文\n"
        assert body_offset(text) == text.index("本文")

    def test_splitと同じ値になる(self) -> None:
        text = "---\nid: ABC\ncreated: 2026-01-01\n---\n\n# 見出し\n"
        assert body_offset(text) == split(text).body_offset

    def test_CRLFでもsplitと一致する(self) -> None:
        text = "---\r\nid: ABC\r\n---\r\n本文\r\n"
        assert body_offset(text) == split(text).body_offset

    def test_YAMLを読まないので速い(self) -> None:
        """1 万語のノートで打鍵のたびに呼ばれる。"""
        import time

        text = "---\nid: ABC\n---\n" + "本文の行\n" * 5000
        started = time.perf_counter()
        for _ in range(100):
            body_offset(text)
        elapsed = (time.perf_counter() - started) * 1000 / 100
        assert elapsed < 1.0, f"1 回あたり {elapsed:.3f}ms"
