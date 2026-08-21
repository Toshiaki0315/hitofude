"""保存した検索（K-4）。名前を付けた検索式をサイドバーに置く。

ノートを動かさずに束ねられ、1 つのノートが複数の束に入れる。
置き場は QSettings（R9 に触れない）。
"""

import pytest

from hitofude.config import SavedSearch
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import Filter, FilterKind

pytestmark = pytest.mark.gui


def add(window: MainWindow, title: str, body: str) -> None:
    note = window.vault.create(title, f"# {title}\n\n{body}\n")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()


class TestSidebarSection:
    def test_保存した検索がサイドバーに並ぶ(self, window) -> None:
        window._config.saved_searches = [SavedSearch(name="今月の仕事", query="#仕事")]
        window.reload_saved_searches()
        model = window._sidebar.model()
        labels = [model.item(row).text() for row in range(model.rowCount())]
        assert "検索" in labels

    def test_選ぶと検索結果が一覧に出る(self, window) -> None:
        add(window, "仕事の予算", "来期の予算\n\n#仕事")
        add(window, "私用のメモ", "旅行\n\n#私用")
        window._config.saved_searches = [SavedSearch(name="仕事だけ", query="#仕事")]
        window.reload_saved_searches()

        window.set_filter(Filter(FilterKind.SEARCH, name="仕事だけ", query="#仕事"))
        model = window._note_list.model()
        titles = {model.note_at(model.index(row, 0)).title for row in range(model.rowCount())}
        assert titles == {"仕事の予算"}

    def test_無ければ見出しごと出ない(self, window) -> None:
        model = window._sidebar.model()
        labels = [model.item(row).text() for row in range(model.rowCount())]
        assert "検索" not in labels


class TestSaveFlow:
    def test_保存すると設定とサイドバーに載る(self, window, monkeypatch) -> None:
        from hitofude.ui import search_actions as module

        answers = iter([("#仕事 予算", True), ("仕事の予算調べ", True)])
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers))
        )
        assert window.save_search() is True
        assert window._config.saved_searches == [
            SavedSearch(name="仕事の予算調べ", query="#仕事 予算")
        ]

    def test_同じ名前は上書き(self, window, monkeypatch) -> None:
        from hitofude.ui import search_actions as module

        window._config.saved_searches = [SavedSearch(name="調べ", query="古い")]
        answers = iter([("新しい", True), ("調べ", True)])
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers))
        )
        window.save_search()
        assert window._config.saved_searches == [SavedSearch(name="調べ", query="新しい")]

    def test_やめれば何もしない(self, window, monkeypatch) -> None:
        from hitofude.ui import search_actions as module

        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
        )
        assert window.save_search() is False
        assert window._config.saved_searches == []

    def test_メニューに入口がある(self, window) -> None:
        labels = [action.text() for action in window.actions()]
        assert "検索を保存…" in labels


class TestDeleteFlow:
    def test_サイドバーの右クリックで削除できる(self, window, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        from hitofude.ui import note_actions as module

        window._config.saved_searches = [SavedSearch(name="消す", query="#x")]
        window.reload_saved_searches()
        monkeypatch.setattr(
            module.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        target = Filter(FilterKind.SEARCH, name="消す", query="#x")
        menu = window.sidebar_menu_for(target)
        assert menu is not None
        delete = next(a for a in menu.actions() if "削除" in a.text())
        delete.trigger()
        assert window._config.saved_searches == []
