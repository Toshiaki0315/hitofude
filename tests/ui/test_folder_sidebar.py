"""フォルダをサイドバーに出す（K-2）。

サブフォルダは既に読める（§7.1）のに、**画面から見えなかった**。フォルダに
分けても、一覧は題名で並ぶだけで、どれがどこにあるか読めない（ユーザー報告）。

**見せるだけ。** 作る・動かすは K-3（§7.1 を覆すので ADR が要る）。
"""

from pathlib import Path

import pytest

from hitofude.storage.index_db import ROOT_FOLDER, FolderCount
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import COUNT_ROLE, FOLDERS_LABEL, Filter, FilterKind, Sidebar

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
        assert FOLDERS_LABEL in labels(sidebar)

    def test_フォルダが無ければ見出しも出さない(self, sidebar) -> None:
        """タグと同じ作法。空の見出しは場所を取るだけ。"""
        sidebar.set_folders([])
        assert FOLDERS_LABEL not in labels(sidebar)

    def test_階層は入れ子で出す(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        model = sidebar.model()
        header = next(
            model.item(row)
            for row in range(model.rowCount())
            if model.item(row).text() == FOLDERS_LABEL
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
            if model.item(row).text() == FOLDERS_LABEL
        )
        assert header.child(0).data(COUNT_ROLE) == 2

    def test_タグより上に出す(self, sidebar) -> None:
        """**入れ物が先、ラベルが後。** 場所を探すほうが先に目に入る。"""
        from hitofude.storage.index_db import TagCount

        sidebar.set_folders(FOLDERS)
        sidebar.set_tags([TagCount(tag="仕事", count=1)])
        found = labels(sidebar)
        folders = found.index(FOLDERS_LABEL)
        assert folders < found.index("タグ")


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
        assert FOLDERS_LABEL in labels(window.sidebar)

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


NESTED = [
    FolderCount(folder=ROOT_FOLDER, count=9),
    FolderCount(folder="仕事", count=1),
    FolderCount(folder="嗚呼あ", count=0),
    FolderCount(folder="嗚呼あ/テスト２", count=0),
]


class TestRootEntry:
    """「フォルダ」の行そのものが直下（ユーザー要望 2026-08-21）。

    以前は見出し「フォルダ」の下に「直下」という子を置いていたが、
    **見出しは押しても何も起きない**のに 1 行を使い、直下がもう 1 行を
    使っていた。見出しを直下そのものにすると、`仕事` や `嗚呼あ` が
    そこから 1 段だけ下がり、Finder の見え方と重なる。
    """

    def header(self, sidebar: Sidebar):
        model = sidebar.model()
        return next(
            model.item(row)
            for row in range(model.rowCount())
            if model.item(row).text() == FOLDERS_LABEL
        )

    def all_labels(self, sidebar: Sidebar) -> list[str]:
        found: list[str] = []

        def walk(item) -> None:
            for row in range(item.rowCount()):
                child = item.child(row)
                found.append(child.text())
                walk(child)

        model = sidebar.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            found.append(item.text())
            walk(item)
        return found

    def test_見出しを選ぶと直下になる(self, sidebar, qtbot) -> None:
        sidebar.set_folders(NESTED)
        target = Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)
        with qtbot.waitSignal(sidebar.filter_changed, timeout=1000) as blocker:
            sidebar.select(target)
        assert blocker.args[0] == target
        assert sidebar.current_filter() == target

    def test_直下という別の行は出さない(self, sidebar) -> None:
        """**同じものを 2 行に分けない。** 見出しと直下は同じ場所を指す。"""
        sidebar.set_folders(NESTED)
        assert not any(label.startswith("直下") for label in self.all_labels(sidebar))
        assert not any(label.startswith("./") for label in self.all_labels(sidebar)), (
            "記号が素で出た"
        )

    def test_件数は見出しに出す(self, sidebar) -> None:
        """選ぶと何件出るかは、ほかのフォルダと同じ読み方で分かるように。"""
        sidebar.set_folders(NESTED)
        assert self.header(sidebar).data(COUNT_ROLE) == 9

    def test_フォルダは見出しの子として並ぶ(self, sidebar) -> None:
        sidebar.set_folders(NESTED)
        header = self.header(sidebar)
        assert [header.child(row).text() for row in range(header.rowCount())] == [
            "仕事",
            "嗚呼あ",
        ]

    def test_子フォルダはさらに一段下がる(self, sidebar) -> None:
        sidebar.set_folders(NESTED)
        header = self.header(sidebar)
        deep = next(
            header.child(row)
            for row in range(header.rowCount())
            if "嗚呼あ" in header.child(row).text()
        )
        assert [deep.child(row).text() for row in range(deep.rowCount())] == ["テスト２"]

    def test_直下が空のときの案内(self, window) -> None:
        """記号（`.`）を見せない。案内は文章なので「直下」と読ませる。"""
        window.set_filter(Filter(FilterKind.FOLDER, folder=ROOT_FOLDER))
        notice = window.note_list_pane.empty_notice_text()
        assert "直下" in notice
        assert "." not in notice.split("\n")[0].replace("`", "")

    def test_ルートのフィルタが作れる(self) -> None:
        """画面の言葉は「フォルダ」だが、文章の中では「直下」と読ませる
        （空の案内で「「フォルダ」にノートはありません」は意味を成さない）。"""
        assert Filter(FilterKind.FOLDER, folder=ROOT_FOLDER).label == "直下"


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


class TestOpenInFinder:
    """フォルダを Finder で開く（ユーザー要望 2026-08-22）。

    **実物を見たい場面がある。** ノートには「Finder で表示」があるのに、
    フォルダには実物への道が無かった。ノートのほうは 1 件を選ばせたい
    ので `open -R`（親を開いて選択）だが、**フォルダはそれ自体を開く**
    （中のファイルを見たいのだから、親を開いても一手足りない）。
    """

    def labels(self, window, target: Filter) -> list[str]:
        menu = window.sidebar_menu_for(target)
        assert menu is not None
        try:
            return [action.text() for action in menu.actions()]
        finally:
            menu.deleteLater()

    def opened(self, window, monkeypatch, target: Filter) -> list[list[str]]:
        from hitofude.ui import export_actions as module

        ran: list[list[str]] = []
        monkeypatch.setattr(module.subprocess, "run", lambda args, **kwargs: ran.append(args))
        window.open_folder_in_finder(target)
        return ran

    def test_メニューに出る(self, window) -> None:
        window.vault.create_folder("日報")
        window.refresh()
        assert "Finder で開く" in self.labels(window, Filter(FilterKind.FOLDER, folder="日報"))

    def test_直下にも出る(self, window) -> None:
        """保管フォルダそのものを開きたいことも多い。"""
        assert "Finder で開く" in self.labels(window, Filter(FilterKind.FOLDER, folder=ROOT_FOLDER))

    def test_そのフォルダを開く(self, window, monkeypatch) -> None:
        window.vault.create_folder("日報")
        window.refresh()
        ran = self.opened(window, monkeypatch, Filter(FilterKind.FOLDER, folder="日報"))
        assert ran == [["open", str(window.vault.root / "日報")]]

    def test_直下は保管フォルダを開く(self, window, monkeypatch) -> None:
        ran = self.opened(window, monkeypatch, Filter(FilterKind.FOLDER, folder=ROOT_FOLDER))
        assert ran == [["open", str(window.vault.root)]]

    def test_無いフォルダなら何もしない(self, window, monkeypatch) -> None:
        """メニューを開いてから Finder で消された、はありうる。"""
        ran = self.opened(window, monkeypatch, Filter(FilterKind.FOLDER, folder="消えた"))
        assert ran == []


class TestRenameFolderMenu:
    """フォルダの名前を変える（ユーザー要望 2026-08-22）。

    **取り残さない。** 名前が変わるとノートのパスも全部変わるので、
    索引・一覧・開いているノート・絞り込みがそろって追いつく必要がある。
    """

    def prepared(self, window):
        window.vault.create_folder("仕事")
        note = window.vault.create("会議", "# 会議\n\n本文\n", folder="仕事")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        return note

    def target(self, folder="仕事"):
        return Filter(FilterKind.FOLDER, folder=folder)

    def labels(self, window, target=None):
        menu = window.sidebar_menu_for(target or self.target())
        assert menu is not None
        try:
            return [action.text() for action in menu.actions() if action.text()]
        finally:
            menu.deleteLater()

    def typed(self, monkeypatch, name: str, accepted: bool = True):
        from hitofude.ui import note_actions as module

        monkeypatch.setattr(
            module.QInputDialog, "getText", staticmethod(lambda *a, **k: (name, accepted))
        )

    def test_メニューに出る(self, window) -> None:
        self.prepared(window)
        assert "名前を変更…" in self.labels(window)

    def test_削除の上に出る(self, window) -> None:
        """**消すより先に並べる。** 直したいだけのときに削除を通らせない。"""
        self.prepared(window)
        found = self.labels(window)
        assert found.index("名前を変更…") < found.index("フォルダを削除…")

    def test_直下には出さない(self, window) -> None:
        """保管フォルダそのものの名前は設定で変えるもの（削除も出していない）。"""
        assert "名前を変更…" not in self.labels(window, self.target(ROOT_FOLDER))

    def test_名前が変わる(self, window, monkeypatch) -> None:
        self.prepared(window)
        self.typed(monkeypatch, "業務")
        window.rename_folder(self.target())
        assert (window.vault.root / "業務").is_dir()
        assert not (window.vault.root / "仕事").exists()

    def test_取り消せば何もしない(self, window, monkeypatch) -> None:
        self.prepared(window)
        self.typed(monkeypatch, "業務", accepted=False)
        window.rename_folder(self.target())
        assert (window.vault.root / "仕事").is_dir()

    def test_索引が追いつく(self, window, monkeypatch) -> None:
        self.prepared(window)
        self.typed(monkeypatch, "業務")
        window.rename_folder(self.target())
        paths = {str(row.path) for row in window.vault_index.notes()}
        assert "業務/会議.md" in paths
        assert "仕事/会議.md" not in paths

    def test_見ていたフォルダに追いつく(self, window, monkeypatch) -> None:
        """**名前を変えた先を見せる。** 変えた瞬間に一覧が空になると驚く。"""
        self.prepared(window)
        window.set_filter(self.target())
        self.typed(monkeypatch, "業務")
        window.rename_folder(self.target())
        assert window.filter == self.target("業務")
        titles = {
            window.note_list.model().note_at(window.note_list.model().index(row, 0)).title
            for row in range(window.note_list.model().rowCount())
        }
        assert titles == {"会議"}

    def test_開いているノートも追いつく(self, window, monkeypatch) -> None:
        """**古いパスへ自動保存させない**（消えた場所へ書き戻る）。"""
        note = self.prepared(window)
        window.open_and_select(note.path)
        self.typed(monkeypatch, "業務")
        window.rename_folder(self.target())
        assert window.current_note.path == window.vault.root / "業務" / "会議.md"

    def test_同じ名前があれば知らせる(self, window, monkeypatch) -> None:
        self.prepared(window)
        window.vault.create_folder("業務")
        self.typed(monkeypatch, "業務")
        window.rename_folder(self.target())
        assert (window.vault.root / "仕事").is_dir()
        assert "同じ名前" in window.notice() or "できません" in window.notice()
