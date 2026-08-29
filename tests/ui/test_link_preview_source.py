"""覗き見に実際のノートを渡す（U-2）。

エディタは vault を知らないので、**窓が題名から中身を引く係**を挿す。
題名の照合は `wikilink.resolve`（リンクを開くのと同じ道）——別に書くと、
開けるのに覗けない／覗けるのに開けないがずれて出る。
"""

import pytest

pytestmark = pytest.mark.gui


class TestSource:
    def test_あるノートの中身を返す(self, window) -> None:
        note = window._vault.create("会議メモ", "# 会議メモ\n\n決めたこと\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        assert "決めたこと" in (window._note_preview("会議メモ") or "")

    def test_無いノートはNone(self, window) -> None:
        assert window._note_preview("まだ無いノート") is None

    def test_表記が違っても引ける(self, window) -> None:
        """**開くのと同じ照合**（大文字小文字・空白の畳み込み）。"""
        note = window._vault.create("Meeting Notes", "# Meeting Notes\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        assert window._note_preview("meeting notes") is not None

    def test_エディタに挿されている(self, window) -> None:
        note = window._vault.create("会議メモ", "# 会議メモ\n\n決めたこと\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.editor._link_preview.set_source(window._note_preview)
        assert window.editor._link_preview._source is not None
