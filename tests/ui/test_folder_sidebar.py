"""フォルダをサイドバーに出す（K-2）。

サブフォルダは既に読める（§7.1）のに、**画面から見えなかった**。フォルダに
分けても、一覧は題名で並ぶだけで、どれがどこにあるか読めない（ユーザー報告）。

**見せるだけ。** 作る・動かすは K-3（§7.1 を覆すので ADR が要る）。
"""

from pathlib import Path

import pytest

from hitofude.storage.index_db import FolderCount
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import Filter, FilterKind, Sidebar

pytestmark = pytest.mark.gui

FOLDERS = [
    FolderCount(folder="仕事", count=2),
    FolderCount(folder="仕事/2026", count=1),
    FolderCount(folder="私用", count=1),
]


@pytest.fixture
def sidebar(qtbot) -> Sidebar:
    widget = Sidebar()
    qtbot.addWidget(widget)
    return widget


def labels(sidebar: Sidebar) -> list[str]:
    model = sidebar.model()
    return [model.item(row).text() for row in range(model.rowCount())]


class TestTree:
    def test_フォルダの見出しが出る(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        assert "フォルダ" in labels(sidebar)

    def test_フォルダが無ければ見出しも出さない(self, sidebar) -> None:
        """タグと同じ作法。空の見出しは場所を取るだけ。"""
        sidebar.set_folders([])
        assert "フォルダ" not in labels(sidebar)

    def test_階層は入れ子で出す(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        model = sidebar.model()
        header = next(
            model.item(row)
            for row in range(model.rowCount())
            if model.item(row).text() == "フォルダ"
        )
        top = [header.child(row).text() for row in range(header.rowCount())]
        assert any("仕事" in text for text in top)
        assert any("私用" in text for text in top)

    def test_末端の名前だけ出す(self, sidebar) -> None:
        """`仕事/2026` は `2026` と出す（階層は字下げで見せる）。"""
        sidebar.set_folders(FOLDERS)
        found = FolderCount(folder="仕事/2026", count=1)
        assert found.label == "2026"

    def test_件数も出す(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        model = sidebar.model()
        header = next(
            model.item(row)
            for row in range(model.rowCount())
            if model.item(row).text() == "フォルダ"
        )
        assert "2" in header.child(0).text()

    def test_タグより上に出す(self, sidebar) -> None:
        """**入れ物が先、ラベルが後。** 場所を探すほうが先に目に入る。"""
        from hitofude.storage.index_db import TagCount

        sidebar.set_folders(FOLDERS)
        sidebar.set_tags([TagCount(tag="仕事", count=1)])
        found = labels(sidebar)
        assert found.index("フォルダ") < found.index("タグ")


class TestSelect:
    def test_選ぶと知らせる(self, sidebar, qtbot) -> None:
        sidebar.set_folders(FOLDERS)
        target = Filter(FilterKind.FOLDER, folder="仕事")
        with qtbot.waitSignal(sidebar.filter_changed, timeout=1000) as blocker:
            sidebar.select(target)
        assert blocker.args[0] == target

    def test_組み直しても選択が残る(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        target = Filter(FilterKind.FOLDER, folder="仕事")
        sidebar.select(target)
        sidebar.set_folders([*FOLDERS, FolderCount(folder="趣味", count=1)])
        assert sidebar.current_filter() == target


class TestInWindow:
    def put(self, window: MainWindow, folder: str, title: str) -> Path:
        target = window.vault.root / folder
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{title}.md"
        path.write_text(f"# {title}\n\n本文\n", encoding="utf-8")
        window.vault_index.sync(window.vault)
        window.refresh()
        return path

    def test_フォルダが出る(self, window) -> None:
        self.put(window, "仕事", "会議")
        assert "フォルダ" in labels(window.sidebar)

    def test_選ぶとその中だけ出る(self, window) -> None:
        self.put(window, "仕事", "会議")
        self.put(window, "私用", "買い物")
        window.set_filter(Filter(FilterKind.FOLDER, folder="仕事"))

        model = window.note_list.model()
        assert [model.index(i).data() for i in range(model.rowCount())] == ["会議"]

    def test_空のときの案内(self, window) -> None:
        self.put(window, "仕事", "会議")
        window.set_filter(Filter(FilterKind.FOLDER, folder="無い"))
        assert "無い" in window.note_list_pane.empty_notice_text()
