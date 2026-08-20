"""保存すると版が残り、戻せる（提案 6 / ADR-0023）。

保管の作りは `tests/storage/test_history.py`。ここは**アプリのどこから
呼ぶか**（保存の道・起動時の掃除・戻す操作）を見る。
"""

from datetime import datetime, timedelta

import pytest

from hitofude.storage import history
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def versions(window: MainWindow):
    return window.note_versions()


def write_body(window: MainWindow, body: str) -> None:
    """本文だけ書き換える。

    **front matter は消さない。** 実アプリでは隠れていて触れない（ADR-0013）。
    `setPlainText` で丸ごと入れ替えると `id` ごと消えてしまい、履歴の鍵が
    変わって別のノート扱いになる。
    """
    from hitofude.core import frontmatter

    current = window.editor.toPlainText()
    split = frontmatter.split(current)
    head = current[: len(current) - len(split.body)]
    window.editor.setPlainText(head + body)


class TestKeepOnSave:
    def test_保存すると版が残る(self, window) -> None:
        window.new_note()
        write_body(window, "# 会議メモ\n\n一回目の内容\n")
        window.flush()

        assert len(versions(window)) == 1
        assert "一回目の内容" in versions(window)[0].read()

    def test_続けて保存しても増えない(self, window) -> None:
        """**間引く**（ADR-0023）。自動保存は打ち終わって 0.8 秒で走る。"""
        window.new_note()
        write_body(window, "# 会議メモ\n\n一回目\n")
        window.flush()
        write_body(window, "# 会議メモ\n\n二回目\n")
        window.flush()

        assert len(versions(window)) == 1

    def test_名前を変えても続く(self, window) -> None:
        """**id で分ける。** 題名が変わっても履歴が途切れない。"""
        window.new_note()
        write_body(window, "# 最初の名前\n\n本文\n")
        window.flush()
        write_body(window, "# 変えた名前\n\n本文を書き足した\n")
        window.flush()

        assert versions(window)  # 名前が変わっても同じ id の下にある

    def test_開いただけでは残らない(self, window) -> None:
        note = window.vault.create("既にあるメモ", "# 既にあるメモ\n\n本文\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_and_select(note.path)

        assert versions(window) == []


class TestRestore:
    def make_history(self, window: MainWindow) -> None:
        window.new_note()
        write_body(window, "# メモ\n\n古い内容\n")
        window.flush()
        # 間引きを越えるだけ時間を進めた体にする
        window._history_now = lambda: datetime.now() + timedelta(hours=1)
        write_body(window, "# メモ\n\n新しい内容\n")
        window.flush()

    def test_選んだ版に戻せる(self, window) -> None:
        self.make_history(window)
        oldest = versions(window)[-1]

        assert window.restore_version(oldest) is True
        assert "古い内容" in window.editor.toPlainText()

    def test_戻す前の内容も版に残る(self, window) -> None:
        """**戻す操作も取り消せる。** 取り消せない操作を増やさない。"""
        self.make_history(window)
        oldest = versions(window)[-1]

        window.restore_version(oldest)
        assert any("新しい内容" in version.read() for version in versions(window))

    def test_ファイルにも書かれる(self, window) -> None:
        self.make_history(window)
        oldest = versions(window)[-1]
        window.restore_version(oldest)

        assert "古い内容" in window.current_note.path.read_text(encoding="utf-8")

    def test_知らせを出す(self, window) -> None:
        self.make_history(window)
        window.restore_version(versions(window)[-1])
        assert window.notice()


class TestPrune:
    def test_起動時に掃除する(self, qtbot, config) -> None:
        root = config.vault_path / ".hitofude" / "history"
        old = datetime.now() - timedelta(days=history.MAX_DAYS + 1)
        history.keep(root, "01OLD", "# 大昔\n", now=old)

        second = MainWindow(config)
        qtbot.addWidget(second)
        try:
            assert history.versions(root, "01OLD") == []
        finally:
            second.close()


class TestOpenDialog:
    def test_メニューにある(self, window) -> None:
        from PySide6.QtGui import QKeySequence

        found = {a.text(): a.shortcut().toString() for a in window.actions()}
        assert "版の履歴…" in found
        assert found["版の履歴…"] == QKeySequence("Ctrl+Shift+H").toString()

    def test_開ける(self, window) -> None:
        window.new_note()
        write_body(window, "# メモ\n\n本文\n")
        window.flush()

        dialog = window.build_history_dialog()
        try:
            assert dialog.row_count() == 1
        finally:
            dialog.deleteLater()

    def test_ノートを開いていなければ出さない(self, window) -> None:
        assert window.build_history_dialog() is None

    def test_選ぶと戻る(self, window) -> None:
        window.new_note()
        write_body(window, "# メモ\n\n古い内容\n")
        window.flush()
        window._history_now = lambda: datetime.now() + timedelta(hours=1)
        write_body(window, "# メモ\n\n新しい内容\n")
        window.flush()

        dialog = window.build_history_dialog()
        try:
            dialog.select_row(dialog.row_count() - 1)
            dialog.restore()
        finally:
            dialog.deleteLater()
        assert "古い内容" in window.editor.toPlainText()
