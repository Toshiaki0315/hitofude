"""メインウィンドウ（spec §5.1）。

サイドバー / ノートリスト / エディタの 3 ペイン。ここが Phase 1〜4 で作った
部品を初めて 1 本に繋ぐ場所になる。

保存の流れ（§7.4）:
    テキスト変更 → デバウンス 800ms → 競合検査 → アトミック書き込み → 索引更新

ノート切り替え・ウィンドウの非活性化・終了時は待たずに書く。
"""

import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QTextCursor,
)
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)

from hitofude import APP_NAME, __version__
from hitofude.app import ThemeWatcher, apply_theme, set_macos_appearance
from hitofude.config import (
    DEFAULT_POINT_SIZE,
    MAX_POINT_SIZE,
    MIN_POINT_SIZE,
    Config,
)
from hitofude.core import frontmatter, textpos
from hitofude.core.activation import ALLOWED_SCHEMES
from hitofude.core.document import Note, with_title
from hitofude.core.outline import headings
from hitofude.core.search import matching_line
from hitofude.core.stats import count as count_text
from hitofude.core.wikilink import context_line, normalize, resolve
from hitofude.editor import exporter, importer, pptx_export
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.storage import autosave
from hitofude.storage.autosave import Debouncer
from hitofude.storage.index_db import IndexDb, NoteRow, SortOrder
from hitofude.storage.vault import (
    ConflictAction,
    Vault,
    check_conflict,
    keep_both_path,
    sanitize_filename,
    unique_path,
)
from hitofude.storage.watcher import ChangeKind, VaultWatcher
from hitofude.theme import ThemeColors, ThemeMode
from hitofude.ui.backlink_bar import Backlink
from hitofude.ui.conflict_dialog import ConflictDialog, Resolution
from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.icons import apply_menu_font
from hitofude.ui.index_sync import IndexSyncTask, StatsReporter, StatsTask, SyncReporter
from hitofude.ui.menus import build_menus
from hitofude.ui.note_list import NoteListView, NoteRole
from hitofude.ui.note_list_pane import EMPTY_NOTICE, NoteListPane
from hitofude.ui.panes import (
    SIDEBAR_MIN_WIDTH,
    PaneSplitter,
)
from hitofude.ui.preferences import PreferencesDialog
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter
from hitofude.ui.shortcut_sheet import ShortcutSheet
from hitofude.ui.sidebar import ALL, Filter, FilterKind, Sidebar

logger = logging.getLogger(__name__)


DEFAULT_SIZE = (1100, 720)
MINIMUM_SIZE = (720, 480)
SAVE_TICK_MS = 200
STASH_INTERVAL_SECONDS = 2.0
# 文字数を数え直すまでの待ち。38,000 字のノートで 40ms 掛かる（実測）ので
# 1 打ごとには数えられない
STATS_DELAY_MS = 400

# この長さを超えたら、文字数の集計を背景へ回す（ユーザー要望）。
# **1 フレーム（16ms）に収まるうちはその場で数える。** 実測で
# 1,000 文字 1.5ms / 1 万文字 13.7ms / 1.3 万文字 17.0ms。短い本文を
# 投げると、返ってくるまでの往復のほうが長くつく
ASYNC_STATS_CHARS = 10_000
# 「直前のノートへ戻る」で遡れる数（C-8）
MAX_HISTORY = 20
DIRTY_MARK = "•"
# ステータスバー右端の余白。ウィンドウの角が丸いので、右端ぴったりに置くと
# 最後の文字が欠ける（実際に欠けた）
STATUS_RIGHT_MARGIN = 14
STATS_TOOLTIP = "文字数と行数。\n装飾の記号（`**` など）と front matter、改行は数えません。"
MODE_TOOLTIP = "今入っている書き方のモード。\nRaw（⌘/）／ フォーカス（⇧⌘D）／ タイプライタ（⇧⌘Y）"

# 帯に出すバックリンクの上限（E-6）。ここに出る数だけファイルを読むので、
# 際限なく増えると開くたびに遅くなる。読み切れない数を並べても使えない
MAX_BACKLINKS = 50

# 片づけの確認に並べる名前の数（E-5）。全部並べるとダイアログが画面を溢れる
CLEANUP_PREVIEW = 10

NEW_NOTE_TITLE = "無題"
PINNED_NOTICE = "ピン留めしているノートは削除できません。先にピン留めを外してください。"
NOTICE_MS = 5000

# `Cmd +` / `Cmd -` の 1 押しで動く量（G-5）。環境設定の刻みは 0.5pt だが、
# **押して分からない変化はもう一度押される**ので、こちらは 1pt にする
ZOOM_STEP = 1.0


def _short_path(path: Path) -> str:
    """ステータスバーに収まる長さにする。

    絶対パスはたいてい `/Users/名前/` で始まり、その分だけ肝心の場所が
    見えなくなる。**見えない知らせは無いのと同じ**なので `~` にする。
    """
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


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

        self._db = IndexDb(self._vault.managed_dir / "index.sqlite")
        self._note: Note | None = None
        self._loading = False
        self._opening = False
        self._filter: Filter = ALL
        # 全文検索で最後に打った語（G-1）。飛び先を数え直すのに使う
        self._search_query = ""

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
        # 開いたノートの履歴（C-8）。**今いるノートは入れない。**
        # 入れると「戻る」の 1 回目が今の場所になり、押しても何も起きない
        self._history: list[Path] = []
        self._going_back = False

        # 文字数の集計（長い本文だけ背景で回す）。**親を付けない**のは
        # 索引の走査と同じ理由（結果が戻る前に窓ごと消えると落ちる）
        self._stats_reporter = StatsReporter()
        self._stats_reporter.counted.connect(self._on_stats_counted)
        self._stats_token = 0

        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(STATS_DELAY_MS)
        self._stats_timer.timeout.connect(self._update_stats)

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
        self._reveal_button = QToolButton(self)
        self._reveal_button.setText("Finder で表示")
        self._reveal_button.setAutoRaise(True)
        self._reveal_button.hide()
        self._reveal_button.clicked.connect(self._reveal_exported)
        self.statusBar().addPermanentWidget(self._reveal_button)
        self._exported: Path | None = None
        self._export_timer = QTimer(self)
        self._export_timer.setSingleShot(True)
        self._export_timer.setInterval(NOTICE_MS)
        self._export_timer.timeout.connect(self.hide_export_notice)

        # **文字数より左に置く。** 右端は文字数の場所で、あとから増えたものを
        # 右へ足すと、保存のたびに文字数が横へ動いて見える
        self._mode_label = QLabel("", self)
        self._mode_label.setToolTip(MODE_TOOLTIP)
        self.statusBar().addPermanentWidget(self._mode_label)

        self._saved_label = QLabel("", self)
        self._saved_label.setToolTip("最後に保存した時刻。保存は自動で、打ち始めると消えます。")
        self.statusBar().addPermanentWidget(self._saved_label)

        self._stats_label = QLabel("", self)
        self._stats_label.setToolTip(STATS_TOOLTIP)
        self._stats_label.setContentsMargins(0, 0, STATUS_RIGHT_MARGIN, 0)
        self.statusBar().addPermanentWidget(self._stats_label)
        self.statusBar().setSizeGripEnabled(False)

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
        self._sidebar.filter_changed.connect(self._on_filter_changed)
        self._sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sidebar.customContextMenuRequested.connect(self._show_sidebar_menu)
        self._note_list.note_activated.connect(self._on_note_activated)
        self._editor.textChanged.connect(self._on_text_changed)
        self._theme_watcher.changed.connect(self._on_theme_changed)

        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
        self._editor.set_tag_source(self._known_tags)
        self._editor.set_mono_family(self._config.mono_family)
        self._editor.set_tab_width(self._config.tab_width)
        self._sidebar.set_line_spacing(self._config.line_spacing)
        self._note_list.set_line_spacing(self._config.line_spacing)
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
        return self._reveal_button

    @property
    def export_timer(self) -> QTimer:
        return self._export_timer

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
                return self._trash_rows()
            case FilterKind.TAG:
                return self._db.notes_with_tag(target.tag or "", order=order)
        return []

    def set_sort_order(self, order: SortOrder) -> None:
        """一覧の並び順を変えて覚える（C-3）。"""
        self._config.sort_order = order
        self._list_pane.set_sort_order(order)
        self.refresh()

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
        target = self._sidebar.filter_at(point)
        menu = self.sidebar_menu_for(target) if target is not None else None
        if menu is None:
            return
        menu.exec(self._sidebar.viewport().mapToGlobal(point))
        menu.deleteLater()

    def sidebar_menu_for(self, target: Filter) -> QMenu | None:
        """サイドバーの右クリックメニュー。**今はゴミ箱だけ**（G-3）。

        「すべて」や「お気に入り」に出せる操作が無いのに空のメニューを
        出すと、押せる何かがあると誤解させる。
        """
        if target.kind is not FilterKind.TRASH:
            return None
        menu = QMenu(self)
        apply_menu_font(menu)
        action = menu.addAction("ゴミ箱を空にする…")
        action.triggered.connect(self.empty_trash)
        # **押してから断らない。** 件数は開く前に分かるので、押せない状態で
        # 見せる（一覧の「ゴミ箱へ移動」がピン留め時にそうなっているのと同じ）
        action.setEnabled(bool(self._trash_entries()))
        return menu

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
        apply_menu_font(menu)
        if self._filter.kind is FilterKind.TRASH:
            menu.addAction("元に戻す").triggered.connect(lambda: self.restore_note(path))
            menu.addSeparator()
            # 「…」は「押すと確認が出る」の合図（他のメニューと揃える）
            menu.addAction("完全に削除…").triggered.connect(lambda: self.delete_permanently(path))
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

    def delete_permanently(self, path: Path) -> bool:
        """ゴミ箱の 1 件を完全に削除する（G-3）。消したら True。

        **戻せないので必ず名前を見せて確認する。** ゴミ箱へ移すときの
        「30 日は戻せます」とは別の文面にする。
        """
        if not path.is_file():
            return False
        answer = QMessageBox.question(
            self,
            "完全に削除",
            f"「{path.stem}」を完全に削除しますか？\nこの操作は取り消せません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        # **開いたままにしない。** 消えたファイルに向けて自動保存が走ると、
        # 消したはずのノートが書き戻る
        if self._note is not None and self._note.path == path:
            self._close_current()
        self._watcher.suppress(path)
        self._vault.delete_permanently(path)
        self.refresh()
        self.statusBar().showMessage("完全に削除しました", NOTICE_MS)
        logger.info("完全に削除した: %s", path.name)
        return True

    def empty_trash(self) -> int:
        """ゴミ箱を今すぐ空にする（G-3）。消した数を返す。

        **30 日待たずに消したいことがある。** 見られたくないノートを
        捨てたとき、残っているのは捨てたことにならない。

        E-5 の片づけと同じ作法で、**数を見せてから**消す。
        """
        entries = self._trash_entries()
        if not entries:
            # ここへ来るのは、メニューを開いてから Finder などで空にされたとき
            QMessageBox.information(self, "ゴミ箱は空です", "消すものはありません。")
            return 0

        answer = QMessageBox.question(
            self,
            "ゴミ箱を空にする",
            f"ゴミ箱の {len(entries)} 件を完全に削除しますか？\n"
            "この操作は取り消せません（もう戻せません）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 0

        if self._note is not None and self._note.path.parent == self._vault.trash_dir:
            self._close_current()
        for path in entries:
            self._watcher.suppress(path)
        removed = self._vault.empty_trash()
        self.refresh()
        self.statusBar().showMessage(f"{len(removed)} 件を完全に削除しました", NOTICE_MS)
        logger.info("ゴミ箱を空にした: %d 件", len(removed))
        return len(removed)

    def _trash_entries(self) -> list[Path]:
        """ゴミ箱の中身（ノートも添付も）。"""
        return [path for path in self._vault.trash_dir.glob("*") if path.is_file()]

    def _close_current(self) -> None:
        """開いているノートを閉じる。**保存はしない**（消す直前に呼ぶため）。"""
        self._note = None
        self._editor.clear()
        self._remember_note(None)
        self._update_title()
        self._update_stats()

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
        note = self._vault.create(NEW_NOTE_TITLE)
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)
        self._note_list.select_path(note.path.relative_to(self._vault.root))

    # ------------------------------------------------------------- テンプレート

    def new_from_template(self) -> bool:
        """`Cmd+Shift+N`。雛形を選んで新しいノートを作る（E-4）。

        **題名は聞かない。** 雛形の名前をそのまま題名にして、見出しを
        直せばファイル名が追いかける（ADR-0005）。ダイアログを 2 枚
        重ねるより、開いてすぐ書けるほうが速い。
        """
        if not self._vault.templates():
            QMessageBox.information(
                self,
                "テンプレートがありません",
                f"「{self._vault.templates_dir}」に `.md` を置くと、ここから使えます。",
            )
            return False

        palette = Palette(self, placeholder="雛形を選ぶ…", theme=self._theme_watcher.colors)
        palette.set_provider(self._template_items)
        palette.chosen.connect(lambda item: self.create_from_template(item.path))
        palette.finished.connect(palette.deleteLater)
        palette.open_with()
        return True

    def create_from_template(self, path: Path) -> Note | None:
        """雛形からノートを作って開く（E-4）。作れなければ None。"""
        self.flush()
        try:
            created = self._vault.create_from_template(path)
        except (ValueError, OSError):
            logger.warning("雛形から作れなかった: %s", path)
            return None

        self._db.upsert_note(created.note, self._vault.root)
        self.refresh()
        self.open_note(created.note.path)
        self._note_list.select_path(created.note.path.relative_to(self._vault.root))
        self._place_cursor(created.cursor)
        return created.note

    def open_daily_note(self, day: datetime | None = None) -> Note:
        """`Cmd+T`。今日のノートを開く。無ければ作る（E-4）。

        **同じ日に何度押しても同じノートを開く。** 増えると、どちらに
        書いたか分からなくなる。
        """
        self.flush()
        created = self._vault.daily_note(day)
        self._db.upsert_note(created.note, self._vault.root)
        self.refresh()
        self.open_note(created.note.path)
        self._note_list.select_path(created.note.path.relative_to(self._vault.root))
        self._place_cursor(created.cursor)
        return created.note

    def _template_items(self, query: str) -> list[PaletteItem]:
        items = [
            PaletteItem(title=path.stem, subtitle=self._template_hint(path), path=path)
            for path in self._vault.templates()
        ]
        return fuzzy_filter(query, items)

    def _template_hint(self, path: Path) -> str:
        """一覧に出す 1 行。雛形の最初の見出しを使う。

        読めなければ空にする。**候補が出ないより、説明が無いほうがまし**。
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        for line in text.split("\n"):
            if line.startswith("#"):
                return line.lstrip("# ").strip()
        return ""

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
        """保存済みの合図（C-5）。`None` で消す。

        **開いただけでは出さない。** まだ何も書いていないのに「保存しました」
        は嘘になる。打ち始めたら消す。
        """
        self._saved_label.setText(f"{at:%H:%M} に保存" if at is not None else "")

    def saved_text(self) -> str:
        return self._saved_label.text()

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
        """今入っているモードの並び。何も入っていなければ空（ユーザー要望）。

        **有効なものだけ出す。** 「なし」と出しても場所を取るだけで、
        読む理由がない。Raw はツールバーを隠していると（`Cmd+3`）他に
        分かる場所が無いので、ここが唯一の手掛かりになる。
        """
        found = [name for name, active in self._modes() if active]
        return " / ".join(found)

    def _modes(self) -> list[tuple[str, bool]]:
        return [
            ("Raw", self._editor.source_mode),
            ("フォーカス", self._editor.focus_mode),
            ("タイプライタ", self._editor.typewriter_mode),
        ]

    def _update_modes(self) -> None:
        self._mode_label.setText(self.mode_text())

    def _update_stats(self) -> None:
        """ステータスバーの「◯◯文字 / ◯◯行」を更新する。

        **長い本文は背景で数える**（ユーザー要望）。その場で数えると、
        打つ手を止めた 0.4 秒後に画面が 70ms（忙しいときは 285ms）止まる。
        数えるのは表示のためだけなので、待たせる理由がない。
        """
        if self._note is None:
            self._stats_label.setText("")
            return

        text = self._editor.toPlainText()
        # 前に投げたぶんの結果を捨てるための合図
        self._stats_token += 1
        if len(text) <= ASYNC_STATS_CHARS:
            self._show_stats(count_text(text))
            return
        QThreadPool.globalInstance().start(StatsTask(text, self._stats_token, self._stats_reporter))

    def _on_stats_counted(self, token: int, stats) -> None:
        """背景で数え終わった結果を出す。

        **古い結果は捨てる。** 数え終わる前に別のノートへ移れるので、
        遅れて届いた前のノートの数字を出すと、今見ているものと食い違う。
        """
        if self._closing or token != self._stats_token:
            return
        self._show_stats(stats)

    def _show_stats(self, stats) -> None:
        self._stats_label.setText(f"{stats.characters:,} 文字 / {stats.lines:,} 行")

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
        # 書けた時点で「ここが保存済みの状態」。これを怠ると、保存後の
        # カーソル移動（リビールの textChanged）が編集扱いに戻ってしまう
        self._editor.document().setModified(False)

        autosave.discard(self._recovery_root, note.path)
        self._note = self._rename_if_title_changed(note, self._vault.read(note.path))
        self._db.upsert_note(self._note, self._vault.root)
        self.refresh()
        self._update_title()
        self._show_saved(datetime.now())
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
                # キャンセルは「まだ決めない」であって「保存できた」ではない。
                # `flush()` は保存の前に待ちを解除しているので、ここで戻さないと
                # 未保存の編集が「保存済み」扱いになり、終了時の「両方残す」も
                # 走らず、書いた内容が消える。退避（_maybe_stash）も pending を
                # 見ているため、戻すことで保険も生き返る
                self._debouncer.touch()
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
        else:
            self._note = None
            self._editor.clear()

    # ------------------------------------------------------------------ 検索

    def quick_open(self) -> None:
        """`Cmd+O`。タイトルへのあいまい一致で開く（spec §5.4）。"""
        palette = self._make_palette("ノートを開く…")
        palette.set_provider(self._quick_open_items)
        palette.open_with()

    def preview_in_browser(self) -> None:
        """書き出さずに既定のブラウザで確認する（E-2）。

        **画面では図にならない Mermaid・数式・コードの色**が、ここで見える。
        押した時点の本文を書き出すので、直後の内容がそのまま出る。
        """
        if self._note is None:
            return
        target = exporter.write_preview(
            self._editor.toPlainText(),
            theme=self._theme_watcher.colors,
            base_path=self._vault.root,
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def copy_as_html(self) -> None:
        """書式付きでクリップボードへ入れる（E-3）。メールやチャットへ貼る用。"""
        if self._note is None:
            return
        exporter.copy_html(
            self._editor.toPlainText(),
            theme=self._theme_watcher.colors,
            base_path=self._vault.root,
        )

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
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)
        self._note_list.select_path(note.path.relative_to(self._vault.root))
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
        """`Cmd+R`。このノートの見出しへ飛ぶ（C-2）。

        ノート横断のクイックオープンと同じ道具を使う。入口が増えても
        操作を覚え直さずに済む。
        """
        palette = self._make_palette("見出しへ飛ぶ…")
        palette.set_provider(self._outline_items)
        palette.open_with()

    def _known_tags(self) -> list[str]:
        """索引にあるタグ（C-4 / 補完の候補）。件数の多い順ではなく名前順。

        探しているものが五十音で見つかるほうが速い。
        """
        return sorted(entry.tag for entry in self._db.tag_tree())

    def _outline_items(self, query: str) -> list[PaletteItem]:
        items = [
            PaletteItem(
                title=found.text or "（無題の見出し）",
                # 字下げで階層を見せる。深さを数字で出しても読み取りにくい
                subtitle="　" * (found.level - 1) + "#" * found.level,
                path=self._note.path if self._note else Path(),
                line=found.line,
            )
            for found in headings(self._editor.toPlainText())
        ]
        return fuzzy_filter(query, items)

    def jump_to_line(self, line: int) -> None:
        """その行の先頭へカーソルを移す（C-2）。無い行番号なら何もしない。"""
        block = self._editor.document().findBlockByNumber(line)
        if not block.isValid():
            return
        cursor = self._editor.textCursor()
        cursor.setPosition(block.position())
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()
        self._editor.setFocus()

    def full_text_search(self) -> None:
        """`Cmd+Shift+F`。本文を検索する（spec §5.4）。

        **選んだら、その箇所へ飛ぶ**（G-1）。抜粋を見て選んだのに先頭が
        開くと、`Cmd+F` で探し直しになる。
        """
        palette = Palette(self, placeholder="本文を検索…", theme=self._theme_watcher.colors)
        palette.set_provider(self._search_items)
        palette.chosen.connect(self._on_search_chosen)
        palette.finished.connect(palette.deleteLater)
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
        # 飛び先を探すのに要る。**索引には行番号を持たせない**（作りが
        # 変わって作り直しが要る。開いたノートで数え直せば足りる）
        self._search_query = query
        return [
            PaletteItem(title=hit.title, subtitle=hit.snippet, path=hit.path)
            for hit in self._db.search(query)
        ]

    def _on_search_chosen(self, item: PaletteItem) -> None:
        """検索の結果を開いて、一致した行へキャレットを置く（G-1）。

        **見つからなくても開く。** 飛べないだけで、開けないより開くほうがよい。
        """
        self.open_note(self._vault.root / item.path)
        self._note_list.select_path(item.path)

        line = matching_line(self._editor.toPlainText(), self._search_query)
        if line is not None:
            self.jump_to_line(line)

    def _on_palette_chosen(self, item: PaletteItem) -> None:
        if item.line is not None:
            self.jump_to_line(item.line)
            return
        self.open_note(self._vault.root / item.path)
        self._note_list.select_path(item.path)

    # ------------------------------------------------------------ エクスポート

    def export_markdown(self) -> Path | None:
        """Markdown のまま書き出す。変換を挟まない。"""
        return self._export("Markdown で書き出す", "Markdown (*.md)", ".md", self._write_markdown)

    def export_html(self) -> Path | None:
        """spec §9 Phase 6。R2 の例外はエクスポート層に閉じている。"""
        return self._export("HTML で書き出す", "HTML (*.html)", ".html", self._write_html)

    def export_pdf(self) -> Path | None:
        return self._export("PDF で書き出す", "PDF (*.pdf)", ".pdf", self._write_pdf)

    def export_pptx(self) -> Path | None:
        """PowerPoint で書き出す（F-5）。**ざっくり作って手で整える**前提。"""
        return self._export(
            "PowerPoint で書き出す", "PowerPoint (*.pptx)", ".pptx", self._write_pptx
        )

    def print_note(self) -> bool:
        """`Cmd+P`。印刷ダイアログを出す（C-9）。

        **macOS では `Cmd+P` は印刷が慣習。** ここは PDF 書き出しに
        割り当てていたが、印刷パネルから「PDF として保存」も選べるので、
        慣習に合わせても PDF への道は残る。書き出しはメニューにある。

        刷る前に保存する。書き出しと同じで、打った直後の内容が出ないと
        「今見えているもの」と違うものが出てしまう。
        """
        if self._note is None:
            return False
        self.flush()
        printer = exporter.new_printer()
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("印刷")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        exporter.print_document(
            printer,
            self._editor.toPlainText(),
            theme=self._theme_watcher.colors,
            base_point_size=self._config.font_point_size,
            base_path=self._vault.root,
        )
        return True

    def _export(self, caption: str, filter_: str, suffix: str, writer) -> Path | None:
        """保存先を尋ねて書き出す。`writer` は `(Path, str) -> Path`。"""
        if self._note is None:
            return None
        self.flush()
        suggested = str(Path.home() / f"{self._note.title}{suffix}")
        chosen, _ = QFileDialog.getSaveFileName(self, caption, suggested, filter_)
        if not chosen:
            return None
        target = writer(Path(chosen), self._editor.toPlainText())
        self._notify_export(target)
        return target

    def _notify_export(self, target: Path) -> None:
        """どこへ書いたかを見せ、Finder への道を添える（G-4）。

        **書き出しても画面が変わらなかった。** 保存先を選んだ直後、
        何も起きないように見えて、書けたのかどうかも分からない。

        知らせは残さない。前のファイルを指すボタンが居座ると、今のノートと
        関係のないものを開くことになる。
        """
        self._exported = target
        self.statusBar().showMessage(f"{_short_path(target)} に書き出しました", NOTICE_MS)
        self._reveal_button.show()
        self._export_timer.start()

    def hide_export_notice(self) -> None:
        self._reveal_button.hide()
        self._exported = None

    def _reveal_exported(self) -> None:
        if self._exported is not None:
            self.reveal_in_finder(self._exported)

    def reveal_in_finder(self, path: Path) -> None:
        """Finder で場所を開き、そのファイルを選んだ状態にする（G-4）。

        **フォルダを開くだけにしない。** 同じ名前が並ぶ場所だと、どれを
        書いたのか分からない。`open -R` は選択まで面倒を見てくれる。

        書き出したあとに消された場合は何もしない（空振りさせない）。
        """
        if not path.exists():
            logger.info("書き出したファイルが見つからない: %s", path)
            return
        subprocess.run(["open", "-R", str(path)], check=False)

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

    def _write_pptx(self, target: Path, text: str) -> Path:
        return pptx_export.write_pptx(target, text, base_path=self._vault.root)

    def _write_pdf(self, target: Path, text: str) -> Path:
        return exporter.write_pdf(
            target,
            text,
            theme=self._theme_watcher.colors,
            base_point_size=self._config.font_point_size,
            base_path=self._vault.root,
        )

    def import_document(self) -> Path | None:
        """「ファイル」→「読み込む…」。資料をノートにして開く（F-2）。

        **元のファイルは触らない。** 読むだけで、移動も複製もしない。
        題名はファイル名を使う（`講演資料.pdf` → `講演資料`）。

        **読めなければノートを作らない。** 空のノートが増えるほうが困る。
        """
        self.flush()
        chosen, _ = QFileDialog.getOpenFileName(
            self, "読み込む", str(Path.home()), importer.FILE_FILTER
        )
        if not chosen:
            return None

        source = Path(chosen)
        text = importer.to_markdown(source, save_image=self.save_attachment)
        if not text.strip():
            QMessageBox.warning(
                self,
                "読み込めませんでした",
                f"「{source.name}」から文字を取り出せませんでした。\n"
                "画像だけの資料や、保護されたファイルかもしれません。",
            )
            return None

        note = self._vault.create(source.stem, text)
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)
        self._note_list.select_path(note.path.relative_to(self._vault.root))
        logger.info("取り込んだ: %s → %s", source.name, note.path.name)
        return note.path

    def cleanup_attachments(self) -> int:
        """使っていない添付をゴミ箱へ移す（E-5）。移した数を返す。

        **手で走らせる。** 起動のたびに動かすと、参照の取りこぼしが
        「気づかないうちにファイルが動く」に直結する。件数を見せて、
        押したときだけ動かす。

        **書きかけの本文も数える。** 先に保存しないと、貼ったばかりの
        画像が「どこからも指されていない」ことになって消える。
        """
        self.flush()
        orphans = self._vault.unused_attachments()
        if not orphans:
            QMessageBox.information(
                self,
                "片づけるものはありません",
                "どの添付もノートから使われています。",
            )
            return 0

        names = "\n".join(f"・{path.name}" for path in orphans[:CLEANUP_PREVIEW])
        if len(orphans) > CLEANUP_PREVIEW:
            names += f"\n…ほか {len(orphans) - CLEANUP_PREVIEW} 件"
        answer = QMessageBox.question(
            self,
            "使っていない添付を片づける",
            f"どのノートからも使われていない添付が {len(orphans)} 件あります。\n"
            f"ゴミ箱へ移しますか？（{self._config.trash_days} 日は戻せます）\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 0

        moved = self._vault.trash_attachments(orphans)
        self.statusBar().showMessage(f"{len(moved)} 件をゴミ箱へ移しました", NOTICE_MS)
        logger.info("使っていない添付を片づけた: %d 件", len(moved))
        return len(moved)

    def place_manual(self) -> None:
        """ヘルプ →「使い方のノートを置き直す」。

        **既にあるノートは消さない。** 書き足したメモごと消えては困るので、
        別のファイルとして置く（`Vault.place_manual`）。
        """
        note = self._vault.place_manual()
        if note is None:
            return
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        self.open_note(note.path)

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
