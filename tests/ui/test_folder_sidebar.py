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


class TestExpansion:
    """フォルダツリーの展開はタグの有無に依存しない（コードレビュー指摘）。"""

    def folder_index(self, sidebar):
        model = sidebar.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            if item.text() == "フォルダ":
                return model.indexFromItem(item)
        return None

    def test_タグが無くても展開される(self, qtbot) -> None:
        from hitofude.storage.index_db import FolderCount
        from hitofude.ui.sidebar import Sidebar

        sidebar = Sidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_folders([FolderCount(folder="仕事", count=2)])
        sidebar.set_tags([])  # タグゼロ

        index = self.folder_index(sidebar)
        assert index is not None
        assert sidebar.isExpanded(index), "タグが無いとフォルダが畳まれたまま"

    def test_タグが無くても畳んだ枝は覚える(self, qtbot) -> None:
        from hitofude.storage.index_db import FolderCount
        from hitofude.ui.sidebar import Sidebar

        sidebar = Sidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_folders([FolderCount(folder="仕事", count=2)])
        sidebar.set_tags([])
        index = self.folder_index(sidebar)
        sidebar.setExpanded(index, False)  # 手で畳む

        sidebar.set_folders([FolderCount(folder="仕事", count=3)])  # 件数が変わって再構築
        index = self.folder_index(sidebar)
        assert not sidebar.isExpanded(index), "畳んだ枝が再構築で開き直された"


class TestFilterValidation:
    def test_フォルダ指定なしのFOLDERは作れない(self, qtbot) -> None:
        """folder=None のまま作ると、ラベルが 'None/'・一覧は黙って空に
        なっていた（コードレビュー指摘）。作る時点で大声で失敗させる。"""
        import pytest as _pytest

        from hitofude.ui.sidebar import Filter, FilterKind

        with _pytest.raises(ValueError):
            Filter(FilterKind.FOLDER)


class TestRootEntry:
    """ルートを「フォルダ」として常に並べる（ユーザー要望）。"""

    def labels(self, sidebar) -> list[str]:
        model = sidebar.model()
        found = []
        for row in range(model.rowCount()):
            item = model.item(row)
            found.append(item.text())
            for child in range(item.rowCount()):
                found.append(item.child(child).text())
        return found

    def test_直下という項目が出る(self, qtbot) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER, FolderCount
        from hitofude.ui.sidebar import Sidebar

        sidebar = Sidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_folders(
            [FolderCount(folder=ROOT_FOLDER, count=2), FolderCount(folder="仕事", count=1)]
        )
        found = self.labels(sidebar)
        assert any(label.startswith("直下") for label in found)
        assert not any(label.startswith("./") for label in found), "記号が素で出ている"

    def test_ルートのフィルタが作れる(self) -> None:
        from hitofude.storage.index_db import ROOT_FOLDER
        from hitofude.ui.sidebar import Filter, FilterKind

        target = Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)
        assert target.label == "直下"


class TestCreateFolderMenu:
    """フォルダを右クリック → 直下に新しいフォルダ（ユーザー要望）。"""

    def folder_filter(self, name="日報"):
        from hitofude.ui.sidebar import Filter, FilterKind

        return Filter(FilterKind.FOLDER, folder=name)

    def root_filter(self):
        from hitofude.storage.index_db import ROOT_FOLDER
        from hitofude.ui.sidebar import Filter, FilterKind

        return Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)

    def test_メニューに項目がある(self, window) -> None:
        window.vault.create_folder("日報")
        window.refresh()
        menu = window.sidebar_menu_for(self.folder_filter())
        assert menu is not None
        assert "新しいフォルダ…" in [action.text() for action in menu.actions()]

    def test_直下にも出る(self, window) -> None:
        menu = window.sidebar_menu_for(self.root_filter())
        assert menu is not None
        assert "新しいフォルダ…" in [action.text() for action in menu.actions()]

    def test_選んだフォルダの中に作られる(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        window.vault.create_folder("日報")
        window.refresh()
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("2026", True))
        )
        created = window.create_folder(self.folder_filter())
        assert created == window.vault.root / "日報" / "2026"
        assert "日報/2026" in window.vault.folders()
        assert "作りました" in window.notice()

    def test_直下から作ると直下にできる(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("日報", True))
        )
        created = window.create_folder(self.root_filter())
        assert created == window.vault.root / "日報"

    def test_作ったフォルダは空でもサイドバーに出る(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("空っぽ", True))
        )
        window.create_folder(self.root_filter())
        model = window._sidebar.model()
        labels = []
        for row in range(model.rowCount()):
            item = model.item(row)
            for child in range(item.rowCount()):
                labels.append(item.child(child).text())
        assert any(label.startswith("空っぽ") for label in labels)

    def test_やめれば何もしない(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
        )
        assert window.create_folder(self.root_filter()) is None
        assert window.vault.folders() == []

    def test_同じ名前なら知らせて作らない(self, window, monkeypatch) -> None:
        from hitofude.ui import note_actions as module

        window.vault.create_folder("日報")
        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("日報", True))
        )
        assert window.create_folder(self.root_filter()) is None
        assert "同じ名前" in window.notice()


class TestDeleteFolderMenu:
    """フォルダを右クリック → 削除（フォルダが残る仕様の対になる出口）。"""

    def folder_filter(self, name="消す箱"):
        from hitofude.ui.sidebar import Filter, FilterKind

        return Filter(FilterKind.FOLDER, folder=name)

    def yes(self, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        from hitofude.ui import note_actions as module

        monkeypatch.setattr(
            module.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )

    def test_メニューに項目がある(self, window) -> None:
        window.vault.create_folder("消す箱")
        window.refresh()
        found = [a.text() for a in window.sidebar_menu_for(self.folder_filter()).actions()]
        assert "フォルダを削除…" in found

    def test_直下には削除を出さない(self, window) -> None:
        """保管フォルダそのものは消せない。"""
        from hitofude.storage.index_db import ROOT_FOLDER

        found = [
            a.text() for a in window.sidebar_menu_for(self.folder_filter(ROOT_FOLDER)).actions()
        ]
        assert "フォルダを削除…" not in found

    def test_空なら消える(self, window, monkeypatch) -> None:
        window.vault.create_folder("消す箱")
        window.refresh()
        self.yes(monkeypatch)
        assert window.delete_folder(self.folder_filter()) is True
        assert "消す箱" not in window.vault.folders()
        assert "削除しました" in window.notice()

    def test_ノートが入っていたら知らせて消さない(self, window, monkeypatch) -> None:
        path = window.vault.root / "使用中" / "メモ.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# メモ\n", encoding="utf-8")
        window.refresh()
        self.yes(monkeypatch)
        assert window.delete_folder(self.folder_filter("使用中")) is False
        assert path.exists()
        assert "ノート" in window.notice()

    def test_やめれば残る(self, window, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        from hitofude.ui import note_actions as module

        window.vault.create_folder("消す箱")
        window.refresh()
        monkeypatch.setattr(
            module.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
        )
        assert window.delete_folder(self.folder_filter()) is False
        assert "消す箱" in window.vault.folders()

    def test_選んでいたフォルダを消したらすべてへ戻る(self, window, monkeypatch) -> None:
        """サイドバーで選んでいたものが消えたら「すべて」へ退避する。

        実際の経路（サイドバーの選択 → filter_changed）を通す。
        """
        from hitofude.ui.sidebar import FilterKind

        window.vault.create_folder("消す箱")
        window.refresh()
        window._sidebar.select(self.folder_filter())
        assert window._filter.kind is FilterKind.FOLDER  # 選べている

        self.yes(monkeypatch)
        window.delete_folder(self.folder_filter())
        assert window._filter.kind is FilterKind.ALL
