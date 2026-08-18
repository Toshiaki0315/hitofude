"""メインウィンドウ（spec §5.1）。

サイドバー / ノートリスト / エディタの 3 ペイン。ここが Phase 1〜4 で作った
部品を初めて 1 本に繋ぐ場所になる。

保存の流れ（§7.4）:
    テキスト変更 → デバウンス 800ms → 競合検査 → アトミック書き込み → 索引更新

ノート切り替え・ウィンドウの非活性化・終了時は待たずに書く。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)

from hitofude import APP_NAME, __version__
from hitofude.app import ThemeWatcher, apply_theme, set_macos_appearance
from hitofude.config import (
    CONTENT_WIDTH_PIXELS,
    DEFAULT_POINT_SIZE,
    MAX_POINT_SIZE,
    MIN_POINT_SIZE,
    Config,
)
from hitofude.core import frontmatter, textpos
from hitofude.core.activation import ALLOWED_SCHEMES
from hitofude.core.document import Note
from hitofude.core.stats import is_huge
from hitofude.core.wikilink import context_line, normalize, resolve
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.storage import autosave
from hitofude.storage.index_db import IndexDb, NoteRow, SortOrder
from hitofude.storage.vault import (
    Vault,
    unique_path,
)
from hitofude.storage.watcher import ChangeKind, VaultWatcher
from hitofude.theme import ThemeColors, ThemeMode
from hitofude.ui.backlink_bar import Backlink
from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.export_actions import ExportActions
from hitofude.ui.index_sync import IndexSyncTask, SyncReporter
from hitofude.ui.menus import build_menus
from hitofude.ui.note_actions import NoteActions
from hitofude.ui.note_list import NoteListView
from hitofude.ui.note_list_pane import EMPTY_NOTICE, NoteListPane
from hitofude.ui.panes import (
    SIDEBAR_MIN_WIDTH,
    PaneSplitter,
)
from hitofude.ui.preferences import PreferencesDialog
from hitofude.ui.save_controller import SaveController
from hitofude.ui.search_actions import SearchActions
from hitofude.ui.shortcut_sheet import ShortcutSheet
from hitofude.ui.sidebar import ALL, Filter, FilterKind, Sidebar
from hitofude.ui.status_bar import (  # noqa: F401  ASYNC_STATS_CHARS 等はテストが再輸出先として参照する
    ASYNC_STATS_CHARS,
    STATUS_RIGHT_MARGIN,
    StatusBarController,
)

logger = logging.getLogger(__name__)


DEFAULT_SIZE = (1100, 720)
MINIMUM_SIZE = (720, 480)
# 「直前のノートへ戻る」で遡れる数（C-8）
MAX_HISTORY = 20
DIRTY_MARK = "•"

# 帯に出すバックリンクの上限（E-6）。ここに出る数だけファイルを読むので、
# 際限なく増えると開くたびに遅くなる。読み切れない数を並べても使えない
MAX_BACKLINKS = 50

# 片づけの確認に並べる名前の数（E-5）。全部並べるとダイアログが画面を溢れる
CLEANUP_PREVIEW = 10

NEW_NOTE_TITLE = "無題"
PINNED_NOTICE = "ピン留めしているノートは削除できません。先にピン留めを外してください。"
HUGE_NOTE_NOTICE = "大きなノートのため、装飾を無効にして開きました（編集と保存はできます）"
NOTICE_MS = 5000

# `Cmd +` / `Cmd -` の 1 押しで動く量（G-5）。環境設定の刻みは 0.5pt だが、
# **押して分からない変化はもう一度押される**ので、こちらは 1pt にする
ZOOM_STEP = 1.0


def _empty_notice(target: Filter) -> str:
    """一覧が 0 件のときに出す案内（C-6 の文言を絞り込みごとに変える）。

    **次に何をすればよいかを言う。** ゴミ箱で「＋ で作れます」と案内すると、
    作ったノートはゴミ箱に入らないので、案内どおりにしても状況が変わらない
    （ユーザー指摘）。
    """
    match target.kind:
        case FilterKind.TRASH:
            return "ゴミ箱は空です。\n捨てたノートがここに 30 日残ります。"
        case FilterKind.PINNED:
            return "お気に入りはありません。\n一覧を右クリックしてピン留めできます。"
        case FilterKind.TAG:
            return f"「#{target.tag}」のノートはありません。\n本文に書くとここに集まります。"
        case _:
            return EMPTY_NOTICE


class MainWindow(QMainWindow):
    def __init__(self, config: Config | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config if config is not None else Config()
        self._vault = Vault(self._config.vault_path)
        self._vault.ensure_layout()
        self._vault.purge_trash(self._config.trash_days)
        self._vault.sweep_temp_files()  # クラッシュで残った .tmp の掃除（H-1）

        self._db = IndexDb(self._vault.managed_dir / "index.sqlite")
        self._note: Note | None = None
        self._loading = False
        self._opening = False
        self._filter: Filter = ALL

        # ノートの CRUD（ゴミ箱・ピン・改名・雛形・片づけ）は束ごと
        # 切り出してある（ui/note_actions.py）。メニューの結線より先に作る
        self._notes = NoteActions(self)

        self._build_ui()
        self._build_menus()
        self._restore_layout()

        # 保存フロー（デバウンス・競合・退避）は束ごと切り出してある
        # （ui/save_controller.py）。pending は保存の外からも見るので、
        # 同じオブジェクトへの別名を残す
        self._saver = SaveController(self)
        self._debouncer = self._saver.debouncer
        self._recovery_root = self._saver.recovery_root
        self._save_timer = self._saver.timer

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
        # 開いたノートの履歴（C-8）。**今いるノートは入れない。**
        # 入れると「戻る」の 1 回目が今の場所になり、押しても何も起きない
        self._history: list[Path] = []
        self._going_back = False

        self._seed_manual()
        self._vault.seed_templates()
        self.refresh()  # 前回の索引で先に描く。走査を待たずに操作できる
        self._reopen_last_note()
        self.start_index_sync()
        self.offer_recovery()

    # ------------------------------------------------------------------ 構築

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        # 配色を当てている最中に次が来ることがある（`_on_theme_changed`）
        self._applying_theme = False
        self._pending_theme: ThemeColors | None = None
        self._theme_watcher = ThemeWatcher(self._config.theme_mode, parent=self)
        theme = self._theme_watcher.colors
        # **起動時にも当てる。** `create_application()` は「システムのテーマ」で
        # パレットを当てるが、ここで使うのは「保存された設定」。食い違っていると
        # 切り替えの通知も飛ばないまま明るいまま残る
        self._apply_palette(theme)

        self._sidebar = Sidebar(theme=theme)
        self._list_pane = NoteListPane(theme=theme)
        self._note_list = self._list_pane.note_list
        self._pane = EditorPane(
            theme=theme,
            font_family=self._config.font_family,
            base_point_size=self._config.font_point_size,
        )
        self._editor = self._pane.editor

        self._sidebar.setMinimumWidth(SIDEBAR_MIN_WIDTH)

        self._splitter = PaneSplitter(theme.rule)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._list_pane)
        self._splitter.addWidget(self._pane)
        self._splitter.setStretchFactor(2, 1)
        self._splitter.setChildrenCollapsible(False)

        self.setCentralWidget(self._splitter)

        # 書き出した直後だけ出す（G-4）。**いちばん左寄り**に置く。
        # 隣は今のノートの状態を出す場所で、押せるものが混ざると紛らわしい
        # 書き出し・印刷・取り込みは束ごと切り出してある（ui/export_actions.py）。
        # G-4 の知らせ（ボタンとタイマ）も書き出しの一部なので、部品ごと持たせる
        self._exports = ExportActions(self)
        # 探す系（Cmd+O / Cmd+Shift+F / Cmd+R）も同じ作りで別モジュールに
        self._search = SearchActions(self)

        # **文字数より左に置く。** 右端は文字数の場所で、あとから増えたものを
        # 右へ足すと、保存のたびに文字数が横へ動いて見える
        # ステータスバーの 3 ラベルと集計の背景実行は束ごと切り出してある
        # （ui/status_bar.py）。ラベルはテストからも見るので別名を残す
        self._status = StatusBarController(self)
        self._mode_label = self._status.mode_label
        self._saved_label = self._status.saved_label
        self._stats_label = self._status.stats_label
        self._stats_reporter = self._status.reporter
        self._stats_timer = self._status.stats_timer

        self._list_pane.new_note_requested.connect(self.new_note)
        self._list_pane.sort_order_changed.connect(self.set_sort_order)
        self._editor.link_activated.connect(self.activate_link)
        self._editor.tag_activated.connect(self.activate_tag)
        self._editor.note_activated.connect(self.activate_note)
        self._editor.modes_changed.connect(self._update_modes)
        self._pane.backlinks.opened.connect(self._on_backlink_opened)
        self._pane.backlinks.toggled.connect(self._remember_backlinks)
        self._pane.backlinks.set_expanded(self._config.backlinks_expanded)
        self._list_pane.set_sort_order(self._config.sort_order)
        self._note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._note_list.customContextMenuRequested.connect(self._show_context_menu)

        self._sidebar.set_line_spacing(self._config.line_spacing)
        self._note_list.set_line_spacing(self._config.line_spacing)
        self._editor.set_content_width(CONTENT_WIDTH_PIXELS[self._config.content_width])
        self._sidebar.filter_changed.connect(self._on_filter_changed)
        self._sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sidebar.customContextMenuRequested.connect(self._show_sidebar_menu)
        self._note_list.note_activated.connect(self._on_note_activated)
        self._note_list.files_dropped.connect(self._notes.import_note_files)
        self._editor.textChanged.connect(self._on_text_changed)
        self._theme_watcher.changed.connect(self._on_theme_changed)

        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
        self._editor.set_tag_source(self._known_tags)
        self._editor.set_mono_family(self._config.mono_family)
        self._editor.set_tab_width(self._config.tab_width)
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
        self._list_pane.setVisible(self._config.note_list_visible)
        self._pane.set_toolbar_visible(self._config.toolbar_visible)
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
    def note_list_pane(self) -> NoteListPane:
        return self._list_pane

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
    def config(self) -> Config:
        return self._config

    @property
    def reveal_button(self) -> QToolButton:
        """書き出した直後だけ出る「Finder で表示」（G-4）。"""
        return self._exports.reveal_button

    @property
    def export_timer(self) -> QTimer:
        return self._exports.export_timer

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
        order = self._config.sort_order
        match target.kind:
            case FilterKind.ALL:
                return self._db.notes(order=order)
            case FilterKind.PINNED:
                return [row for row in self._db.notes(order=order) if row.pinned]
            case FilterKind.TRASH:
                return self._notes.trash_rows()
            case FilterKind.TAG:
                return self._db.notes_with_tag(target.tag or "", order=order)
        return []

    def set_sort_order(self, order: SortOrder) -> None:
        """一覧の並び順を変えて覚える（C-3）。"""
        self._config.sort_order = order
        self._list_pane.set_sort_order(order)
        self.refresh()

    def set_filter(self, target: Filter) -> None:
        self._filter = target
        self._list_pane.set_empty_notice(_empty_notice(target))
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

    def _show_sidebar_menu(self, point) -> None:
        self._notes.show_sidebar_menu(point)

    def sidebar_menu_for(self, target: Filter) -> QMenu | None:
        return self._notes.sidebar_menu_for(target)

    def _show_context_menu(self, point) -> None:
        self._notes.show_context_menu(point)

    def context_menu_for(self, relative: Path) -> QMenu:
        return self._notes.context_menu_for(relative)

    def restore_note(self, path: Path) -> Path | None:
        return self._notes.restore_note(path)

    def delete_permanently(self, path: Path) -> bool:
        return self._notes.delete_permanently(path)

    def empty_trash(self) -> int:
        return self._notes.empty_trash()

    def _close_current(self) -> None:
        """開いているノートを閉じる。**保存はしない**（消す直前に呼ぶため）。"""
        self._note = None
        self._editor.clear()
        # 待ちを残すと、次のノートを開くまで 200ms ごとに flush が空振りする
        self._debouncer.clear()
        self._remember_note(None)
        self._update_title()
        self._update_stats()

    def toggle_pin(self, path: Path) -> bool:
        return self._notes.toggle_pin(path)

    def toggle_pin_current(self) -> bool:
        return self._notes.toggle_pin_current()

    def prompt_rename(self, path: Path) -> Path | None:
        return self._notes.prompt_rename(path)

    def rename_note(self, path: Path, title: str) -> Path:
        """タイトルを付け替える（ADR-0005）。実体は NoteActions。"""
        return self._notes.rename_note(path, title)

    def trash_note(self, path: Path) -> bool:
        return self._notes.trash_note(path)

    def _apply_huge_guard(self, text: str) -> None:
        """巨大ファイルガード（spec §6.6 / R7、TASKS 6-7）。

        装飾（scan + classify + setFormat）は行数に比例して効く。上限を
        超えたノートは装飾を止めて素のテキストとして開き、そのことを知らせる。
        編集と保存は今まで通りできる。**setPlainText の前に呼ぶ**こと
        （初回ハイライトが走る前にモードを決める）。
        """
        huge = is_huge(text)
        self._editor.highlighter.set_plain_mode(huge)
        if huge:
            self.statusBar().showMessage(HUGE_NOTE_NOTICE, NOTICE_MS)

    def _place_cursor_at_body(self, text: str) -> None:
        offset = frontmatter.body_offset(text)
        if offset == 0:
            return
        cursor = self._editor.textCursor()
        # body_offset は Python 単位、setPosition は UTF-16 単位
        cursor.setPosition(textpos.py_to_utf16(text, offset))
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
            self._apply_huge_guard(note.text)
            self._editor.setPlainText(note.text)
            cursor = self._editor.textCursor()
            limit = self._editor.document().characterCount() - 1
            body = textpos.py_to_utf16(note.text, frontmatter.body_offset(note.text))
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
            self._push_history(self._note.path)
        self._note = note
        self._loading = True
        try:
            self._apply_huge_guard(note.text)
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
        # 別のノートの保存時刻を出したままにしない（C-5）
        self._show_saved(None)
        self._remember_note(note.path)
        self._update_backlinks()

    def new_note(self) -> None:
        self.flush()
        self._open_created(self._vault.create(NEW_NOTE_TITLE))

    def _open_created(self, note: Note, cursor: int | None = None) -> None:
        """作った / 取り込んだノートを索引へ入れ、一覧を更新して開く。

        「upsert → refresh → open → select」の 4 連は作成系の全入口
        （新規・雛形・今日のノート・wikilink・取り込み・マニュアル設置）で
        同じ並びになる。ばらばらに書くと select 漏れが起きる
        （place_manual で実際に漏れていた）。
        """
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)
        self._note_list.select_path(note.path.relative_to(self._vault.root))
        if cursor is not None:
            self._place_cursor(cursor)

    # ------------------------------------------------------------- テンプレート

    def new_from_template(self) -> bool:
        """`Cmd+Shift+N`（E-4）。"""
        return self._notes.new_from_template()

    def create_from_template(self, path: Path) -> Note | None:
        return self._notes.create_from_template(path)

    def open_daily_note(self, day: datetime | None = None) -> Note:
        """`Cmd+T`（E-4）。"""
        return self._notes.open_daily_note(day)

    def _place_cursor(self, position: int | None) -> None:
        """`{{cursor}}` の位置へキャレットを置く（E-4）。

        文字は隠していても実在するので、ソースの位置がそのまま使える（R4）。
        """
        if position is None:
            return
        cursor = self._editor.textCursor()
        cursor.setPosition(min(position, len(self._editor.toPlainText())))
        self._editor.setTextCursor(cursor)
        self._editor.setFocus()

    def trash_current(self) -> bool:
        return self._notes.trash_current()

    def _on_text_changed(self) -> None:
        if self._loading or self._note is None:
            return
        # textChanged は**書式の変更でも**発火する。リビール（カーソル移動時の
        # rehighlightBlock）を編集と数えると、読んでいるだけで 800ms 後に保存が
        # 走り、front matter の modified が嘘をつく（C-5）。ハイライタの書式変更は
        # isModified を立てないので、文字が実際に変わったときだけ通す
        if not self._editor.document().isModified():
            return
        self._debouncer.touch()
        self._update_title()
        self._stats_timer.start()
        # 古い時刻が残っていると今の状態と食い違う（C-5）
        self._show_saved(None)

    # --------------------------------------------------------- 表示の更新

    def _show_saved(self, at: "datetime | None") -> None:
        """保存済みの合図（C-5）。実体は StatusBarController。"""
        self._status.show_saved(at)

    def saved_text(self) -> str:
        return self._status.saved_text()

    def _update_title(self) -> None:
        """未保存なら印を付ける。

        保存は自動なので、書けているのか黙っていると分からない。
        """
        if self._note is None:
            self.setWindowTitle(APP_NAME)
            return
        mark = f"{DIRTY_MARK} " if self._debouncer.pending else ""
        self.setWindowTitle(f"{mark}{self._note.title} — {APP_NAME}")

    def mode_text(self) -> str:
        return self._status.mode_text()

    def _update_modes(self) -> None:
        self._status.update_modes()

    def _update_stats(self) -> None:
        self._status.update_stats()

    def _on_stats_counted(self, token: int, stats) -> None:
        self._status.on_stats_counted(token, stats)

    @property
    def _stats_token(self) -> int:
        """テストが「今の合図」を読むために残している別名。"""
        return self._status.token

    def status_text(self) -> str:
        return self._status.status_text()

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
        """直前に開いていたノートへ戻る（C-8）。押すたびに遡れる。

        **消えたノートは飛ばす。** ゴミ箱へ入れた直後に押したとき、
        戻る先が無いのではなく「その前」へ行けるほうが自然。
        """
        while self._history:
            target = self._history.pop()
            if not target.is_file():
                continue
            # **戻る操作は履歴に積まない。** 積むと今いた場所が上に乗り、
            # 次に押したときそこへ戻ってしまう（2 つのノートを往復する）
            self._going_back = True
            try:
                self.open_note(target)
            finally:
                self._going_back = False
            return

    def _push_history(self, path: Path) -> None:
        """履歴に積む（C-8）。

        同じノートを続けて積まない。開き直すたびに増えると、戻るのに
        同じ数だけ押すことになる。
        """
        if self._going_back:
            return
        if self._history and self._history[-1] == path:
            return
        self._history.append(path)
        # 際限なく持つと閉じるときの保存も重くなる
        del self._history[:-MAX_HISTORY]

    def flush(self, *, interactive: bool = True) -> None:
        """未保存の内容を今すぐ書く（§7.4）。実体は SaveController。"""
        self._saver.flush(interactive=interactive)

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
            note = self._vault.read(path)
            self._db.upsert_note(note, self._vault.root)

            if self._note is not None and self._note.path == path:
                if self._debouncer.pending:
                    return  # 保存時に競合として扱う
                # 未編集なら静かに読み直す。open_note() だとカーソルが本文
                # 先頭へ動き、iCloud 同期のたびに閲覧位置が飛んでしまう
                self._reload_open_note(note)
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
            # 作り直した時点で編集中の内容は書けている
            self._editor.document().setModified(False)
            self._debouncer.clear()
            self._update_title()
        else:
            # 本文を消すだけだと、タイトル・last_note・未保存の待ちに
            # 消えたノートが残り、表示が嘘をつく
            self._close_current()

    # ------------------------------------------------------------------ 検索

    def quick_open(self) -> None:
        """`Cmd+O`（spec §5.4）。"""
        self._search.quick_open()

    def preview_in_browser(self) -> None:
        """書き出さずに既定のブラウザで確認する（E-2）。"""
        self._exports.preview_in_browser()

    def copy_as_html(self) -> None:
        """書式付きでクリップボードへ入れる（E-3）。"""
        self._exports.copy_as_html()

    def activate_link(self, url: str) -> None:
        """`Cmd+クリック` されたリンクを既定のブラウザで開く（D-1）。

        **開く先はここでも確かめる。** 判定は `core/activation.py` にあるが、
        外へ出す一歩手前でもう一度見る。増えた入口から素通りするのを防ぐ。
        """
        if not url.strip().lower().startswith(ALLOWED_SCHEMES):
            logger.warning("開かないスキーム: %s", url)
            return
        QDesktopServices.openUrl(QUrl(url))

    def activate_note(self, name: str) -> Path | None:
        """`Cmd+クリック` された `[[ノート名]]` を開く（E-6）。

        **無ければ作る**（ADR-0011）。書いた時点ではまだ無いノートを指すのが
        ふつうで、何も起きないと作るために一覧へ戻る手間が要る。

        同じ題名のノートが 2 つあるときは、一覧で上に来るほう（既定では
        最近更新したほう）を開く。**選ばせない。** 押した人が期待するのは
        「飛ぶ」ことで、選択肢を出すと流れが切れる。
        """
        target = normalize(name)
        if not target:
            return None

        rows = self._db.notes()
        found = resolve(target, [row.title for row in rows])
        if found is not None:
            row = next(row for row in rows if row.title == found)
            path = self._vault.root / row.path
            self.open_note(path)
            self._note_list.select_path(row.path)
            return path

        self.flush()
        note = self._vault.create(target, f"# {target}\n\n")
        self._open_created(note)
        logger.info("リンク先が無かったので作った: %s", note.path.name)
        return note.path

    def _remember_backlinks(self, expanded: bool) -> None:
        self._config.backlinks_expanded = expanded

    def toggle_backlinks(self) -> None:
        """`Cmd+4`。バックリンクの帯を開閉する（E-6 ③）。"""
        self._pane.backlinks.toggle()

    def _update_backlinks(self) -> None:
        """開いているノートを指しているノートを帯に流す（E-6 ③）。

        **自分自身は数えない。** 自分の中の `[[自分]]` は繋がりではない。

        指している行は、そのファイルを読んで取る（`context_line`）。冒頭
        （索引にある `preview`）では、長いノートから指されたときに関係が
        分からない。読むのはここに出る数だけなので安い。
        """
        bar = self._pane.backlinks
        if self._note is None:
            bar.set_links([])
            return

        relative = self._note.relative_to(self._vault.root)
        found: list[Backlink] = []
        for row in self._db.backlinks(self._note.title)[:MAX_BACKLINKS]:
            if str(row.path) == relative:
                continue
            found.append(
                Backlink(
                    title=row.title,
                    context=self._context_for(row.path),
                    path=row.path,
                )
            )
        bar.set_links(found)

    def _context_for(self, relative: Path) -> str:
        """そのノートが今のノートを指している行。読めなければ空。"""
        if self._note is None:
            return ""
        try:
            text = (self._vault.root / relative).read_text(encoding="utf-8")
        except OSError:
            return ""
        return context_line(text, self._note.title)

    def _on_backlink_opened(self, relative: Path) -> None:
        self.open_note(self._vault.root / relative)
        self._note_list.select_path(relative)

    def activate_tag(self, tag: str) -> None:
        """`Cmd+クリック` されたタグで一覧を絞る（D-2）。

        サイドバーの選択も動かす。一覧だけ変わると、今どれで絞っているか
        分からなくなる。
        """
        target = Filter(kind=FilterKind.TAG, tag=tag)
        self._sidebar.select(target)
        self.set_filter(target)

    def open_outline(self) -> None:
        """`Cmd+R`（C-2）。"""
        self._search.open_outline()

    def _known_tags(self) -> list[str]:
        """索引にあるタグ（C-4 / 補完の候補）。件数の多い順ではなく名前順。

        探しているものが五十音で見つかるほうが速い。
        """
        return sorted(entry.tag for entry in self._db.tag_tree())

    def jump_to_line(self, line: int) -> None:
        """その行の先頭へカーソルを移す（C-2）。"""
        self._search.jump_to_line(line)

    def full_text_search(self) -> None:
        """`Cmd+Shift+F`（spec §5.4 / G-1）。"""
        self._search.full_text_search()

    # ------------------------------------------------------------ エクスポート

    def export_markdown(self) -> Path | None:
        return self._exports.export_markdown()

    def export_html(self) -> Path | None:
        return self._exports.export_html()

    def export_pdf(self) -> Path | None:
        return self._exports.export_pdf()

    def export_pptx(self) -> Path | None:
        return self._exports.export_pptx()

    def print_note(self) -> bool:
        """`Cmd+P`（C-9）。"""
        return self._exports.print_note()

    def hide_export_notice(self) -> None:
        self._exports.hide_notice()

    def reveal_in_finder(self, path: Path) -> None:
        self._exports.reveal_in_finder(path)

    def import_document(self) -> Path | None:
        """「ファイル」→「読み込む…」（F-2）。"""
        return self._exports.import_document()

    def cleanup_attachments(self) -> int:
        """使っていない添付をゴミ箱へ移す（E-5）。実体は NoteActions。"""
        return self._notes.cleanup_attachments()

    def place_manual(self) -> None:
        """ヘルプ →「使い方のノートを置き直す」。

        **既にあるノートは消さない。** 書き足したメモごと消えては困るので、
        別のファイルとして置く（`Vault.place_manual`）。
        """
        note = self._vault.place_manual()
        if note is None:
            return
        self._open_created(note)

    def show_shortcuts(self) -> None:
        """`Cmd+?`。ショートカットの一覧を出す（C-7）。"""
        sheet = ShortcutSheet(self)
        sheet.finished.connect(sheet.deleteLater)
        sheet.show()

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
        # exec() 後も親の子リストに残り続ける。QFontComboBox ×2 を抱えた
        # ダイアログが開くたびに溜まる（Palette 等は finished→deleteLater 済み）
        dialog.deleteLater()

    def zoom_in(self) -> bool:
        """`Cmd +`。本文を 1pt 大きくする（G-5）。変わったら True。"""
        return self._set_font_size(self._config.font_point_size + ZOOM_STEP)

    def zoom_out(self) -> bool:
        """`Cmd -`。本文を 1pt 小さくする（G-5）。"""
        return self._set_font_size(self._config.font_point_size - ZOOM_STEP)

    def reset_zoom(self) -> bool:
        """`Cmd 0`。既定の大きさへ戻す（G-5）。"""
        return self._set_font_size(DEFAULT_POINT_SIZE)

    def _set_font_size(self, size: float) -> bool:
        """本文の大きさを変えて覚える。

        **環境設定と同じ値を触る。** 別に持つと、片方で変えたときに
        もう片方が古い値を書き戻す。

        **端では丸める。** 上限まで 0.5pt しか無くても、そこまでは動かす
        （押したのに何も起きないより、行けるところまで行くほうが素直）。
        """
        clamped = min(max(size, MIN_POINT_SIZE), MAX_POINT_SIZE)
        if clamped == self._config.font_point_size:
            return False
        self._config.font_point_size = clamped
        self._editor.set_base_point_size(clamped)
        # 1pt の差は見て取りにくい。**変えたことが分かるように**数字を出す
        self.statusBar().showMessage(f"文字サイズ {clamped:g}pt", NOTICE_MS)
        return True

    def _apply_preferences(self) -> None:
        """設定を今の画面へ反映する。保管フォルダだけは再起動が要る。"""
        self._editor.set_font_family(self._config.font_family)
        self._editor.set_base_point_size(self._config.font_point_size)
        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
        self._editor.set_mono_family(self._config.mono_family)
        self._editor.set_tab_width(self._config.tab_width)
        self._sidebar.set_line_spacing(self._config.line_spacing)
        self._note_list.set_line_spacing(self._config.line_spacing)
        self._editor.set_content_width(CONTENT_WIDTH_PIXELS[self._config.content_width])
        self._apply_list_font()
        self._theme_watcher.set_mode(self._config.theme_mode)
        self._vault.purge_trash(self._config.trash_days)

    # ------------------------------------------------------------------ 表示

    def toggle_sidebar(self) -> None:
        self._splitter.toggle_pane(0)

    def toggle_note_list(self) -> None:
        self._splitter.toggle_pane(1)

    def toggle_toolbar(self) -> None:
        self._pane.set_toolbar_visible(not self._pane.toolbar_visible())

    def _apply_splitter_style(self, theme: ThemeColors) -> None:
        """ペインの境界に 1px の線を引く。"""
        self._splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {theme.rule}; }}")

    def _apply_palette(self, colors: ThemeColors) -> None:
        """配色を `QPalette` へ流し込む（spec §5.3）。

        ここを忘れると、自前で色を持っているエディタだけが変わり、
        サイドバーと一覧は明るいまま残る。ダークではノートのタイトルが
        白地に薄い灰色になり、ほぼ読めない。
        """
        application = QApplication.instance()
        if application is not None:
            apply_theme(cast(QApplication, application), colors)
        # ネイティブの部品はパレットで塗り替えられない。外観そのものを申告する。
        # **「システムに合わせる」ときは固定しない**（ユーザー報告）。固定すると
        # Qt が見る配色が自分で入れた値になり、OS を切り替えても
        # `colorSchemeChanged` が飛ばず、起動中は追従しなくなる
        following = self._theme_watcher.mode is ThemeMode.SYSTEM
        set_macos_appearance(dark=None if following else colors.is_dark)

    def _on_theme_changed(self, colors: ThemeColors) -> None:
        """配色を当てる。**当てている最中に次が来たら、そちらを最後に残す。**

        「ダーク → システムに合わせる」（OS はライト）で踏んだ（ユーザー報告）。
        macOS へ「暗い外観」を申告したまま配色を決めるので、まず古い暗い色が
        流れる。その適用の途中で申告を解くと、Qt が `colorSchemeChanged` を
        **その場で**投げ、明るい配色が入れ子で当たる。入れ子が終わると外側が
        続きを進めるので、古い暗い色が上書きし直していた。

        結果、アプリのパレットは入れ子側（明るい）、本文とツールバーは
        外側（暗い）になり、画面の中で配色が食い違った。
        """
        self._pending_theme = colors
        if self._applying_theme:
            return  # 外側の処理が、いま入れた色で仕上げてくれる

        self._applying_theme = True
        try:
            while self._pending_theme is not None:
                current, self._pending_theme = self._pending_theme, None
                self._apply_theme_now(current)
        finally:
            self._applying_theme = False

    def _apply_theme_now(self, colors: ThemeColors) -> None:
        self._apply_palette(colors)
        self._pane.set_theme(colors)
        self._list_pane.set_theme(colors)
        self._sidebar.set_theme(colors)
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
        self._config.note_list_visible = not self._list_pane.isHidden()
        self._config.toolbar_visible = self._pane.toolbar_visible()
        self._config.window_geometry = self.saveGeometry()
        self._config.sync()

        self._save_timer.stop()
        self._watcher.stop()
        # ワーカーが自分の接続で書いている最中に落とさない
        self.wait_for_index_sync()
        self._db.close()
        super().closeEvent(event)
