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
from hitofude.ui.quick_open import PaletteItem
from hitofude.ui.sidebar import ALL, Filter, FilterKind

pytestmark = pytest.mark.gui


@pytest.fixture
def window(window):
    window.show()
    return window


class TestLayout:
    def test_既定は3ペインに見える(self, window) -> None:
        """アウトライン（ADR-0022）とアシスタント（ADR-0025）を足したので
        中身は 5 つ。**どちらも既定では隠れている**ので、見た目は
        spec §5.1 の 3 ペインのまま。"""
        splitter = window.centralWidget()
        assert isinstance(splitter, QSplitter)
        # サイドバー・一覧・本文・アウトライン・アシスタント・参照（U-1）
        assert splitter.count() == 6
        assert splitter.widget(3).isHidden() is True
        assert splitter.widget(4).isHidden() is True
        assert sum(not splitter.widget(i).isHidden() for i in range(5)) == 3

    def test_並びはサイドバーリストエディタ(self, window) -> None:
        splitter = window.centralWidget()
        assert splitter.widget(0) is window.sidebar
        # 一覧は「新規」ボタンごとペインに包まれている
        assert splitter.widget(1) is window.note_list_pane
        assert window.note_list_pane.note_list is window.note_list
        assert splitter.widget(2) is window.editor_pane
        assert window.editor_pane.editor is window.editor

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
        assert (config.vault_path / ".OboeGaki").is_dir()

    def test_索引ファイルが作られる(self, window, config) -> None:
        assert (config.vault_path / ".OboeGaki" / "index.sqlite").is_file()

    def test_既存のノートを読み込む(self, qtbot, config, tmp_path) -> None:
        vault_root = config.vault_path
        vault_root.mkdir(parents=True, exist_ok=True)
        (vault_root / "既存のメモ.md").write_text("# 既存のメモ\n\n本文\n", encoding="utf-8")

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            # 走査は背景で回るので、終わるまで待つ（§6.6）
            with qtbot.waitSignal(window.index_synced, timeout=15000):
                pass
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


class TestDirtyTracking:
    """「編集中」は文字が変わったときだけ（C-5）。

    リビール（カーソル移動時の rehighlightBlock）は書式を変えるので
    textChanged を発火させる。それを編集と数えると、読んでいるだけで
    800ms 後に保存が走り、front matter の modified が嘘をつく。
    """

    def opened(self, window):
        note = window.vault.create("移動メモ", "# 移動メモ\n\n**強調**と*斜体*の行\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)
        return note

    def move_around(self, window) -> None:
        """マーカーの中や外へ動かしてリビールを起こす。"""
        end = window.editor.document().characterCount() - 1
        for position in (end, end - 5, end - 10, end - 15):
            cursor = window.editor.textCursor()
            cursor.setPosition(max(0, position))
            window.editor.setTextCursor(cursor)

    def test_カーソル移動だけでは編集中にならない(self, window) -> None:
        self.opened(window)
        self.move_around(window)
        assert not window._debouncer.pending

    def test_保存後のカーソル移動でも編集中に戻らない(self, window) -> None:
        from PySide6.QtGui import QTextCursor

        self.opened(window)
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("追記")
        window.flush()
        self.move_around(window)
        assert not window._debouncer.pending

    def test_文字を打てば編集中になる(self, window) -> None:
        """ガードが効きすぎないことの確認。"""
        from PySide6.QtGui import QTextCursor

        self.opened(window)
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("追記")
        assert window._debouncer.pending


class TestExternalChange:
    """spec §7.5。watchdog を待たず、シグナル相当を直接呼んで判定を見る。"""

    def test_未編集なら静かに読み直す(self, window) -> None:
        from hitofude.storage.watcher import ChangeKind

        window.new_note()
        path = window.current_note.path
        path.write_text("# 外から\n\n書き換えられた\n", encoding="utf-8")

        window._on_external_change(ChangeKind.MODIFIED, path)
        assert "書き換えられた" in window.editor.toPlainText()

    def test_読み直してもカーソルが飛ばない(self, window) -> None:
        """iCloud / Dropbox の同期は mtime 更新だけでも読み直しを起こす。

        `open_note()` で読み直すと `_place_cursor_at_body` がカーソルを
        本文先頭へ動かし、閲覧中に突然先頭へ飛ばされていた（回帰）。
        """
        from PySide6.QtGui import QTextCursor

        from hitofude.storage.watcher import ChangeKind

        # 本文のあるノートで見る。new_note() は本文が空で、末尾と本文先頭が
        # 同じ位置になり、飛んでいても検出できない
        note = window.vault.create("読み直しメモ", "# 読み直しメモ\n\n1 行目\n2 行目\n3 行目\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        position = window.editor.textCursor().position()

        # 外部で末尾に追記する（見出しは変えない → 保存時の自動改名を起こさない）
        source = note.path.read_text(encoding="utf-8")
        note.path.write_text(f"{source}外から追記\n", encoding="utf-8")

        window._on_external_change(ChangeKind.MODIFIED, note.path)
        assert "外から追記" in window.editor.toPlainText()  # 読み直されている
        assert window.editor.textCursor().position() == position  # 先頭へ飛ばない

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
        assert [i.title for i in window._search._quick_open_items("会議")] == ["会議メモ"]

    def test_飛び飛びの入力でも引ける(self, window) -> None:
        self._prepare(window)
        assert "会議メモ" in [i.title for i in window._search._quick_open_items("会モ")]

    def test_空なら全部出る(self, window) -> None:
        self._prepare(window)
        assert len(window._search._quick_open_items("")) == 2

    def test_選ぶとそのノートが開く(self, window) -> None:
        self._prepare(window)
        target = window._search._quick_open_items("会議")[0]
        window._search._on_palette_chosen(
            PaletteItem(title=target.title, subtitle="", path=target.path)
        )
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
        assert [i.title for i in window._search._search_items("予算について")] == ["会議メモ"]

    def test_装飾をまたいでも引ける(self, window) -> None:
        self._prepare(window)
        assert len(window._search._search_items("予算について")) == 1

    def test_スニペットが付く(self, window) -> None:
        self._prepare(window)
        assert window._search._search_items("予算について")[0].subtitle

    def test_スニペットに一致部分の印が入る(self, window) -> None:
        from hitofude.storage.index_db import HIGHLIGHT_START

        self._prepare(window)
        assert HIGHLIGHT_START in window._search._search_items("予算について")[0].subtitle

    def test_一致しなければ空(self, window) -> None:
        self._prepare(window)
        assert window._search._search_items("存在しない語") == []

    def test_選ぶとそのノートが開く(self, window) -> None:
        self._prepare(window)
        target = window._search._search_items("予算について")[0]
        window._search._on_palette_chosen(
            PaletteItem(title=target.title, subtitle="", path=target.path)
        )
        assert "予算" in window.editor.toPlainText()


class TestBackgroundIndexSync:
    """spec §6.6, §7.3: 起動時の走査は背景で回す。"""

    def test_起動直後に走査が終わる(self, window, qtbot) -> None:
        assert window.wait_for_index_sync() is True

    def test_既存ノートが走査で拾われる(self, qtbot, config) -> None:
        vault_root = config.vault_path
        vault_root.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            (vault_root / f"既存{index}.md").write_text(
                f"# 既存{index}\n\n本文\n", encoding="utf-8"
            )

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            with qtbot.waitSignal(window.index_synced, timeout=15000) as blocker:
                pass
            assert len(blocker.args[0].added) == 3
            assert window.note_list.model().rowCount() == 3
        finally:
            window.close()

    def test_走査中も一覧を触れる(self, qtbot, config) -> None:
        """UI は前回の索引を読んだまま操作できる（§7.3）。"""
        vault_root = config.vault_path
        vault_root.mkdir(parents=True, exist_ok=True)
        (vault_root / "既存.md").write_text("# 既存\n\n本文\n", encoding="utf-8")

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            # 走査の完了を待たずに呼べること（例外が出ない）
            window.refresh()
            window.note_list.current_path()
            window.wait_for_index_sync()
        finally:
            window.close()

    def test_二重に走らせない(self, window) -> None:
        window.wait_for_index_sync()
        window._syncing_index = True
        window.start_index_sync()  # 何も起きない
        assert window._syncing_index is True

    def test_ワーカーはUI側の接続を使わない(self, window) -> None:
        """sqlite3 の接続はスレッドをまたげない。

        ワーカーは db のパスだけを受け取り、自分で開く。
        """
        from hitofude.ui.index_sync import IndexSyncTask

        task = IndexSyncTask(window._db.path, window.vault, window._sync_reporter)
        assert task._db_path == window._db.path
        assert not hasattr(task, "_db")


class TestRecovery:
    """クラッシュリカバリ（タスク 6-6 / spec §9 Phase 6）。"""

    def test_保存できていれば退避は残らない(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n本文\n")
        window.flush()
        assert window.pending_recovery() == []

    def test_未保存のまま落ちた想定で退避される(self, window) -> None:
        from hitofude.storage import autosave

        window.new_note()
        window.editor.setPlainText("# メモ\n\n落ちる前に書いた\n")
        window._saver._last_stash = 0.0  # 間隔の待ちを飛ばす
        window._saver._maybe_stash()

        found = autosave.pending(window._recovery_root)
        assert len(found) == 1
        assert "落ちる前に書いた" in found[0].text

    def test_復元は別ファイルとして書く(self, window) -> None:
        """元のファイルを上書きしない。ディスク側を捨ててよいとは限らない。"""
        window.new_note()
        original = window.current_note.path
        original.write_text("# メモ\n\nディスク上の内容\n", encoding="utf-8")

        window.editor.setPlainText("# メモ\n\n復元したい内容\n")
        window._saver._last_stash = 0.0
        window._saver._maybe_stash()

        restored = window.restore_pending()
        assert len(restored) == 1
        assert "復元" in restored[0].name
        assert "復元したい内容" in restored[0].read_text(encoding="utf-8")
        assert "ディスク上の内容" in original.read_text(encoding="utf-8")

    def test_復元したら退避は消える(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n本文\n")
        window._saver._last_stash = 0.0
        window._saver._maybe_stash()
        window.restore_pending()
        assert window.pending_recovery() == []

    def test_復元したノートは一覧に出る(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n本文\n")
        window.flush()
        window.editor.setPlainText("# メモ\n\n未保存の続き\n")
        window._saver._last_stash = 0.0
        window._saver._maybe_stash()

        before = window.note_list.model().rowCount()
        window.restore_pending()
        assert window.note_list.model().rowCount() == before + 1

    def test_退避が無ければ何も聞かない(self, window) -> None:
        """QMessageBox が出るとテストが固まる。出ないことの確認でもある。"""
        assert window.offer_recovery() == []

    def test_保存すると退避が捨てられる(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n本文\n")
        window._saver._last_stash = 0.0
        window._saver._maybe_stash()
        assert window.pending_recovery() != []

        window._debouncer.touch()
        window.flush()
        assert window.pending_recovery() == []


class TestRefreshDoesNotReopen:
    """一覧の更新でノートが開き直されないこと（回帰テスト）。

    `set_rows()` は選択をやり直すので、そこで `note_activated` を出すと
    更新のたびに `open_note` → `flush` → 競合ダイアログ、と連鎖して
    アプリが固まる（実際に踏んだ）。
    """

    def test_一覧更新でノートを開き直さない(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# メモ\n\n本文\n")
        window.flush()

        opened: list = []
        window.note_list.note_activated.connect(opened.append)
        window.refresh()
        assert opened == []

    def test_行が増えても開き直さない(self, window) -> None:
        window.new_note()
        window.editor.setPlainText("# 一枚目\n\n本文\n")
        window.flush()

        opened: list = []
        window.note_list.note_activated.connect(opened.append)
        other = window.vault.root / "外から増えた.md"
        other.write_text("# 外から増えた\n\n本文\n", encoding="utf-8")
        window._db.upsert_note(window.vault.read(other), window.vault.root)
        window.refresh()
        assert opened == []

    def test_編集中の内容が一覧更新で消えない(self, window) -> None:
        """開き直すと setPlainText で書きかけが飛ぶ。"""
        window.new_note()
        window.editor.setPlainText("# メモ\n\n書きかけの内容\n")
        window.refresh()
        assert "書きかけの内容" in window.editor.toPlainText()

    def test_ユーザー操作の選択では開く(self, window) -> None:
        """止めるのはプログラムからの選択だけ。

        **今いる行を選び直しても何も起きない**（Qt は変化が無ければ
        `currentChanged` を出さない）。一覧は開いているノートに選択を
        合わせるようになったので、**別の行**へ動かして見る。
        """
        window.new_note()
        window.editor.setPlainText("# 一枚目\n\n本文\n")
        window.flush()
        window.new_note()
        window.editor.setPlainText("# 二枚目\n\n本文\n")
        window.flush()

        opened: list = []
        window.note_list.note_activated.connect(opened.append)
        here = window.note_list.currentIndex().row()
        window.note_list.setCurrentIndex(window.note_list.model().index(1 if here != 1 else 0))
        assert len(opened) == 1


class TestWelcomeNote:
    """初回起動時の使い方ノート（ユーザー要望）。

    他のテストは件数がずれるので置かせていない。ここだけ本来の挙動を見る。
    """

    @pytest.fixture
    def fresh_config(self, tmp_path: Path, qapp) -> Config:
        settings = QSettings(str(tmp_path / "fresh.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "FreshVault"
        return config

    def test_初回起動で置かれて開かれる(self, qtbot, fresh_config) -> None:
        window = MainWindow(fresh_config)
        qtbot.addWidget(window)
        try:
            assert window.note_list.model().rowCount() == 1
            assert window.current_note is not None
            assert "使い方" in window.current_note.path.name
            assert "Markdown" in window.editor.toPlainText()
        finally:
            window.close()

    def test_二度目の起動では増えない(self, qtbot, fresh_config) -> None:
        first = MainWindow(fresh_config)
        qtbot.addWidget(first)
        first.close()

        second = MainWindow(fresh_config)
        qtbot.addWidget(second)
        try:
            assert second.note_list.model().rowCount() == 1
        finally:
            second.close()

    def test_消したら復活しない(self, qtbot, fresh_config) -> None:
        first = MainWindow(fresh_config)
        qtbot.addWidget(first)
        path = first.current_note.path
        first.trash_current()
        first.close()

        second = MainWindow(fresh_config)
        qtbot.addWidget(second)
        try:
            assert second.note_list.model().rowCount() == 0
            assert not path.exists()
        finally:
            second.close()

    def test_タグが索引に入る(self, qtbot, fresh_config) -> None:
        window = MainWindow(fresh_config)
        qtbot.addWidget(window)
        try:
            window.wait_for_index_sync()
            assert [t.tag for t in window._db.tag_tree()]
        finally:
            window.close()


class TestExport:
    """書き出し（spec §9 Phase 6 + Markdown はユーザー要望）。

    ダイアログを開かずに書き出しの実体だけを通す。
    3 形式が同じ経路に乗っていることを見る。
    """

    SOURCE = "# 見出し\n\nこれは **強調** です。\n\n#タグ\n"

    def _open_note(self, window) -> None:
        window.new_note()
        window.editor.setPlainText(self.SOURCE)
        window.flush()

    def test_Markdownで書き出せる(self, window, tmp_path: Path) -> None:
        self._open_note(window)
        target = window._exports._write_markdown(tmp_path / "out.md", window.editor.toPlainText())
        assert target.read_text(encoding="utf-8") == self.SOURCE

    def test_Markdownはマーカーを保つ(self, window, tmp_path: Path) -> None:
        """R1: 書き出しても `**` は `**` のまま。"""
        self._open_note(window)
        window._exports._write_markdown(tmp_path / "out.md", window.editor.toPlainText())
        assert "**強調**" in (tmp_path / "out.md").read_text(encoding="utf-8")

    def test_HTMLで書き出せる(self, window, tmp_path: Path) -> None:
        self._open_note(window)
        window._exports._write_html(tmp_path / "out.html", window.editor.toPlainText())
        assert "<" in (tmp_path / "out.html").read_text(encoding="utf-8")

    def test_PDFで書き出せる(self, window, tmp_path: Path) -> None:
        self._open_note(window)
        window._exports._write_pdf(tmp_path / "out.pdf", window.editor.toPlainText())
        assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF")

    def test_ノートが無ければ何もしない(self, window) -> None:
        assert window.export_markdown() is None

    def test_書き出しても元のノートは残る(self, window, tmp_path: Path) -> None:
        self._open_note(window)
        path = window.current_note.path
        window._exports._write_markdown(tmp_path / "out.md", window.editor.toPlainText())
        assert path.is_file()
        assert "**強調**" in path.read_text(encoding="utf-8")


class TestCloseRace:
    """閉じたあとに走査結果が届く競合（実際に踏んだ）。

    `closeEvent` はワーカーの完了を待つが、**そこから飛んだシグナルは
    主スレッドの待ち行列に残る**。DB を閉じた後にそれが処理されると
    閉じた接続へ問い合わせて `ProgrammingError` で落ちる。
    """

    def test_閉じたあとに走査結果が届いても落ちない(self, qtbot, config) -> None:
        from types import SimpleNamespace

        window = MainWindow(config)
        qtbot.addWidget(window)
        window.close()

        window._on_index_synced(SimpleNamespace(changed=1))

    def test_閉じたあとの失敗通知でも落ちない(self, qtbot, config) -> None:
        window = MainWindow(config)
        qtbot.addWidget(window)
        window.close()

        window._on_index_sync_failed(OSError("後から届いた"))

    def test_走査に失敗したら知らせる(self, window) -> None:
        """**黙って空の一覧を出さない**（ユーザー報告 2026-08-23）。

        索引の作りが古くて書き込みが失敗し、一覧が空になった。記録に
        残すだけだったので、画面には「ノートはありません」としか出ず、
        **ノートが消えたようにしか見えなかった**（ファイルは無事）。
        """
        window._on_index_sync_failed(RuntimeError("だめだった"))
        assert "一覧" in window.notice() or "読み込め" in window.notice()

    def test_失敗を知らせても落ちない(self, window) -> None:
        window._on_index_sync_failed(RuntimeError("だめだった"))
        assert window.notice()


class TestIndexSyncTask:
    """走査ワーカーそのもの（監査で被覆 67% と判明）。

    ふだんは別スレッドで動くため計測に乗らず、**失敗経路が一度も
    通っていなかった**。ここでは直に呼んで両方を確かめる。
    """

    def build(self, window):
        from hitofude.ui.index_sync import IndexSyncTask, SyncReporter

        reporter = SyncReporter()
        got: dict[str, object] = {}
        reporter.finished.connect(lambda result: got.update(finished=result))
        reporter.failed.connect(lambda error: got.update(failed=error))
        return IndexSyncTask(window._db.path, window.vault, reporter), got

    def test_走査できたら結果が飛ぶ(self, window, config) -> None:
        window.vault.create("走査されるノート", "# 走査されるノート\n")
        task, got = self.build(window)

        task.run()
        assert "finished" in got
        assert got["finished"].changed >= 1

    def test_失敗したら失敗が飛ぶ(self, window, monkeypatch) -> None:
        """走査が落ちても、UI 側は前回の索引のまま操作を続けられる。"""
        from hitofude.storage.index_db import IndexDb

        def explode(self, vault):
            raise OSError("読めない")

        monkeypatch.setattr(IndexDb, "sync", explode)
        task, got = self.build(window)

        task.run()
        assert "failed" in got
        assert "finished" not in got

    def test_失敗しても例外を投げない(self, window, monkeypatch) -> None:
        """`QRunnable` から例外が出るとスレッドプールごと不安定になる。"""
        from hitofude.storage.index_db import IndexDb

        monkeypatch.setattr(IndexDb, "sync", lambda self, vault: 1 / 0)
        task, _ = self.build(window)

        task.run()  # 落ちないこと

    def test_UI側の接続を使わない(self, window) -> None:
        """sqlite3 の接続はスレッドをまたげない。ワーカーは自分で開く。"""
        task, _ = self.build(window)
        assert task._db_path == window._db.path
        assert not hasattr(task, "_db")


class TestHugeFileGuard:
    """巨大ファイルガード（spec §6.6 / R7、TASKS 6-7）。"""

    def open_note_with(self, window, text: str):
        note = window.vault.create("大きなノート", text)
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window.open_note(note.path)
        return note

    def test_巨大なノートは装飾を止めて開く(self, window) -> None:
        from hitofude.core.stats import HUGE_FILE_LINES

        self.open_note_with(window, "# 見出し\n" + "本文\n" * HUGE_FILE_LINES)
        assert window.editor.highlighter.plain_mode is True
        assert "装飾を無効" in window.notice()

    def test_巨大なノートでも編集して保存できる(self, window) -> None:
        from PySide6.QtGui import QTextCursor

        from hitofude.core.stats import HUGE_FILE_LINES

        note = self.open_note_with(window, "# 見出し\n" + "本文\n" * HUGE_FILE_LINES)
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("追記した行")
        window.flush()
        assert "追記した行" in note.path.read_text(encoding="utf-8")

    def test_ふつうのノートに戻ると装飾も戻る(self, window) -> None:
        from hitofude.core.stats import HUGE_FILE_LINES

        self.open_note_with(window, "# 見出し\n" + "本文\n" * HUGE_FILE_LINES)
        small = window.vault.create("ふつうのノート", "# ふつうのノート\n\n**強調**\n")
        window.vault_index.upsert_note(small, window.vault.root)
        window.refresh()
        window.open_note(small.path)
        assert window.editor.highlighter.plain_mode is False
        data = window.editor.document().findBlockByNumber(2).userData()
        assert data is not None  # 解析が走っている


class TestStartupSweep:
    def test_起動時にクラッシュの残骸を掃除する(self, qtbot, config) -> None:
        """H-1 層 1 の配線。掃除の中身は tests/storage/test_vault.py が見る。"""
        import os
        import time

        from hitofude.ui.main_window import MainWindow

        vault_root = config.vault_path
        vault_root.mkdir(parents=True, exist_ok=True)
        orphan = vault_root / ".メモ.md.abc.tmp"
        orphan.write_text("残骸", encoding="utf-8")
        old = time.time() - 2 * 3600
        os.utime(orphan, (old, old))

        window = MainWindow(config)
        qtbot.addWidget(window)
        try:
            assert not orphan.exists()
        finally:
            window.close()


class TestClearedNote:
    """本文を全部消したらタイトルは「無題」へ戻る（ユーザー要望 2026-08-18）。

    以前は空本文のタイトルがファイル名へ落ちていたため、一度書いて
    改名が追従したあとに本文を消すと、前のタイトルが残って見えた。
    """

    def test_本文を消すとタイトルも一覧も無題に戻る(self, window) -> None:
        from hitofude.ui.note_list import NoteRole

        window.new_note()
        window.editor.setPlainText("# 会議メモ\n\n本文\n")
        window.flush()
        assert "会議メモ" in window.windowTitle()

        window.editor.selectAll()  # front matter は選ばれない（既存の守り）
        window.editor.textCursor().removeSelectedText()
        window.flush()

        assert "会議メモ" not in window.windowTitle()
        assert "無題" in window.windowTitle()
        # ファイル名もタイトルへ追従する（ADR-0005 の既存機構）
        assert window.current_note.path.name == "無題.md"
        model = window.note_list.model()
        titles = [model.data(model.index(row), NoteRole.TITLE) for row in range(model.rowCount())]
        assert titles == ["無題"]


class TestRecoveryKeepsFolder:
    """クラッシュ復元がフォルダのノートを直下へ出さない（コードレビュー指摘。
    K-1「分類したのに箱から飛び出す」の取り漏らし）。"""

    def test_復元コピーは元のフォルダにできる(self, window) -> None:
        from hitofude.storage import autosave

        folder = window.vault.root / "仕事"
        folder.mkdir()
        source = folder / "会議メモ.md"
        source.write_text("# 会議メモ\n\n本文\n", encoding="utf-8")
        autosave.stash(window._saver.recovery_root, source, "# 会議メモ\n\n未保存の本文\n")

        restored = window.restore_pending()
        assert len(restored) == 1
        assert restored[0].parent == folder, "復元コピーが直下へ出た"

    def test_フォルダが消えていれば直下へ(self, window) -> None:
        from hitofude.storage import autosave

        gone = window.vault.root / "消えた"
        source = gone / "メモ.md"
        autosave.stash(window._saver.recovery_root, source, "# メモ\n\n本文\n")

        restored = window.restore_pending()
        assert len(restored) == 1
        assert restored[0].parent == window.vault.root  # 無い箱は作らない（§7.1）


class TestCaseOnlyTitleChange:
    """見出しの大文字小文字だけ変えたとき（S-3）。

    `-2` が付くと、以後ファイル名（`meeting-2`）とタイトル（`meeting`）が
    食い違うため、`_rename_if_title_changed` の「**ファイル名がそれまでの
    タイトルと一致していたときだけ動かす**」という条件に掛からなくなる。
    **そのノートは二度とファイル名がタイトルに追従しない。**
    ここは保存の道から通しで見る。
    """

    def test_番号を付けずに改名する(self, window) -> None:
        note = window._vault.create("Meeting", "# Meeting\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_and_select(note.path)

        window.editor.setPlainText("# meeting\n\n本文\n")
        window.flush()
        assert window.current_note.path.name == "meeting.md"

    def test_その後もタイトルに追従する(self, window) -> None:
        """**後遺症が残らないこと。** ここが本題。"""
        note = window._vault.create("Meeting", "# Meeting\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_and_select(note.path)

        window.editor.setPlainText("# meeting\n\n本文\n")
        window.flush()
        window.editor.setPlainText("# 会議\n\n本文\n")
        window.flush()
        assert window.current_note.path.name == "会議.md"
