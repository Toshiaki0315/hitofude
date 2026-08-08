"""3 ペインと保存フローのテスト（タスク 5-1 / spec §5.1, §7.4, §7.5）。

Phase 1〜4 の部品が 1 本に繋がっていることを見る層。
ここが通れば「打った内容がファイルに残る」ことになる。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QSplitter

from hitofude.config import Config
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import ALL, Filter, FilterKind

pytestmark = pytest.mark.gui


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    return config


@pytest.fixture
def window(qtbot, config: Config) -> MainWindow:
    widget = MainWindow(config)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


class TestLayout:
    def test_3ペインになっている(self, window) -> None:
        splitter = window.centralWidget()
        assert isinstance(splitter, QSplitter)
        assert splitter.count() == 3

    def test_並びはサイドバーリストエディタ(self, window) -> None:
        splitter = window.centralWidget()
        assert splitter.widget(0) is window.sidebar
        assert splitter.widget(1) is window.note_list
        assert splitter.widget(2) is window.editor

    def test_ペインをたためる(self, window) -> None:
        """spec §5.4: `Cmd+1` / `Cmd+2`。"""
        window.toggle_sidebar()
        assert window.sidebar.isVisible() is False
        window.toggle_sidebar()
        assert window.sidebar.isVisible() is True

    def test_幅が永続化される(self, window, config) -> None:
        window.centralWidget().setSizes([200, 300, 600])
        window.close()
        assert config.splitter_sizes[0] == 200

    def test_表示状態も永続化される(self, window, config) -> None:
        window.toggle_note_list()
        window.close()
        assert config.note_list_visible is False


class TestVaultSetup:
    def test_vaultが作られる(self, window, config) -> None:
        assert config.vault_path.is_dir()
        assert (config.vault_path / ".hitofude").is_dir()

    def test_索引ファイルが作られる(self, window, config) -> None:
        assert (config.vault_path / ".hitofude" / "index.sqlite").is_file()

    def test_既存のノートを読み込む(self, qtbot, config, tmp_path) -> None:
        vault_root = config.vault_path
        vault_root.mkdir(parents=True, exist_ok=True)
        (vault_root / "既存のメモ.md").write_text("# 既存のメモ\n\n本文\n", encoding="utf-8")

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert window.note_list.model().rowCount() == 1
        finally:
            window.close()


class TestNewNote:
    def test_新規ノートを作れる(self, window) -> None:
        window.new_note()
        assert window.current_note is not None
        assert window.current_note.path.is_file()

    def test_一覧に出る(self, window) -> None:
        window.new_note()
        assert window.note_list.model().rowCount() == 1

    def test_エディタに読み込まれる(self, window) -> None:
        window.new_note()
        assert "id:" in window.editor.toPlainText()

    def test_連続で作れる(self, window) -> None:
        window.new_note()
        window.new_note()
        assert window.note_list.model().rowCount() == 2


class TestSave:
    """spec §7.4: これが通れば打った内容がファイルに残る。"""

    def test_フラッシュでファイルに書かれる(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n本文を書いた\n")
        window.flush()
        assert "本文を書いた" in window.current_note.path.read_text(encoding="utf-8")

    def test_読み込み直後は保存しない(self, window) -> None:
        """開いただけで modified が更新されると無意味な diff が出る。"""
        window.new_note()
        before = window.current_note.path.read_text(encoding="utf-8")
        window.flush()
        assert window.current_note.path.read_text(encoding="utf-8") == before

    def test_保存でタイトルが索引に入る(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 新しい題名\n\n本文\n")
        window.flush()
        from hitofude.ui.note_list import NoteRole

        model = window.note_list.model()
        titles = [model.data(model.index(row), NoteRole.TITLE) for row in range(model.rowCount())]
        assert "新しい題名" in titles

    def test_保存でタグが索引に入る(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n本文 #work/会議\n")
        window.flush()
        window.sidebar.select(Filter(FilterKind.TAG, "work"))
        assert window.sidebar.current_filter() == Filter(FilterKind.TAG, "work")

    def test_ノートを切り替えると先に保存する(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 一枚目\n\n切り替え前に書いた\n")

        window.new_note()  # 切り替え時にフラッシュされ、題名に合わせて改名される
        saved = window.vault.root / "一枚目.md"
        assert saved.is_file()
        assert "切り替え前に書いた" in saved.read_text(encoding="utf-8")

    def test_閉じるときに保存する(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n終了前に書いた\n")
        window.close()
        saved = window.vault.root / "メモ.md"
        assert saved.is_file()
        assert "終了前に書いた" in saved.read_text(encoding="utf-8")

    def test_保存しても文字が変わらない(self, window) -> None:
        """R1: `toPlainText()` がそのまま保存内容。"""
        window.new_note()
        window.editor.setPlainText("# メモ\n\nこれは**強調**です #tag\n")
        window.flush()
        saved = window.current_note.path.read_text(encoding="utf-8")
        assert "これは**強調**です #tag" in saved


class TestFilter:
    def test_タグで絞り込める(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 仕事\n\n本文 #work\n")
        window.flush()
        window.new_note()
        window.editor.setPlainText("# 私用\n\n本文 #private\n")
        window.flush()

        window.sidebar.select(Filter(FilterKind.TAG, "work"))
        assert window.note_list.model().rowCount() == 1

    def test_すべてに戻せる(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 仕事\n\n本文 #work\n")
        window.flush()
        window.sidebar.select(Filter(FilterKind.TAG, "work"))
        window.sidebar.select(ALL)
        assert window.note_list.model().rowCount() >= 1


class TestTrash:
    def test_ゴミ箱へ移せる(self, window) -> None:
        window.new_note()
        path = window.current_note.path
        window.trash_current()
        assert not path.exists()
        assert (window.vault.trash_dir / path.name).is_file()

    def test_一覧から消える(self, window) -> None:
        window.new_note()
        window.trash_current()
        assert window.note_list.model().rowCount() == 0

    def test_開いていないときは何もしない(self, window) -> None:
        window.trash_current()


class TestExternalChange:
    """spec §7.5。watchdog を待たず、シグナル相当を直接呼んで判定を見る。"""

    def test_未編集なら静かに読み直す(self, window) -> None:
        from hitofude.storage.watcher import ChangeKind

        window.new_note()
        path = window.current_note.path
        path.write_text("# 外から\n\n書き換えられた\n", encoding="utf-8")

        window._on_external_change(ChangeKind.MODIFIED, path)
        assert "書き換えられた" in window.editor.toPlainText()

    def test_編集中なら読み直さない(self, window) -> None:
        """勝手に上書きすると書いている内容が消える。"""
        from hitofude.storage.watcher import ChangeKind

        window.new_note()
        path = window.current_note.path
        window.editor.setPlainText("# 自分が書いた\n\n編集中\n")
        path.write_text("# 外から\n\n書き換えられた\n", encoding="utf-8")

        window._on_external_change(ChangeKind.MODIFIED, path)
        assert "編集中" in window.editor.toPlainText()

    def test_開いていないノートの変更は索引に入る(self, window) -> None:
        from hitofude.storage.watcher import ChangeKind

        other = window.vault.root / "外部で作られた.md"
        other.write_text("# 外部で作られた\n\n本文\n", encoding="utf-8")
        window._on_external_change(ChangeKind.CREATED, other)
        assert window.note_list.model().rowCount() == 1


class TestCloseWithConflict:
    """終了時にモーダルを開くとアプリが終了できなくなる（回帰テスト）。"""

    def test_競合したまま閉じても固まらない(self, window) -> None:
        window.new_note()
        path = window.current_note.path
        window.editor.setPlainText("# 自分の版\n\n編集中\n")
        path.write_text("# 外部の版\n\n外から書き換えた\n", encoding="utf-8")

        window.close()  # ダイアログが出ると永久に返ってこない

    def test_競合したまま閉じても書いた内容が残る(self, window) -> None:
        """聞けないときは書いたものを失わない側に倒す。"""
        window.new_note()
        path = window.current_note.path
        window.editor.setPlainText("# 自分の版\n\n消えては困る内容\n")
        path.write_text("# 外部の版\n\n外から書き換えた\n", encoding="utf-8")

        window.close()

        rescued = list(window.vault.root.glob("* (競合 *).md"))
        assert len(rescued) == 1
        assert "消えては困る内容" in rescued[0].read_text(encoding="utf-8")

    def test_外部の版も残る(self, window) -> None:
        window.new_note()
        path = window.current_note.path
        window.editor.setPlainText("# 自分の版\n\n編集中\n")
        path.write_text("# 外部の版\n\n外から書き換えた\n", encoding="utf-8")

        window.close()
        assert "外から書き換えた" in path.read_text(encoding="utf-8")


class TestTrashFilter:
    def test_ゴミ箱を選ぶと捨てたノートが出る(self, window) -> None:
        from hitofude.ui.sidebar import TRASH

        window.new_note()
        window.editor.setPlainText("# 捨てるメモ\n\n本文\n")
        window.flush()
        window.trash_current()

        window.sidebar.select(TRASH)
        assert window.note_list.model().rowCount() == 1

    def test_ゴミ箱のノートを開ける(self, window) -> None:
        from hitofude.ui.sidebar import TRASH

        window.new_note()
        window.editor.setPlainText("# 捨てるメモ\n\n捨てた本文\n")
        window.flush()
        window.trash_current()

        window.sidebar.select(TRASH)
        window.note_list.setCurrentIndex(window.note_list.model().index(0))
        assert "捨てた本文" in window.editor.toPlainText()

    def test_ゴミ箱が空なら何も出ない(self, window) -> None:
        from hitofude.ui.sidebar import TRASH

        window.sidebar.select(TRASH)
        assert window.note_list.model().rowCount() == 0


class TestRenameOnTitleChange:
    """spec §7.1: タイトル変更時はファイルをリネームする。"""

    def test_見出しを変えるとファイル名も変わる(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n本文\n")
        window.flush()
        assert window.current_note.path.name == "会議メモ.md"

    def test_旧名のファイルは残らない(self, window) -> None:
        window.new_note()
        old = window.current_note.path
        window.editor.setPlainText("# 会議メモ\n\n本文\n")
        window.flush()
        assert not old.exists()

    def test_旧名はゴミ箱に残さない(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n本文\n")
        window.flush()
        assert list(window.vault.trash_dir.glob("*.md")) == []

    def test_一覧にも新しい名前で出る(self, window) -> None:
        from hitofude.ui.note_list import NoteRole

        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n本文\n")
        window.flush()
        model = window.note_list.model()
        assert model.rowCount() == 1
        assert model.data(model.index(0), NoteRole.TITLE) == "会議メモ"

    def test_手で付けた別名は勝手に変えない(self, window) -> None:
        """`2026-08-08-会議.md` のような命名を保存のたびに壊さない。"""
        path = window.vault.root / "2026-08-08-会議.md"
        path.write_text("# 会議メモ\n\n本文\n", encoding="utf-8")
        window._db.sync(window.vault)
        window.refresh()
        window.open_note(path)

        window.editor.setPlainText("# 会議メモ\n\n本文を足した\n")
        window.flush()
        assert window.current_note.path.name == "2026-08-08-会議.md"

    def test_同名があれば連番を付ける(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n一枚目\n")
        window.flush()
        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n二枚目\n")
        window.flush()
        assert window.current_note.path.name == "会議メモ-2.md"


class TestQuickOpen:
    """spec §5.4: `Cmd+O` のあいまい検索パレット。"""

    def _prepare(self, window) -> None:
        for title, body in (("会議メモ", "来期の予算について"), ("読書メモ", "第3章まで")):
            window.new_note()
            window.editor.setPlainText(f"# {title}\n\n{body}\n")
            window.flush()

    def test_タイトルで絞り込める(self, window) -> None:
        self._prepare(window)
        assert [i.title for i in window._quick_open_items("会議")] == ["会議メモ"]

    def test_飛び飛びの入力でも引ける(self, window) -> None:
        self._prepare(window)
        assert "会議メモ" in [i.title for i in window._quick_open_items("会モ")]

    def test_空なら全部出る(self, window) -> None:
        self._prepare(window)
        assert len(window._quick_open_items("")) == 2

    def test_選ぶとそのノートが開く(self, window) -> None:
        self._prepare(window)
        target = window._quick_open_items("会議")[0]
        window._on_palette_chosen(target.path)
        assert "来期の予算について" in window.editor.toPlainText()


class TestFullTextSearch:
    """spec §5.4: `Cmd+Shift+F` の全文検索。"""

    def _prepare(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n来期の**予算**について話した\n")
        window.flush()
        window.new_note()
        window.editor.setPlainText("# 読書メモ\n\n第3章まで読んだ\n")
        window.flush()

    def test_本文で引ける(self, window) -> None:
        self._prepare(window)
        assert [i.title for i in window._search_items("予算について")] == ["会議メモ"]

    def test_装飾をまたいでも引ける(self, window) -> None:
        self._prepare(window)
        assert len(window._search_items("予算について")) == 1

    def test_スニペットが付く(self, window) -> None:
        self._prepare(window)
        assert window._search_items("予算について")[0].subtitle

    def test_スニペットに一致部分の印が入る(self, window) -> None:
        from hitofude.storage.index_db import HIGHLIGHT_START

        self._prepare(window)
        assert HIGHLIGHT_START in window._search_items("予算について")[0].subtitle

    def test_一致しなければ空(self, window) -> None:
        self._prepare(window)
        assert window._search_items("存在しない語") == []

    def test_選ぶとそのノートが開く(self, window) -> None:
        self._prepare(window)
        target = window._search_items("予算について")[0]
        window._on_palette_chosen(target.path)
        assert "予算" in window.editor.toPlainText()
