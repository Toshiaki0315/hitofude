"""未保存表示・文字数・編集メニュー・直前のノートへ戻る。

どれも「無くても動くが、無いと不安になる」たぐいのもの。
自動保存を信じるしかない状態や、`Cmd+Z` がメニューに無い状態を埋める。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from hitofude import APP_NAME
from hitofude.config import Config
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")

    widget = MainWindow(config)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


def note(window: MainWindow, title: str, body: str = "本文\n") -> Path:
    created = window.vault.create(title, f"# {title}\n\n{body}")
    window.vault_index.upsert_note(created, window.vault.root)
    window.refresh()
    return created.path


class TestDirtyIndicator:
    def test_ノートが無ければアプリ名だけ(self, window) -> None:
        assert window.windowTitle() == APP_NAME

    def test_開いた直後は印が付かない(self, window) -> None:
        window.open_note(note(window, "メモ"))
        assert window.windowTitle() == f"メモ — {APP_NAME}"

    def test_打つと印が付く(self, window) -> None:
        window.open_note(note(window, "メモ"))
        window.editor.textCursor().insertText("追記")
        assert window.windowTitle().startswith("•")

    def test_保存すると消える(self, window) -> None:
        window.open_note(note(window, "メモ"))
        window.editor.textCursor().insertText("追記")
        window.flush()
        assert not window.windowTitle().startswith("•")

    def test_印が付いてもタイトルは読める(self, window) -> None:
        window.open_note(note(window, "メモ"))
        window.editor.textCursor().insertText("追記")
        assert "メモ" in window.windowTitle()
        assert APP_NAME in window.windowTitle()

    def test_ゴミ箱へ入れると印も消える(self, window) -> None:
        window.open_note(note(window, "メモ"))
        window.editor.textCursor().insertText("追記")
        window.trash_current()
        assert window.windowTitle() == APP_NAME


class TestStats:
    def test_文字数が出る(self, window) -> None:
        window.open_note(note(window, "メモ", "あいうえお\n"))
        assert "文字" in window.status_text()

    def test_開いたノートの分量を数える(self, window) -> None:
        window.open_note(note(window, "メモ", "あいうえお\n"))
        # 見出し「メモ」2 文字 + 本文 5 文字。`#` と空行は数えない
        assert "7 文字" in window.status_text()

    def test_単語数も出る(self, window) -> None:
        window.open_note(note(window, "メモ"))
        assert "語" in window.status_text()

    def test_ノートを切り替えると数え直す(self, window) -> None:
        window.open_note(note(window, "短い", "あ\n"))
        first = window.status_text()
        window.open_note(note(window, "長い", "あいうえおかきくけこ\n"))
        assert window.status_text() != first

    def test_打っただけでは数え直さない(self, window) -> None:
        """1 打ごとに数えると 38,000 字のノートで 40ms 掛かる（実測）。
        入力が止まってから数える。"""
        window.open_note(note(window, "メモ", "あ\n"))
        before = window.status_text()
        window.editor.textCursor().insertText("いうえお")
        assert window.status_text() == before

    def test_少し待てば数え直す(self, window, qtbot) -> None:
        window.open_note(note(window, "メモ", "あ\n"))
        before = window.status_text()
        window.editor.textCursor().insertText("いうえお")
        qtbot.waitUntil(lambda: window.status_text() != before, timeout=3000)

    def test_ノートが無ければ空(self, window) -> None:
        assert window.status_text() == ""


class TestEditMenu:
    """`Cmd+Z` は効いていたが、メニューに無いのは macOS アプリとして不自然。"""

    def labels(self, window) -> list[str]:
        for menu in window.menuBar().findChildren(type(window.menuBar().actions()[0].menu())):
            names = [action.text() for action in menu.actions()]
            if "表を整形" in names:
                return names
        return []

    @pytest.mark.parametrize(
        "label", ["取り消す", "やり直す", "切り取り", "コピー", "貼り付け", "すべて選択"]
    )
    def test_標準項目がある(self, window, label: str) -> None:
        assert label in self.labels(window)

    def test_エディタに効く(self, window) -> None:
        window.open_note(note(window, "メモ"))
        window.editor.setFocus()
        window.editor.textCursor().insertText("消す文字")
        window.dispatch_edit("undo")
        assert "消す文字" not in window.editor.toPlainText()

    def test_フォーカスのある入力欄に効く(self, window) -> None:
        """検索欄で `Cmd+A` を押して本文が全選択されたら取り違え。"""
        window.open_note(note(window, "メモ"))
        window.editor_pane.open_find()
        field = window.editor_pane.find_bar._query
        field.setText("さがす")
        field.setFocus()

        window.dispatch_edit("selectAll")
        assert field.selectedText() == "さがす"
        assert window.editor.textCursor().selectedText() == ""

    def test_渡せない操作なら何もしない(self, window) -> None:
        window.sidebar.setFocus()
        window.dispatch_edit("そんなメソッドは無い")


class TestPreviousNote:
    def test_直前のノートへ戻れる(self, window) -> None:
        first = note(window, "ひとつめ")
        second = note(window, "ふたつめ")
        window.open_note(first)
        window.open_note(second)

        window.open_previous_note()
        assert window.current_note.path == first

    def test_もう一度押すと行き来する(self, window) -> None:
        first = note(window, "ひとつめ")
        second = note(window, "ふたつめ")
        window.open_note(first)
        window.open_note(second)

        window.open_previous_note()
        window.open_previous_note()
        assert window.current_note.path == second

    def test_戻る先が無ければ何もしない(self, window) -> None:
        window.open_previous_note()
        assert window.current_note is None

    def test_消えたノートへは戻らない(self, window) -> None:
        first = note(window, "ひとつめ")
        second = note(window, "ふたつめ")
        window.open_note(first)
        window.open_note(second)
        window.vault.trash(first)

        window.open_previous_note()
        assert window.current_note.path == second

    def test_同じノートを開き直しても履歴が潰れない(self, window) -> None:
        first = note(window, "ひとつめ")
        second = note(window, "ふたつめ")
        window.open_note(first)
        window.open_note(second)
        window.open_note(second)

        window.open_previous_note()
        assert window.current_note.path == first


class TestClipboardSafety:
    def test_コピーが選択のあるほうへ行く(self, window) -> None:
        window.open_note(note(window, "メモ", "コピーされる本文\n"))
        window.editor.setFocus()
        window.editor.selectAll()
        window.dispatch_edit("copy")
        assert "コピーされる本文" in QApplication.clipboard().text()
