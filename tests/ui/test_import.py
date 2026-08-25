"""資料の取り込み（F-2）。

「ファイル」→「読み込む…」で PDF を選ぶと、**新しいノートになって開く**。
もらった資料を Markdown にして書き足す、という使い方（TASKS.md の F 群）。

**元のファイルは触らない。** 読むだけで、移動も複製もしない。
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hitofude.editor.exporter import write_pdf
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui

NOTE = "# 四半期の振り返り\n\n本日の議題は **予算** です。\n"


@pytest.fixture(autouse=True)
def notice(monkeypatch) -> list[str]:
    """読めなかったときの知らせ。**出しっぱなしにするとテストが固まる。**"""
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a, **k: shown.append(text))
    return shown


@pytest.fixture
def sample(qapp, tmp_path: Path) -> Path:
    return write_pdf(tmp_path / "四半期資料.pdf", NOTE)


def choose(monkeypatch, path: Path | None) -> None:
    """ファイル選択の結果を差し替える（開くとモーダルで止まる）。"""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(path) if path else "", "")
    )


def titles(window: MainWindow) -> list[str]:
    model = window.note_list.model()
    return [model.index(row).data() for row in range(model.rowCount())]


def run_import(window: MainWindow) -> Path | None:
    """取り込みを始めて、終わるまで待つ。開いたノートの場所を返す。

    読み取りは背景スレッドに移った（レビュー 2026-08-25）ので、
    `import_document()` は始めるだけですぐ戻る。
    """
    before = window.current_note.path if window.current_note else None
    window.import_document()
    assert window.wait_for_import(), "取り込みが終わらない"
    after = window.current_note.path if window.current_note else None
    return after if after != before else None


class TestImport:
    def test_ノートができて開く(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        path = run_import(window)
        assert path is not None
        assert window.current_note.path == path

    def test_題名はファイル名(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        assert run_import(window).name == "四半期資料.md"

    def test_一覧に出る(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        run_import(window)
        assert "四半期資料" in titles(window)

    def test_本文が入っている(self, window, sample, monkeypatch) -> None:
        choose(monkeypatch, sample)
        run_import(window)
        assert "本日の議題" in window.editor.toPlainText()

    def test_元のファイルを触らない(self, window, sample, monkeypatch) -> None:
        before = sample.read_bytes()
        choose(monkeypatch, sample)
        run_import(window)
        assert sample.read_bytes() == before

    def test_やめれば何も起きない(self, window, monkeypatch) -> None:
        choose(monkeypatch, None)
        before = len(titles(window))
        assert run_import(window) is None
        assert len(titles(window)) == before

    def test_読めないファイルは知らせる(self, window, notice, monkeypatch, tmp_path) -> None:
        """**ノートは作らない。** 空のノートが増えるほうが困る。"""
        broken = tmp_path / "壊れた.pdf"
        broken.write_text("これは PDF ではありません", encoding="utf-8")
        choose(monkeypatch, broken)

        before = len(titles(window))
        assert run_import(window) is None
        assert notice
        assert len(titles(window)) == before

    def test_画像だけのPDFではノートを作らない(self, window, notice, monkeypatch, tmp_path) -> None:
        """ユーザー報告。**題名だけの空のノートができていた。**

        スクリーンショットを PDF にしたものは、ページはあるが文字が
        1 つも無い。題名は常に付くので「空ではない」と見えてしまった。
        """
        from tests.editor.test_importer import image_only_pdf

        source = image_only_pdf(tmp_path / "スクリーンショット.pdf")
        choose(monkeypatch, source)

        before = len(titles(window))
        assert run_import(window) is None
        assert len(titles(window)) == before
        assert notice, "読めなかったことを知らせていない"

    def test_書きかけの内容を保存してから移る(self, window, sample, monkeypatch) -> None:
        note = window.vault.create("元のノート", "# 元のノート\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)
        window.editor.textCursor().insertText("\n打った行\n")

        choose(monkeypatch, sample)
        run_import(window)
        assert "打った行" in note.path.read_text(encoding="utf-8")


class TestMenu:
    def test_メニューにある(self, window) -> None:
        assert "読み込む…" in [action.text() for action in window.actions()]

    def test_ショートカットは付けない(self, window) -> None:
        """ファイルを選ぶ操作で、急いで押すものではない。"""
        for action in window.actions():
            if action.text() == "読み込む…":
                assert action.shortcut().toString() == ""


class TestBackgroundImport:
    """読み取りは背景スレッドで（レビュー 2026-08-25）。

    文字認識付きの PDF は実測 17 秒/ページ。GUI スレッドで読むと
    10 ページの資料で 3 分固まる。索引・統計・アシスタントと同じ
    「QRunnable + 知らせ役」の型で移す。
    """

    def fake(self, monkeypatch, body):
        """`to_markdown` を差し替える。呼ばれ方も覚える。"""
        import hitofude.ui.export_actions as module

        calls: dict = {}

        def stand_in(path, *, save_image=None, ocr=None, on_page=None, should_stop=None):
            import threading

            calls["thread"] = threading.current_thread()
            calls["should_stop"] = should_stop
            return body(on_page)

        monkeypatch.setattr(module.importer, "to_markdown", stand_in)
        return calls

    def test_読み取りはGUIスレッドで走らせない(self, window, sample, monkeypatch) -> None:
        import threading

        calls = self.fake(monkeypatch, lambda on_page: "# 資料\n\n本文\n")
        choose(monkeypatch, sample)
        window.import_document()
        assert window.wait_for_import()
        assert calls["thread"] is not threading.main_thread()
        assert "資料" in titles(window)

    def test_進捗が知らされる(self, window, sample, monkeypatch) -> None:
        told: list[str] = []
        monkeypatch.setattr(window, "notify", lambda text, *a, **k: told.append(text))

        def body(on_page):
            on_page(1, 3)
            on_page(2, 3)
            return "# 資料\n\n本文\n"

        self.fake(monkeypatch, body)
        choose(monkeypatch, sample)
        window.import_document()
        assert window.wait_for_import()
        assert any("1/3" in text for text in told), told
        assert any("2/3" in text for text in told), told

    def test_取り込み中はもう一度始めない(self, window, sample, monkeypatch) -> None:
        import threading

        gate = threading.Event()
        told: list[str] = []
        monkeypatch.setattr(window, "notify", lambda text, *a, **k: told.append(text))
        self.fake(monkeypatch, lambda on_page: (gate.wait(5), "# 資料\n\n本文\n")[1])
        choose(monkeypatch, sample)
        window.import_document()
        window.import_document()  # 走っている間にもう一度
        assert any("取り込んでいます" in text for text in told), told
        gate.set()
        assert window.wait_for_import()
        assert titles(window).count("資料") == 1

    def test_閉じたら途中でやめる合図が立つ(self, window, sample, monkeypatch) -> None:
        calls = self.fake(monkeypatch, lambda on_page: "# 資料\n\n本文\n")
        choose(monkeypatch, sample)
        window.import_document()
        assert window.wait_for_import()
        assert calls["should_stop"]() is False
        window.close()
        assert calls["should_stop"]() is True


class TestCancelledInImporter:
    """途中でやめる口（`should_stop`）が importer 側にもある。"""

    def test_やめる合図で止まる(self, tmp_path, qapp) -> None:
        from hitofude.editor import importer

        source = write_pdf(tmp_path / "資料.pdf", NOTE)
        with pytest.raises(importer.Cancelled):
            importer.to_markdown(source, should_stop=lambda: True)
