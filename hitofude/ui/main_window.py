"""メインウィンドウ（spec §5.1）。

サイドバー / ノートリスト / エディタの 3 ペイン。ここが Phase 1〜4 で作った
部品を初めて 1 本に繋ぐ場所になる。

保存の流れ（§7.4）:
    テキスト変更 → デバウンス 800ms → 競合検査 → アトミック書き込み → 索引更新

ノート切り替え・ウィンドウの非活性化・終了時は待たずに書く。
"""

import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QKeySequence,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QSplitterHandle,
    QWidget,
)

from hitofude import APP_NAME, __version__
from hitofude.app import ThemeWatcher
from hitofude.config import Config
from hitofude.core.document import Note
from hitofude.editor import exporter
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.storage import autosave
from hitofude.storage.autosave import Debouncer
from hitofude.storage.index_db import IndexDb, NoteRow
from hitofude.storage.vault import (
    ConflictAction,
    Vault,
    check_conflict,
    keep_both_path,
    sanitize_filename,
    unique_path,
)
from hitofude.storage.watcher import ChangeKind, VaultWatcher
from hitofude.theme import ThemeColors
from hitofude.ui.conflict_dialog import ConflictDialog, Resolution
from hitofude.ui.note_list import NoteListView, NoteRole
from hitofude.ui.preferences import PreferencesDialog
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter
from hitofude.ui.sidebar import ALL, Filter, FilterKind, Sidebar

logger = logging.getLogger(__name__)


class _Divider(QSplitterHandle):
    """ペインの境界に引く 1px の線。"""

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.splitter().rule_color))


class PaneSplitter(QSplitter):
    """区切り線を自前で描く QSplitter。

    **スタイルシートを使わない。** `setStyleSheet()` は子ウィジェットにも
    波及し、`QPalette` より優先されるため、エディタのテーマ切替が効かなく
    なる（実際に踏んだ）。線 1 本のために表示系全体の仕組みを壊せない。
    """

    def __init__(self, rule_color: str, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.rule_color = rule_color
        self.setHandleWidth(SPLITTER_HANDLE_WIDTH)

    def createHandle(self) -> QSplitterHandle:
        return _Divider(self.orientation(), self)

    def set_rule_color(self, color: str) -> None:
        self.rule_color = color
        for index in range(1, self.count()):
            self.handle(index).update()


class _SyncReporter(QObject):
    """ワーカーから Qt スレッドへ結果を渡すための口。"""

    finished = Signal(object)
    failed = Signal(object)


class _IndexSyncTask(QRunnable):
    """vault の走査を背景で回す（spec §6.6, §7.3）。

    5,000 ノートの初回構築は約 10 秒かかる。同期で走らせると、その間
    ウィンドウが固まって操作できない。UI 側は前回の索引を読んだまま
    操作でき、走査が終わったら一覧を差し替える。

    **ワーカーは自分の `IndexDb` を開く。** sqlite3 の接続はスレッドを
    またげないため、UI 側の接続を使い回してはいけない。
    """

    def __init__(self, db_path: Path, vault: Vault, reporter: _SyncReporter) -> None:
        super().__init__()
        self._db_path = db_path
        self._vault = vault
        self._reporter = reporter

    def run(self) -> None:
        try:
            with IndexDb(self._db_path) as db:
                result = db.sync(self._vault)
        except Exception as error:
            logger.exception("索引の同期に失敗した")
            self._reporter.failed.emit(error)
            return
        self._reporter.finished.emit(result)


DEFAULT_SIZE = (1100, 720)
MINIMUM_SIZE = (720, 480)
SAVE_TICK_MS = 200
# ペインの区切り線。細くしないと掴む場所ではなく境界として読まれない
SPLITTER_HANDLE_WIDTH = 1
STASH_INTERVAL_SECONDS = 2.0
NEW_NOTE_TITLE = "無題"


class MainWindow(QMainWindow):
    def __init__(self, config: Config | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config if config is not None else Config()
        self._vault = Vault(self._config.vault_path)
        self._vault.ensure_layout()
        self._vault.purge_trash(self._config.trash_days)

        self._db = IndexDb(self._vault.managed_dir / "index.sqlite")
        self._note: Note | None = None
        self._loading = False
        self._opening = False
        self._filter: Filter = ALL

        self._build_ui()
        self._build_menus()
        self._restore_layout()

        self._debouncer = Debouncer()
        self._recovery_root = autosave.recovery_root(self._vault.root)
        self._last_stash = 0.0
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(SAVE_TICK_MS)
        self._save_timer.timeout.connect(self._on_save_tick)
        self._save_timer.start()

        self._watcher = VaultWatcher(self._vault, self)
        self._watcher.changed.connect(self._on_external_change)
        self._watcher.start()

        # **親を付けない。** ウィンドウの子にすると、ワーカーが結果を返す前に
        # ウィンドウごと破棄されて "Signal source has been deleted" で落ちる。
        # Python 側の参照（ここと QRunnable）が生存を保つ
        self._sync_reporter = _SyncReporter()
        self._sync_reporter.finished.connect(self._on_index_synced)
        self._sync_reporter.failed.connect(self._on_index_sync_failed)
        self._syncing_index = False

        self._seed_manual()
        self.refresh()  # 前回の索引で先に描く。走査を待たずに操作できる
        self.start_index_sync()
        self.offer_recovery()

    # ------------------------------------------------------------------ 構築

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        self._theme_watcher = ThemeWatcher(self._config.theme_mode, parent=self)
        theme = self._theme_watcher.colors

        self._sidebar = Sidebar()
        self._note_list = NoteListView(theme=theme)
        self._editor = MarkdownEditor(
            theme=theme,
            font_family=self._config.font_family,
            base_point_size=self._config.font_point_size,
        )

        self._splitter = PaneSplitter(theme.rule)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._note_list)
        self._splitter.addWidget(self._editor)
        self._splitter.setStretchFactor(2, 1)
        self._splitter.setChildrenCollapsible(False)

        self.setCentralWidget(self._splitter)

        self._note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._note_list.customContextMenuRequested.connect(self._show_context_menu)

        self._sidebar.filter_changed.connect(self._on_filter_changed)
        self._note_list.note_activated.connect(self._on_note_activated)
        self._editor.textChanged.connect(self._on_text_changed)
        self._theme_watcher.changed.connect(self._on_theme_changed)

        self._editor.set_mono_family(self._config.mono_family)
        self._apply_list_font()
        self._editor.setFocus()

    def _apply_list_font(self) -> None:
        """一覧の文字も本文フォントに合わせる。"""
        font = self._note_list.font()
        font.setFamily(self._config.font_family)
        self._note_list.setFont(font)
        self._note_list.viewport().update()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")
        self._add_action(file_menu, "新規ノート", QKeySequence.StandardKey.New, self.new_note)
        self._add_action(file_menu, "保存", QKeySequence.StandardKey.Save, self.flush)
        file_menu.addSeparator()
        self._add_action(file_menu, "ピン留め", "Ctrl+Shift+P", self.toggle_pin_current)
        self._add_action(file_menu, "ゴミ箱へ移動", "Ctrl+Backspace", self.trash_current)
        file_menu.addSeparator()
        self._add_action(file_menu, "Markdown で書き出す…", "Ctrl+Shift+M", self.export_markdown)
        self._add_action(file_menu, "HTML で書き出す…", "Ctrl+Shift+E", self.export_html)
        self._add_action(file_menu, "PDF で書き出す…", "Ctrl+P", self.export_pdf)

        # StandardKey.Preferences はこの環境で空を返し、キーボードから
        # 到達できなくなる。macOS の慣習どおり明示する
        self._add_action(file_menu, "環境設定…", "Ctrl+,", self.open_preferences)

        search_menu = self.menuBar().addMenu("検索")
        self._add_action(search_menu, "クイックオープン", "Ctrl+O", self.quick_open)
        self._add_action(search_menu, "全文検索", "Ctrl+Shift+F", self.full_text_search)

        edit_menu = self.menuBar().addMenu("編集")
        # **Option を含むショートカットは使わない。** macOS では Option が
        # 文字合成に使われ、Cmd+Option+T は `†` を生む。ショートカットが
        # 発火せず、選択中だと選択範囲がその 1 文字に置き換わって消える
        self._add_action(edit_menu, "表を整形", "Ctrl+Shift+L", self._editor.format_table)

        view_menu = self.menuBar().addMenu("表示")
        self._add_action(view_menu, "サイドバー", "Ctrl+1", self.toggle_sidebar)
        self._add_action(view_menu, "ノートリスト", "Ctrl+2", self.toggle_note_list)
        view_menu.addSeparator()
        self._add_action(view_menu, "ソースモード", "Ctrl+/", self._editor.toggle_source_mode)
        self._add_action(
            view_menu, "フォーカスモード", "Ctrl+Shift+D", self._editor.toggle_focus_mode
        )
        self._add_action(
            view_menu, "タイプライタモード", "Ctrl+Shift+Y", self._editor.toggle_typewriter_mode
        )

        help_menu = self.menuBar().addMenu("ヘルプ")
        self._add_action(help_menu, f"{APP_NAME} について", "", self.show_about)

    def _add_action(self, menu, label: str, shortcut, slot) -> QAction:
        action = QAction(label, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        self.addAction(action)  # メニューを開かなくてもショートカットが効くように
        return action

    def _restore_layout(self) -> None:
        geometry = self._config.window_geometry
        if geometry is not None:
            self.restoreGeometry(geometry)
        self._splitter.setSizes(self._config.splitter_sizes)
        self._sidebar.setVisible(self._config.sidebar_visible)
        self._note_list.setVisible(self._config.note_list_visible)

    # ------------------------------------------------------------------ 参照

    @property
    def editor(self) -> MarkdownEditor:
        return self._editor

    @property
    def note_list(self) -> NoteListView:
        return self._note_list

    @property
    def sidebar(self) -> Sidebar:
        return self._sidebar

    @property
    def vault(self) -> Vault:
        return self._vault

    @property
    def vault_index(self) -> IndexDb:
        return self._db

    @property
    def theme_watcher(self) -> ThemeWatcher:
        return self._theme_watcher

    @property
    def current_note(self) -> Note | None:
        return self._note

    def _seed_manual(self) -> None:
        """初回起動なら使い方ノートを置いて開く（サンプル兼マニュアル）。"""
        note = self._vault.seed_manual()
        if note is None:
            return
        self._db.upsert_note(note, self._vault.root)
        self.open_note(note.path)
        logger.info("使い方ノートを置いた: %s", note.path.name)

    # ------------------------------------------------------------ リカバリ

    def pending_recovery(self) -> list:
        return autosave.pending(self._recovery_root)

    def offer_recovery(self) -> list[Path]:
        """前回の未保存内容があれば復元を尋ねる（spec §9 Phase 6）。"""
        stashes = self.pending_recovery()
        if not stashes:
            return []

        answer = QMessageBox.question(
            self,
            "保存されていない変更が見つかりました",
            f"前回終了したときに保存されていない変更が {len(stashes)} 件あります。\n"
            "別ファイルとして復元しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            autosave.clear_all(self._recovery_root)
            return []
        return self.restore_pending()

    def restore_pending(self) -> list[Path]:
        """退避を別ファイルとして書き出す。

        **元のファイルを上書きしない。** 復元は「見つかった内容を失わない」
        ためのもので、ディスク上の内容を捨ててよいとは限らない。
        """
        restored: list[Path] = []
        for stashed in self.pending_recovery():
            stamp = datetime.fromtimestamp(stashed.stashed_at).date().isoformat()
            target = unique_path(self._vault.root, f"{stashed.source.stem} (復元 {stamp})")
            self._watcher.suppress(target)
            self._vault.write(target, stashed.text)
            self._db.upsert_note(self._vault.read(target), self._vault.root)
            restored.append(target)
            logger.info("未保存の内容を復元した: %s", target.name)

        autosave.clear_all(self._recovery_root)
        self.refresh()
        return restored

    # ------------------------------------------------------------------ 索引

    index_synced = Signal(object)
    """走査が終わったときに `SyncResult` を載せて飛ぶ。"""

    def start_index_sync(self) -> None:
        """vault の走査を背景で始める。二重に走らせない。"""
        if self._syncing_index:
            return
        self._syncing_index = True
        QThreadPool.globalInstance().start(
            _IndexSyncTask(self._db.path, self._vault, self._sync_reporter)
        )

    def wait_for_index_sync(self, timeout_ms: int = 30000) -> bool:
        """走査の完了を待つ。テストと終了処理から使う。"""
        return QThreadPool.globalInstance().waitForDone(timeout_ms)

    def _on_index_synced(self, result) -> None:
        self._syncing_index = False
        if result.changed:
            self.refresh()
        self.index_synced.emit(result)

    def _on_index_sync_failed(self, error: Exception) -> None:
        self._syncing_index = False
        logger.warning("索引の同期に失敗: %s", error)

    # ------------------------------------------------------------------ 一覧

    def refresh(self) -> None:
        """索引から一覧とタグツリーを引き直す。"""
        self._note_list.set_rows(self._rows_for(self._filter))
        self._sidebar.set_tags(self._db.tag_tree())

    def _rows_for(self, target: Filter) -> list[NoteRow]:
        match target.kind:
            case FilterKind.ALL:
                return self._db.notes()
            case FilterKind.PINNED:
                return [row for row in self._db.notes() if row.pinned]
            case FilterKind.TRASH:
                return self._trash_rows()
            case FilterKind.TAG:
                return self._db.notes_with_tag(target.tag or "")
        return []

    def _trash_rows(self) -> list[NoteRow]:
        """ゴミ箱の中身を並べる。

        `.trash` は索引の対象外（`vault.scan()` が除外する）なので、
        ここだけはファイルから直に読む。ゴミ箱は件数が少ない前提。
        """
        rows: list[NoteRow] = []
        for path in sorted(self._vault.trash_dir.glob("*.md")):
            try:
                note = self._vault.read(path)
            except OSError:
                continue
            rows.append(
                NoteRow(
                    id=str(path),
                    path=path.relative_to(self._vault.root),
                    title=note.title,
                    preview=note.preview,
                    modified_at=str(note.meta.get("modified", "")),
                    mtime_ns=note.mtime_ns,
                    size_bytes=note.size_bytes,
                    pinned=False,
                )
            )
        return rows

    def set_filter(self, target: Filter) -> None:
        self._filter = target
        self._note_list.set_rows(self._rows_for(target))

    def _on_filter_changed(self, target: Filter) -> None:
        self.set_filter(target)

    # ------------------------------------------------------- 一覧からの操作

    def _show_context_menu(self, point) -> None:
        relative = self._note_list.indexAt(point).data(NoteRole.PATH)
        if relative is None:
            return
        menu = self.context_menu_for(Path(relative))
        menu.exec(self._note_list.viewport().mapToGlobal(point))
        menu.deleteLater()

    def context_menu_for(self, relative: Path) -> QMenu:
        """一覧の右クリックメニュー。ゴミ箱かどうかで中身が変わる。

        ゴミ箱の中身にピン留めや改名を許すと、戻したときの状態が読めない。
        ここで出せる操作を絞っておく。
        """
        path = self._vault.root / relative
        menu = QMenu(self)
        if self._filter.kind is FilterKind.TRASH:
            menu.addAction("元に戻す").triggered.connect(lambda: self.restore_note(path))
            return menu

        label = "ピン留めを外す" if self._is_pinned(path) else "ピン留め"
        menu.addAction(label).triggered.connect(lambda: self.toggle_pin(path))
        menu.addSeparator()
        menu.addAction("ゴミ箱へ移動").triggered.connect(lambda: self.trash_note(path))
        return menu

    def _is_pinned(self, path: Path) -> bool:
        try:
            return self._vault.read(path).pinned
        except OSError:
            return False

    def restore_note(self, path: Path) -> Path | None:
        """ゴミ箱から vault 直下へ戻す。戻した先を返す。

        **索引にも入れる。** ファイルを動かすだけでは一覧に出てこない。
        """
        if not path.is_file():
            return None
        self._watcher.suppress(path)
        target = self._vault.restore(path)
        self._watcher.suppress(target)
        self._db.upsert_note(self._vault.read(target), self._vault.root)
        self.refresh()
        logger.info("ゴミ箱から戻した: %s", target.name)
        return target

    def toggle_pin(self, path: Path) -> bool:
        """ピン留めを反転する。反転後の状態を返す。

        開いているノートなら、先に保存してから本文を読み直す。
        ピン留めは front matter を書き換えるので、**エディタが古い本文の
        ままだと次の保存でピン留めが黙って消える**。
        """
        if not path.is_file():
            return False
        current = self._note is not None and self._note.path == path
        if current:
            self.flush()

        self._watcher.suppress(path)
        note = self._vault.set_pinned(path, not self._is_pinned(path))
        self._db.upsert_note(note, self._vault.root)
        if current:
            self._reload_open_note(note)
        self.refresh()
        return note.pinned

    def toggle_pin_current(self) -> bool:
        return False if self._note is None else self.toggle_pin(self._note.path)

    def trash_note(self, path: Path) -> None:
        if self._note is not None and self._note.path == path:
            self.trash_current()
            return
        self._watcher.suppress(path)
        self._vault.trash(path)
        self._db.remove_path(self._vault.root, path)
        self.refresh()

    def _reload_open_note(self, note: Note) -> None:
        """開いているノートの本文をディスクの内容へ差し替える。

        カーソル位置は保つ。ノートを開くときと違い、**ユーザーは今そこを
        見ている**ので、先頭へ飛ばされると操作の流れが切れる。
        """
        position = self._editor.textCursor().position()
        self._note = note
        self._loading = True
        try:
            self._editor.setPlainText(note.text)
            cursor = self._editor.textCursor()
            cursor.setPosition(min(position, self._editor.document().characterCount() - 1))
            self._editor.setTextCursor(cursor)
            self._editor.document().setModified(False)
        finally:
            self._loading = False
        self._debouncer.clear()

    # ------------------------------------------------------------------ 編集

    def _on_note_activated(self, relative: Path) -> None:
        self.open_note(self._vault.root / relative)

    def open_note(self, path: Path) -> None:
        """ノートを開く。切り替え前に未保存の内容を書き出す（§7.4）。"""
        if self._opening:
            return  # 保存 → 一覧更新 → 選択変更 と回って戻ってくるのを止める
        self._opening = True
        try:
            self._open_note(path)
        finally:
            self._opening = False

    def _open_note(self, path: Path) -> None:
        self.flush()
        try:
            note = self._vault.read(path)
        except OSError:
            logger.warning("ノートを開けなかった: %s", path)
            return

        self._note = note
        self._loading = True
        try:
            self._editor.setPlainText(note.text)
            self._editor.document().setModified(False)
        finally:
            self._loading = False
        self._debouncer.clear()
        self.setWindowTitle(f"{note.title} — {APP_NAME}")

    def new_note(self) -> None:
        self.flush()
        note = self._vault.create(NEW_NOTE_TITLE)
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)
        self._note_list.select_path(note.path.relative_to(self._vault.root))

    def trash_current(self) -> None:
        if self._note is None:
            return
        path = self._note.path
        self._watcher.suppress(path)
        self._vault.trash(path)
        self._db.remove_path(self._vault.root, path)
        self._note = None
        self._editor.clear()
        self.refresh()

    def _on_text_changed(self) -> None:
        if self._loading or self._note is None:
            return
        self._debouncer.touch()

    def _on_save_tick(self) -> None:
        if self._debouncer.due():
            self.flush()
            return
        if self._debouncer.pending:
            self._maybe_stash()

    def _maybe_stash(self) -> None:
        """未保存の内容を退避する（spec §9 Phase 6）。

        毎チック書くと 1 秒に 5 回ディスクを叩くので、間隔を空ける。
        通常は 800ms で保存されるのでここまで来ることは少ないが、
        保存できない状態（競合の未解決など）が続いたときの保険になる。
        """
        now = time.monotonic()
        if self._note is None or now - self._last_stash < STASH_INTERVAL_SECONDS:
            return
        self._last_stash = now
        try:
            autosave.stash(self._recovery_root, self._note.path, self._editor.toPlainText())
        except OSError:
            logger.warning("未保存内容の退避に失敗した", exc_info=True)

    def flush(self, *, interactive: bool = True) -> None:
        """未保存の内容を今すぐ書く（§7.4 の即時フラッシュ）。

        `interactive=False` のときは競合してもダイアログを出さない。
        終了処理から呼ぶときに使う。**`closeEvent` の中でモーダルを開くと
        アプリが終了できなくなる**（実装中に踏んだ）。
        """
        if self._note is None or not self._debouncer.pending:
            return
        self._debouncer.clear()
        self._save(self._editor.toPlainText(), interactive=interactive)

    def _save(self, text: str, *, interactive: bool = True) -> None:
        note = self._note
        if note is None:
            return

        action = check_conflict(note, dirty=True)
        if action is ConflictAction.ASK:
            if interactive:
                if not self._resolve_conflict(note, text):
                    return
            else:
                # 聞けないときは書いたものを失わない側に倒す。
                # ダイアログの既定（両方残す）と同じ判断
                self._keep_both(note, text)
                return
        if action is ConflictAction.RELOAD:
            # 自分は書いていないのにここへ来ることはないが、来たら外部を優先する
            self.open_note(note.path)
            return

        payload = self._vault.touch_modified(text)
        self._watcher.suppress(note.path)
        self._vault.write(note.path, payload)

        autosave.discard(self._recovery_root, note.path)
        self._note = self._rename_if_title_changed(note, self._vault.read(note.path))
        self._db.upsert_note(self._note, self._vault.root)
        self.refresh()
        self.setWindowTitle(f"{self._note.title} — {APP_NAME}")

    def _rename_if_title_changed(self, previous: Note, current: Note) -> Note:
        """タイトルが変わったらファイル名も合わせる（spec §7.1）。

        ただし**ファイル名がそれまでのタイトルと一致していたときだけ**動かす。
        `2026-08-08-会議.md` のように意図して別名を付けている人のファイルを、
        保存のたびに勝手に改名してしまわないため。
        """
        if current.path.stem != sanitize_filename(previous.title):
            return current

        new_stem = sanitize_filename(current.title)
        if new_stem == current.path.stem:
            return current

        self._watcher.suppress(current.path)
        target = self._vault.rename(current.path, current.title)
        self._watcher.suppress(target)
        self._db.remove_path(self._vault.root, current.path)
        logger.info("タイトル変更に合わせて改名した: %s → %s", current.path.name, target.name)
        return self._vault.read(target)

    def _resolve_conflict(self, note: Note, text: str) -> bool:
        """競合ダイアログを出す。書き込みを続けてよいなら True。"""
        dialog = ConflictDialog(note.path, self)
        dialog.exec()

        match dialog.resolution:
            case Resolution.KEEP_BOTH:
                self.open_note(self._keep_both(note, text))
                return False
            case Resolution.TAKE_EXTERNAL:
                self.open_note(note.path)
                return False
            case Resolution.TAKE_MINE:
                return True
            case _:
                return False

    def _keep_both(self, note: Note, text: str) -> Path:
        """自分の版を別名で保存する（spec §7.5）。書いたものを失わない道。"""
        target = keep_both_path(note.path)
        self._watcher.suppress(target)
        self._vault.write(target, text)
        self._db.upsert_note(self._vault.read(target), self._vault.root)
        logger.info("競合したため別名で保存した: %s", target.name)
        self.refresh()
        return target

    # ------------------------------------------------------------------ 外部変更

    def _on_external_change(self, kind: ChangeKind, path: Path) -> None:
        """spec §7.5 の分岐。"""
        if kind is ChangeKind.DELETED:
            self._db.remove_path(self._vault.root, path)
            if self._note is not None and self._note.path == path:
                self._on_note_deleted(path)
            self.refresh()
            return

        if path.exists():
            self._db.upsert_note(self._vault.read(path), self._vault.root)

        if self._note is not None and self._note.path == path:
            if self._debouncer.pending:
                return  # 保存時に競合として扱う
            self.open_note(path)  # 未編集なら静かに読み直す
        self.refresh()

    def _on_note_deleted(self, path: Path) -> None:
        answer = QMessageBox.question(
            self,
            "ファイルが削除されました",
            f"「{path.name}」は外部で削除されました。\n編集中の内容で作り直しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._watcher.suppress(path)
            self._vault.write(path, self._editor.toPlainText())
            self._note = self._vault.read(path)
            self._db.upsert_note(self._note, self._vault.root)
        else:
            self._note = None
            self._editor.clear()

    # ------------------------------------------------------------------ 検索

    def quick_open(self) -> None:
        """`Cmd+O`。タイトルへのあいまい一致で開く（spec §5.4）。"""
        palette = self._make_palette("ノートを開く…")
        palette.set_provider(self._quick_open_items)
        palette.open_with()

    def full_text_search(self) -> None:
        """`Cmd+Shift+F`。本文を検索する（spec §5.4）。"""
        palette = self._make_palette("本文を検索…")
        palette.set_provider(self._search_items)
        palette.open_with()

    def _make_palette(self, placeholder: str) -> Palette:
        palette = Palette(self, placeholder=placeholder, theme=self._theme_watcher.colors)
        palette.chosen.connect(self._on_palette_chosen)
        # 開くたびに作り直す。前回の入力と結果が残っていると誤操作の元になる
        palette.finished.connect(palette.deleteLater)
        return palette

    def _quick_open_items(self, query: str) -> list[PaletteItem]:
        items = [
            PaletteItem(title=row.title, subtitle=row.preview, path=row.path)
            for row in self._db.notes()
        ]
        return fuzzy_filter(query, items)

    def _search_items(self, query: str) -> list[PaletteItem]:
        return [
            PaletteItem(title=hit.title, subtitle=hit.snippet, path=hit.path)
            for hit in self._db.search(query)
        ]

    def _on_palette_chosen(self, relative: Path) -> None:
        self.open_note(self._vault.root / relative)
        self._note_list.select_path(relative)

    # ------------------------------------------------------------ エクスポート

    def export_markdown(self) -> Path | None:
        """Markdown のまま書き出す。変換を挟まない。"""
        return self._export("Markdown で書き出す", "Markdown (*.md)", ".md", self._write_markdown)

    def export_html(self) -> Path | None:
        """spec §9 Phase 6。R2 の例外はエクスポート層に閉じている。"""
        return self._export("HTML で書き出す", "HTML (*.html)", ".html", self._write_html)

    def export_pdf(self) -> Path | None:
        return self._export("PDF で書き出す", "PDF (*.pdf)", ".pdf", self._write_pdf)

    def _export(self, caption: str, filter_: str, suffix: str, writer) -> Path | None:
        """保存先を尋ねて書き出す。`writer` は `(Path, str) -> Path`。"""
        if self._note is None:
            return None
        self.flush()
        suggested = str(Path.home() / f"{self._note.title}{suffix}")
        chosen, _ = QFileDialog.getSaveFileName(self, caption, suggested, filter_)
        if not chosen:
            return None
        return writer(Path(chosen), self._editor.toPlainText())

    def _write_markdown(self, target: Path, text: str) -> Path:
        return exporter.write_markdown(target, text)

    def _write_html(self, target: Path, text: str) -> Path:
        return exporter.write_html(
            target,
            text,
            title=self._note.title if self._note else "",
            theme=self._theme_watcher.colors,
        )

    def _write_pdf(self, target: Path, text: str) -> Path:
        return exporter.write_pdf(
            target,
            text,
            theme=self._theme_watcher.colors,
            base_point_size=self._config.font_point_size,
        )

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"{APP_NAME} について",
            f"<b>{APP_NAME}</b> {__version__}<br><br>"
            "ライブプレビュー型 Markdown エディタ<br>"
            "ノートは素の <code>.md</code> として保存されます。",
        )

    def open_preferences(self) -> None:
        """`Cmd+,`（spec §5.4）。"""
        dialog = PreferencesDialog(self._config, self)
        dialog.applied.connect(self._apply_preferences)
        dialog.exec()

    def _apply_preferences(self) -> None:
        """設定を今の画面へ反映する。保管フォルダだけは再起動が要る。"""
        self._editor.set_font_family(self._config.font_family)
        self._editor.set_base_point_size(self._config.font_point_size)
        self._editor.set_mono_family(self._config.mono_family)
        self._apply_list_font()
        self._theme_watcher.set_mode(self._config.theme_mode)
        self._vault.purge_trash(self._config.trash_days)

    # ------------------------------------------------------------------ 表示

    def toggle_sidebar(self) -> None:
        self._sidebar.setVisible(not self._sidebar.isVisible())

    def toggle_note_list(self) -> None:
        self._note_list.setVisible(not self._note_list.isVisible())

    def _apply_splitter_style(self, theme: ThemeColors) -> None:
        """ペインの境界に 1px の線を引く。"""
        self._splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {theme.rule}; }}")

    def _on_theme_changed(self, colors: ThemeColors) -> None:
        self._editor.set_theme(colors)
        self._note_list.set_theme(colors)
        self._splitter.set_rule_color(colors.rule)

    # ------------------------------------------------------------------ 終了

    def closeEvent(self, event: QCloseEvent) -> None:
        # 終了時は競合してもダイアログを出さない。ここでモーダルを開くと
        # アプリが終了できなくなる
        self.flush(interactive=False)
        self._config.splitter_sizes = self._splitter.sizes()
        self._config.sidebar_visible = self._sidebar.isVisible()
        self._config.note_list_visible = self._note_list.isVisible()
        self._config.window_geometry = self.saveGeometry()
        self._config.sync()

        self._save_timer.stop()
        self._watcher.stop()
        # ワーカーが自分の接続で書いている最中に落とさない
        self.wait_for_index_sync()
        self._db.close()
        super().closeEvent(event)
