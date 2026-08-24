"""競合と外部削除のときの分岐（spec §7.5）。

**このアプリで最も避けたい事故に直結する経路**なのに、モーダルが挟まるため
テストが無かった（監査で判明）。ダイアログの応答を差し替えて、
どの選択でも書いたものが残ることを見る。
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from hitofude.ui.conflict_dialog import ConflictDialog, Resolution
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def opened_note(window: MainWindow, body: str = "もとの本文\n") -> Path:
    note = window.vault.create("競合するノート", f"# 競合するノート\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    window.open_note(note.path)
    return note.path


def answer_with(monkeypatch, resolution: Resolution) -> None:
    """競合ダイアログの応答を差し替える。"""
    monkeypatch.setattr(ConflictDialog, "exec", lambda self: 0)
    monkeypatch.setattr(ConflictDialog, "resolution", property(lambda self: resolution))


def make_conflict(window: MainWindow, path: Path) -> None:
    """外部で書き換えたうえで、こちらにも未保存の編集を作る。"""
    import time

    time.sleep(0.01)
    path.write_text("# 競合するノート\n\n外部で書いた内容\n", encoding="utf-8")
    # **末尾に足す。** 先頭に入れると見出しが変わり、保存時に改名されて
    # このテストが見たい競合とは別の話になる
    window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
    window.editor.textCursor().insertText("こちらで書いた内容")


class TestConflict:
    def test_自分の版を選ぶと自分の内容が残る(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.TAKE_MINE)

        window.flush()
        assert "こちらで書いた内容" in path.read_text(encoding="utf-8")

    def test_外部を選ぶと外部の内容になる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.TAKE_EXTERNAL)

        window.flush()
        assert "外部で書いた内容" in path.read_text(encoding="utf-8")

    def test_外部を選ぶと画面も外部の内容になる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.TAKE_EXTERNAL)

        window.flush()
        assert "外部で書いた内容" in window.editor.toPlainText()

    def test_両方残すと別ファイルができる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.KEEP_BOTH)

        window.flush()
        kept = [p for p in window.vault.root.glob("*.md") if "競合" in p.name and p != path]
        assert kept, "別名のファイルができていない"

    def test_両方残すとどちらの内容も消えない(self, window, monkeypatch) -> None:
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.KEEP_BOTH)

        window.flush()
        everything = "".join(p.read_text(encoding="utf-8") for p in window.vault.root.glob("*.md"))
        assert "外部で書いた内容" in everything
        assert "こちらで書いた内容" in everything

    def test_閉じるだけなら何も書かない(self, window, monkeypatch) -> None:
        """ダイアログを閉じただけで上書きしない。"""
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.CANCEL)

        window.flush()
        assert "外部で書いた内容" in path.read_text(encoding="utf-8")

    def test_キャンセルしても未保存のまま(self, window, monkeypatch) -> None:
        """キャンセルは「まだ決めない」であって「保存できた」ではない。

        flush() が保存の前に待ちを解除するため、キャンセル後は
        未保存の編集が「保存済み」扱いになっていた（回帰）。
        """
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.CANCEL)

        window.flush()
        assert window._debouncer.pending

    def test_キャンセルして閉じても自分の内容が残る(self, window, monkeypatch) -> None:
        """キャンセル → 終了で、終了時の「両方残す」が走らず
        こちらで書いた内容が消えていた（回帰）。"""
        path = opened_note(window)
        make_conflict(window, path)
        answer_with(monkeypatch, Resolution.CANCEL)

        window.flush()  # 競合ダイアログ → キャンセル
        window.flush(interactive=False)  # closeEvent と同じ経路

        everything = "".join(p.read_text(encoding="utf-8") for p in window.vault.root.glob("*.md"))
        assert "こちらで書いた内容" in everything
        assert "外部で書いた内容" in everything

    def test_聞けないときは両方残す(self, window) -> None:
        """終了処理からはモーダルを開けない。書いたものを失わない側に倒す。"""
        path = opened_note(window)
        make_conflict(window, path)

        window.flush(interactive=False)
        everything = "".join(p.read_text(encoding="utf-8") for p in window.vault.root.glob("*.md"))
        assert "こちらで書いた内容" in everything
        assert "外部で書いた内容" in everything


class TestExternalDelete:
    def test_作り直すと内容が戻る(self, window, monkeypatch) -> None:
        path = opened_note(window, "消される前の本文\n")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        path.unlink()
        window._on_note_deleted(path)
        assert path.is_file()
        assert "消される前の本文" in path.read_text(encoding="utf-8")

    def test_作り直さないなら閉じる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_note_deleted(path)
        assert window.current_note is None
        assert window.editor.toPlainText() == ""

    def test_索引からも消える(self, window, monkeypatch) -> None:
        path = opened_note(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_external_change(_deleted_kind(), path)
        assert all(row.title != "競合するノート" for row in window.vault_index.notes())

    def test_閉じたらタイトルからも消える(self, window, monkeypatch) -> None:
        """No の分岐が本文を消すだけで、タイトル・last_note・未保存の
        待ちの後始末をしていなかった（回帰）。消えたノート名が
        ウィンドウに残り、表示が嘘をつく。"""
        path = opened_note(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_note_deleted(path)
        assert "競合するノート" not in window.windowTitle()

    def test_閉じたら次回起動の対象からも外す(self, window, monkeypatch) -> None:
        path = opened_note(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_note_deleted(path)
        assert window._config.last_note is None

    def test_閉じたら未保存の待ちも解消する(self, window, monkeypatch) -> None:
        path = opened_note(window)
        window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
        window.editor.textCursor().insertText("打ちかけ")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        path.unlink()
        window._on_note_deleted(path)
        assert not window._debouncer.pending  # 200ms ごとの空振り flush を残さない

    def test_作り直したら保存済み扱いになる(self, window, monkeypatch) -> None:
        path = opened_note(window)
        window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
        window.editor.textCursor().insertText("打ちかけ")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        path.unlink()
        window._on_note_deleted(path)
        assert path.is_file()  # 作り直しで書けている
        assert not window._debouncer.pending


def _deleted_kind():
    from hitofude.storage.watcher import ChangeKind

    return ChangeKind.DELETED


class TestRecoveryPrompt:
    """復元の問いかけ（`docs/manual_test.md` §4）。

    **めったに出ないのが正常。** 打鍵から 800ms で本体ファイルへ保存され、
    退避は消える。手で `kill -9` を撃つ頃には保存が済んでいるので、
    尋ねられないのが正しい。ここでは出る条件と、その後の分岐を見る。
    """

    def crashed_with_unsaved(self, window) -> Path:
        """打ちかけのまま落ちた状態を作る。"""
        path = opened_note(window, "保存済みの本文\n")
        window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
        window.editor.textCursor().insertText("打ちかけで落ちた分")
        window._saver.on_tick()  # 200ms 相当。ここで退避ができる
        return path

    def test_保存が済んでいれば尋ねない(self, window, monkeypatch) -> None:
        """打鍵から 800ms 経てば保存され、退避は残らない。"""
        opened_note(window)
        window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
        window.editor.textCursor().insertText("書いた分")
        window.flush()

        assert window.pending_recovery() == []
        assert window.offer_recovery() == []

    def test_打ちかけなら退避が残る(self, window) -> None:
        self.crashed_with_unsaved(window)
        assert len(window.pending_recovery()) == 1

    def test_承諾すると別ファイルにする(self, window, monkeypatch) -> None:
        path = self.crashed_with_unsaved(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        restored = window.offer_recovery()
        assert len(restored) == 1
        assert "打ちかけで落ちた分" in restored[0].read_text(encoding="utf-8")
        assert "打ちかけで落ちた分" not in path.read_text(encoding="utf-8")

    def test_断ると何も増えない(self, window, monkeypatch) -> None:
        before = set(window.vault.root.glob("*.md"))
        self.crashed_with_unsaved(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        assert window.offer_recovery() == []
        assert set(window.vault.root.glob("*.md")) == before | {window.current_note.path}

    def test_断ったら次は尋ねられない(self, window, monkeypatch) -> None:
        """断ったのに毎回出てくるのは鬱陶しい。"""
        self.crashed_with_unsaved(window)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        window.offer_recovery()

        assert window.pending_recovery() == []


class TestWriteFailure:
    """書けなかったときに**書いた内容を捨てない**。

    `flush()` は保存の前に待ちを解除する（再入を防ぐため）。書き込みが
    例外で終わると、待ちは解けたまま何も書かれない。退避（`_maybe_stash`）
    も待ちを見ているので保険まで止まり、終了時の `flush()` も
    「待ちが無い」で素通りする。
    """

    def failing_write(self, monkeypatch, window: MainWindow) -> None:
        def refuse(*_args, **_kwargs):
            raise OSError("書けない（ディスクや権限）")

        monkeypatch.setattr(window.vault, "write", refuse)

    def test_例外で落ちない(self, window: MainWindow, monkeypatch) -> None:
        opened_note(window)
        window.editor.insertPlainText("追記\n")
        self.failing_write(monkeypatch, window)
        window.flush()  # 例外が漏れると QTimer のスロットから飛び出す

    def test_待ちを解かない(self, window: MainWindow, monkeypatch) -> None:
        """次のチックでもう一度試し、退避も続くようにする。"""
        opened_note(window)
        window.editor.insertPlainText("追記\n")
        self.failing_write(monkeypatch, window)
        window.flush()
        assert window._debouncer.pending

    def test_書けなかったことを知らせる(self, window: MainWindow, monkeypatch) -> None:
        """黙って失敗すると、書いたつもりで閉じてしまう。"""
        opened_note(window)
        window.editor.insertPlainText("追記\n")
        self.failing_write(monkeypatch, window)
        window.flush()
        assert "保存" in window.notice()

    def test_保存済みの時刻を出さない(self, window: MainWindow, monkeypatch) -> None:
        opened_note(window)
        window.editor.insertPlainText("追記\n")
        self.failing_write(monkeypatch, window)
        window.flush()
        assert window.saved_text() == ""


class TestWriteRetry:
    """書けないまま繰り返し叩かない（コードレビュー指摘 2026-08-24）。

    失敗したら待ちに戻すので、恒久的な失敗（権限・容量）では 0.8 秒ごとに
    書き込みと記録と通知が延々と繰り返される。**間を置く。**
    """

    def failing(self, monkeypatch, window: MainWindow) -> list[int]:
        tried: list[int] = []

        def refuse(*_args, **_kwargs):
            tried.append(1)
            raise OSError("書けない")

        monkeypatch.setattr(window.vault, "write", refuse)
        return tried

    def ready(self, window: MainWindow) -> None:
        """打ちかけがあり、いつでも保存に入れる状態にする。"""
        opened_note(window)
        window.editor.insertPlainText("追記\n")
        window._saver.debouncer.delay = 0  # 待たずに due にする

    def test_すぐには再試行しない(self, window: MainWindow, monkeypatch) -> None:
        self.ready(window)
        tried = self.failing(monkeypatch, window)
        window.flush()
        window._saver.on_tick()
        window._saver.on_tick()
        assert len(tried) == 1

    def test_間を置いたら試す(self, window: MainWindow, monkeypatch) -> None:
        self.ready(window)
        tried = self.failing(monkeypatch, window)
        window.flush()
        from hitofude.ui.save_controller import WRITE_RETRY_SECONDS

        base = window._saver.clock()
        window._saver.clock = lambda: base + WRITE_RETRY_SECONDS + 1
        window._saver.on_tick()
        assert len(tried) == 2

    def test_自分で保存したときは待たせない(self, window: MainWindow, monkeypatch) -> None:
        """`Cmd+S` は「今すぐ書け」。間を置く相手ではない。"""
        self.ready(window)
        tried = self.failing(monkeypatch, window)
        window.flush()
        window.flush(explicit=True)
        assert len(tried) == 2

    def test_知らせは繰り返さない(self, window: MainWindow, monkeypatch) -> None:
        told: list[str] = []
        self.ready(window)
        tried = self.failing(monkeypatch, window)
        monkeypatch.setattr(window, "notify", lambda text, *args, **kwargs: told.append(text))
        window.flush()
        window.flush(explicit=True)
        assert len(tried) == 2
        assert len(told) == 1

    def test_書けたら知らせ直す(self, window: MainWindow, monkeypatch) -> None:
        """一度直ったあとに再び失敗したら、また知らせる。"""
        self.ready(window)
        self.failing(monkeypatch, window)
        window.flush()
        monkeypatch.undo()
        window.flush(explicit=True)  # 書けた
        told: list[str] = []
        monkeypatch.setattr(window, "notify", lambda text, *args, **kwargs: told.append(text))
        self.failing(monkeypatch, window)
        window.editor.insertPlainText("さらに追記\n")
        window.flush(explicit=True)
        assert told
