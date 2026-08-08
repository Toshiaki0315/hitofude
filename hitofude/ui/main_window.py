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

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QWidget,
)

from hitofude import APP_NAME, __version__
from hitofude.app import ThemeWatcher
from hitofude.config import Config
from hitofude.core import frontmatter
from hitofude.core.document import Note, with_title
from hitofude.core.stats import count as count_text
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
from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.index_sync import IndexSyncTask, SyncReporter
from hitofude.ui.menus import build_menus
from hitofude.ui.note_list import NoteListView, NoteRole
from hitofude.ui.panes import (
    NOTE_LIST_MIN_WIDTH,
    SIDEBAR_MIN_WIDTH,
    PaneSplitter,
)
from hitofude.ui.preferences import PreferencesDialog
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter
from hitofude.ui.sidebar import ALL, Filter, FilterKind, Sidebar

logger = logging.getLogger(__name__)


DEFAULT_SIZE = (1100, 720)
MINIMUM_SIZE = (720, 480)
SAVE_TICK_MS = 200
STASH_INTERVAL_SECONDS = 2.0
# 文字数を数え直すまでの待ち。38,000 字のノートで 40ms 掛かる（実測）ので
# 1 打ごとには数えられない
STATS_DELAY_MS = 400
DIRTY_MARK = "•"

NEW_NOTE_TITLE = "無題"
PINNED_NOTICE = "ピン留めしているノートは削除できません。先にピン留めを外してください。"
NOTICE_MS = 5000


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
        self._sync_reporter = SyncReporter()
        self._sync_reporter.finished.connect(self._on_index_synced)
        self._sync_reporter.failed.connect(self._on_index_sync_failed)
        self._syncing_index = False
        self._closing = False
        self._previous_path: Path | None = None

        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(STATS_DELAY_MS)
        self._stats_timer.timeout.connect(self._update_stats)

        self._seed_manual()
        self.refresh()  # 前回の索引で先に描く。走査を待たずに操作できる
        self._reopen_last_note()
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
        self._pane = EditorPane(
            theme=theme,
            font_family=self._config.font_family,
            base_point_size=self._config.font_point_size,
        )
        self._editor = self._pane.editor

        self._sidebar.setMinimumWidth(SIDEBAR_MIN_WIDTH)
        self._note_list.setMinimumWidth(NOTE_LIST_MIN_WIDTH)

        self._splitter = PaneSplitter(theme.rule)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._note_list)
        self._splitter.addWidget(self._pane)
        self._splitter.setStretchFactor(2, 1)
        self._splitter.setChildrenCollapsible(False)

        self.setCentralWidget(self._splitter)

        self._stats_label = QLabel("", self)
        self.statusBar().addPermanentWidget(self._stats_label)
        self.statusBar().setSizeGripEnabled(False)

        self._note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._note_list.customContextMenuRequested.connect(self._show_context_menu)

        self._sidebar.filter_changed.connect(self._on_filter_changed)
        self._note_list.note_activated.connect(self._on_note_activated)
        self._editor.textChanged.connect(self._on_text_changed)
        self._theme_watcher.changed.connect(self._on_theme_changed)

        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
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
        build_menus(self)

    def _restore_layout(self) -> None:
        geometry = self._config.window_geometry
        if geometry is not None:
            self.restoreGeometry(geometry)
        # **表示状態を先に決める。** 隠れているウィジェットは幅 0 になるので、
        # 順序が逆だと割り当てた幅がその場で捨てられる
        self._sidebar.setVisible(self._config.sidebar_visible)
        self._note_list.setVisible(self._config.note_list_visible)
        self._splitter.restore_sizes(self._config.splitter_sizes)

    # ------------------------------------------------------------------ 参照

    @property
    def editor(self) -> MarkdownEditor:
        return self._editor

    @property
    def editor_pane(self) -> EditorPane:
        return self._pane

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

    def _reopen_last_note(self) -> None:
        """前回開いていたノートを開き直す（タスク A-1）。

        **開けなくても静かに諦める。** 消えていることも、保管フォルダを
        変えたこともある。起動が止まる理由にはならない。
        """
        if self._note is not None:
            return  # 使い方ノートを置いた直後など、既に開いている

        relative = self._config.last_note
        if relative is None:
            return

        path = self._vault.root / relative
        if not path.is_file():
            self._config.last_note = None
            return

        self.open_note(path)
        self._note_list.select_path(relative)

    def _remember_note(self, path: Path | None) -> None:
        """開いているノートを覚える。

        終了時ではなく**開いた時点で書く**。終了時だけだと強制終了で忘れる。
        """
        if path is None:
            self._config.last_note = None
            return
        try:
            self._config.last_note = path.relative_to(self._vault.root)
        except ValueError:
            # vault の外のファイル。覚えても次に開けない
            self._config.last_note = None

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
            IndexSyncTask(self._db.path, self._vault, self._sync_reporter)
        )

    def wait_for_index_sync(self, timeout_ms: int = 30000) -> bool:
        """走査の完了を待つ。テストと終了処理から使う。"""
        return QThreadPool.globalInstance().waitForDone(timeout_ms)

    def _on_index_synced(self, result) -> None:
        self._syncing_index = False
        if self._closing:
            # ワーカーの完了は待てても、そこから飛んだシグナルは主スレッドの
            # 待ち行列に残る。`closeEvent` が DB を閉じた後にこれが処理されると
            # 閉じた接続へ問い合わせて落ちる
            return
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

    # --------------------------------------------------------------- 添付

    def save_attachment(self, data: bytes, suffix: str) -> str | None:
        """貼られた画像を vault へ置き、本文へ挿す Markdown を返す。

        エディタから呼ばれる。**保存できなければ None を返す**。壊れた
        リンクを本文へ書くより、何も入らないほうが分かりやすい。
        """
        try:
            path = self._vault.add_attachment(data, suffix)
        except OSError:
            logger.warning("添付を保存できなかった", exc_info=True)
            return None

        # 自分で書いたファイルなので、外部変更として拾わせない
        self._watcher.suppress(path)
        logger.info("添付を保存した: %s", path.name)
        return self._vault.attachment_link(path)

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
        menu.addAction("名前を変更…").triggered.connect(lambda: self.prompt_rename(path))
        menu.addSeparator()
        trash = menu.addAction("ゴミ箱へ移動")
        trash.triggered.connect(lambda: self.trash_note(path))
        # 項目ごと消すと理由が分からない。押せない状態で見せる
        trash.setEnabled(not self._is_pinned(path))
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
        current = self._note is not None and self._note.path == path
        if current:
            self.flush()
            # 保存でタイトルが変わるとファイル名も変わる（`_rename_if_title_changed`）。
            # 古いパスを掴んだままだと、存在しないファイルを読みに行く
            if self._note is not None:
                path = self._note.path
        if not path.is_file():
            return False

        self._watcher.suppress(path)
        note = self._vault.set_pinned(path, not self._is_pinned(path))
        self._db.upsert_note(note, self._vault.root)
        if current:
            self._reload_open_note(note)
        self.refresh()
        return note.pinned

    def toggle_pin_current(self) -> bool:
        return False if self._note is None else self.toggle_pin(self._note.path)

    def prompt_rename(self, path: Path) -> Path | None:
        try:
            current = self._vault.read(path).title
        except OSError:
            return None
        title, accepted = QInputDialog.getText(self, "名前を変更", "新しい名前", text=current)
        return self.rename_note(path, title) if accepted else None

    def rename_note(self, path: Path, title: str) -> Path:
        """タイトルを付け替える（ADR-0005）。

        **本文の見出しを書き換える。** タイトルは本文から導かれるので、
        ファイル名だけ変えても一覧の表示は変わらず、真実が 2 つになる。
        ファイル名は保存時に見出しへ追従する（`_rename_if_title_changed`）。

        開いているノートはエディタ経由で書き換える。本文の編集なので、
        打ち間違えたら `Cmd+Z` で戻せるべき。
        """
        if not title.strip():
            return path
        if self._note is not None and self._note.path == path:
            return self._rename_open_note(title)
        return self._rename_stored_note(path, title)

    def _rename_open_note(self, title: str) -> Path:
        renamed = with_title(self._editor.toPlainText(), title)
        if renamed != self._editor.toPlainText():
            cursor = self._editor.textCursor()
            cursor.beginEditBlock()
            try:
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(renamed)
            finally:
                cursor.endEditBlock()
            self._debouncer.touch()
        self.flush()
        return self._note.path if self._note is not None else Path()

    def _rename_stored_note(self, path: Path, title: str) -> Path:
        try:
            renamed = with_title(path.read_text(encoding="utf-8"), title)
        except OSError:
            return path

        self._watcher.suppress(path)
        self._vault.write(path, renamed)

        target = self._vault.rename(path, title)
        if target != path:
            self._watcher.suppress(target)
            self._db.remove_path(self._vault.root, path)
        self._db.upsert_note(self._vault.read(target), self._vault.root)
        self.refresh()
        logger.info("名前を変えた: %s → %s", path.name, target.name)
        return target

    def trash_note(self, path: Path) -> bool:
        """ゴミ箱へ移す。移せたら True。

        **ピン留めしているノートは移さない。** ピン留めは「これは残す」と
        いう意思表示で、削除と噛み合わない。
        """
        if self._note is not None and self._note.path == path:
            return self.trash_current()
        if self._is_pinned(path):
            self._notify_pinned()
            return False

        self._watcher.suppress(path)
        self._vault.trash(path)
        self._db.remove_path(self._vault.root, path)
        self.refresh()
        return True

    def _notify_pinned(self) -> None:
        """黙って無視すると、押し間違いなのか壊れたのか分からない。"""
        self.statusBar().showMessage(PINNED_NOTICE, NOTICE_MS)

    def _place_cursor_at_body(self, text: str) -> None:
        offset = frontmatter.body_offset(text)
        if offset == 0:
            return
        cursor = self._editor.textCursor()
        cursor.setPosition(offset)
        self._editor.setTextCursor(cursor)

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
            limit = self._editor.document().characterCount() - 1
            body = frontmatter.body_offset(note.text)
            cursor.setPosition(max(body, min(position, limit)))
            self._editor.setTextCursor(cursor)
            self._editor.document().setModified(False)
        finally:
            self._loading = False
        self._debouncer.clear()
        self._pane.refresh_highlights()

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

        if self._note is not None and self._note.path != path:
            self._previous_path = self._note.path
        self._note = note
        self._loading = True
        try:
            self._editor.setPlainText(note.text)
            # `setPlainText()` はカーソルを位置 0 に置くが、そこは front matter の
            # 前にあたる。front matter は画面に見えないので、ユーザーは本文の
            # 先頭にいるつもりで打ち始める（R4 により位置と文字数は 1:1）
            self._place_cursor_at_body(note.text)
            self._editor.document().setModified(False)
        finally:
            self._loading = False
        self._debouncer.clear()
        self._pane.refresh_highlights()
        self._update_title()
        self._stats_timer.stop()
        self._update_stats()
        self._remember_note(note.path)

    def new_note(self) -> None:
        self.flush()
        note = self._vault.create(NEW_NOTE_TITLE)
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)
        self._note_list.select_path(note.path.relative_to(self._vault.root))

    def trash_current(self) -> bool:
        if self._note is None:
            return False
        if self._note.pinned:
            self._notify_pinned()
            return False

        path = self._note.path
        self._watcher.suppress(path)
        self._vault.trash(path)
        self._db.remove_path(self._vault.root, path)
        self._note = None
        self._editor.clear()
        self._remember_note(None)
        self.refresh()
        self._update_title()
        self._update_stats()
        return True

    def _on_text_changed(self) -> None:
        if self._loading or self._note is None:
            return
        self._debouncer.touch()
        self._update_title()
        self._stats_timer.start()

    # --------------------------------------------------------- 表示の更新

    def _update_title(self) -> None:
        """未保存なら印を付ける。

        保存は自動なので、書けているのか黙っていると分からない。
        """
        if self._note is None:
            self.setWindowTitle(APP_NAME)
            return
        mark = f"{DIRTY_MARK} " if self._debouncer.pending else ""
        self.setWindowTitle(f"{mark}{self._note.title} — {APP_NAME}")

    def _update_stats(self) -> None:
        if self._note is None:
            self._stats_label.setText("")
            return
        stats = count_text(self._editor.toPlainText())
        self._stats_label.setText(f"{stats.characters:,} 文字 / {stats.words:,} 語")

    def status_text(self) -> str:
        return self._stats_label.text()

    def dispatch_edit(self, name: str) -> None:
        """編集操作をフォーカスのあるウィジェットへ渡す。

        `QLineEdit` も `QPlainTextEdit` も同じ名前のメソッドを持つので、
        取り違えずにそのまま呼べる。
        """
        target = QApplication.focusWidget() or self._editor
        method = getattr(target, name, None)
        if callable(method):
            method()

    def open_previous_note(self) -> None:
        """直前に開いていたノートへ戻る。もう一度押すと行き来する。"""
        target = self._previous_path
        if target is None or not target.is_file():
            return
        self.open_note(target)

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
        self._update_title()
        self._remember_note(self._note.path)

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
            base_path=self._vault.root,
        )

    def _write_pdf(self, target: Path, text: str) -> Path:
        return exporter.write_pdf(
            target,
            text,
            theme=self._theme_watcher.colors,
            base_point_size=self._config.font_point_size,
            base_path=self._vault.root,
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
        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
        self._editor.set_mono_family(self._config.mono_family)
        self._apply_list_font()
        self._theme_watcher.set_mode(self._config.theme_mode)
        self._vault.purge_trash(self._config.trash_days)

    # ------------------------------------------------------------------ 表示

    def toggle_sidebar(self) -> None:
        self._splitter.toggle_pane(0)

    def toggle_note_list(self) -> None:
        self._splitter.toggle_pane(1)

    def _apply_splitter_style(self, theme: ThemeColors) -> None:
        """ペインの境界に 1px の線を引く。"""
        self._splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {theme.rule}; }}")

    def _on_theme_changed(self, colors: ThemeColors) -> None:
        self._pane.set_theme(colors)
        self._note_list.set_theme(colors)
        self._splitter.set_rule_color(colors.rule)

    # ------------------------------------------------------------------ 終了

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        # 終了時は競合してもダイアログを出さない。ここでモーダルを開くと
        # アプリが終了できなくなる
        self.flush(interactive=False)
        # **`isVisible()` を使わない。** ウィンドウ自体が隠れていると子も
        # False を返すため、`Cmd+H` で隠してから終了すると、出していたペインが
        # 「隠す」で保存され、次の起動が真っ白な窓になる（実際に踏んだ）
        self._config.splitter_sizes = self._splitter.sizes_to_keep()
        self._config.sidebar_visible = not self._sidebar.isHidden()
        self._config.note_list_visible = not self._note_list.isHidden()
        self._config.window_geometry = self.saveGeometry()
        self._config.sync()

        self._save_timer.stop()
        self._watcher.stop()
        # ワーカーが自分の接続で書いている最中に落とさない
        self.wait_for_index_sync()
        self._db.close()
        super().closeEvent(event)
