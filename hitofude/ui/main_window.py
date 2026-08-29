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
from typing import cast

from PySide6.QtCore import QCoreApplication, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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
from hitofude.core import frontmatter, searchquery, textpos
from hitofude.core import llm as llm_module
from hitofude.core.activation import ALLOWED_SCHEMES
from hitofude.core.document import Note
from hitofude.core.outline import headings
from hitofude.core.stats import is_huge
from hitofude.core.wikilink import context_line, normalize, resolve
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.storage import autosave, history
from hitofude.storage.index_db import (
    ROOT_FOLDER,
    IndexDb,
    NoteRow,
    SortOrder,
    merge_folders,
)
from hitofude.storage.vault import (
    TRASH_DIR,
    Vault,
    unique_path,
)
from hitofude.storage.watcher import ChangeKind, VaultWatcher
from hitofude.theme import ThemeColors, ThemeMode
from hitofude.ui import tooltip
from hitofude.ui.assistant_actions import AssistantActions
from hitofude.ui.assistant_pane import AssistantPane
from hitofude.ui.backlink_bar import Backlink
from hitofude.ui.editor_pane import EditorPane
from hitofude.ui.export_actions import ExportActions
from hitofude.ui.graph_window import GraphWindow
from hitofude.ui.history_actions import HistoryActions
from hitofude.ui.history_dialog import HistoryDialog
from hitofude.ui.icons import Glyph, glyph_icon
from hitofude.ui.index_sync import (
    IndexSyncTask,
    SyncReporter,
)
from hitofude.ui.menu_button import MenuButton
from hitofude.ui.menus import build_gear_menu, build_menus, sync_edit_actions
from hitofude.ui.note_actions import NoteActions
from hitofude.ui.note_list import NoteListView
from hitofude.ui.note_list_pane import EMPTY_NOTICE, NoteListPane
from hitofude.ui.outline_pane import OutlinePane
from hitofude.ui.panes import (
    SIDEBAR_MIN_WIDTH,
    PaneSplitter,
)
from hitofude.ui.preferences import PreferencesDialog
from hitofude.ui.reference_pane import ReferencePane
from hitofude.ui.save_controller import SaveController
from hitofude.ui.search_actions import SearchActions
from hitofude.ui.shortcut_sheet import ShortcutSheet
from hitofude.ui.sidebar import ALL, TRASH, Filter, FilterKind, Sidebar
from hitofude.ui.status_bar import (  # noqa: F401  定数はテストが再輸出先として参照する
    ASYNC_STATS_CHARS,
    NOTICE_MS,
    STATUS_RIGHT_MARGIN,
    StatusBarController,
)
from hitofude.ui.table_dialog import TableSizeDialog

logger = logging.getLogger(__name__)


DEFAULT_SIZE = (1100, 720)
MINIMUM_SIZE = (720, 480)
# 「直前のノートへ戻る」で遡れる数（C-8）
MAX_HISTORY = 20
DIRTY_MARK = "•"

# 帯に出すバックリンクの上限（E-6）。ここに出る数だけファイルを読むので、
# 際限なく増えると開くたびに遅くなる。読み切れない数を並べても使えない
MAX_BACKLINKS = 50

NEW_NOTE_TITLE = "無題"
HUGE_NOTE_NOTICE = "大きなノートのため、装飾を無効にして開きました（編集と保存はできます）"

# 終了時に索引の走査を待つ上限。索引は捨ててよいキャッシュ（R9）なので、
# ここで粘るより窓が閉じるほうが大事
LOCKED_VAULT_NOTICE = "保管フォルダを開けませんでした。設定で場所を選び直してください"

MEMORY_DB = Path(":memory:")
"""保管フォルダを開けないときの索引の置き場（ADR-0030）。**覚えない。**
窓を出して設定へ辿り着かせるためだけのもの。"""

CLOSE_INDEX_WAIT_MS = 3000

BUSY_NOTICE = "いま同期しています。終わるまでお待ちください"


def _sync_notice(result, *, full: bool) -> str:
    """走査の結果を一言で。**「何も起きなかった」と「壊れている」を分ける。**

    変わらなかったことをはっきり言わないと、押した人には失敗と区別が
    付かない（ノートが消えて見えた件と同じ落とし穴）。
    """
    parts = [
        f"{len(found)} 件{label}"
        for label, found in (
            ("増えました", result.added),
            ("変わりました", result.updated),
            ("消えました", result.removed),
        )
        if found
    ]
    head = "索引を作り直しました" if full else "最新の情報に同期しました"
    if not parts:
        return f"{head}（変わりはありません）"
    return f"{head}（{'、'.join(parts)}）"


# アウトラインを打鍵に追従させる間隔。即時だと 1 打ごとに全文スキャンになる
OUTLINE_DELAY_MS = 300

# `Cmd +` / `Cmd -` の 1 押しで動く量（G-5）。設定の刻みは 0.5pt だが、
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
            return "お気に入りはありません。\n一覧を右クリックして入れられます。"
        case FilterKind.TAG:
            return f"「#{target.tag}」のノートはありません。\n本文に書くとここに集まります。"
        case FilterKind.FOLDER:
            # 記号（ルートの "."）を見せない。案内は文章なので `label` で読ませる
            return (
                f"「{target.label}」にノートはありません。\n"
                "Finder でこのフォルダに `.md` を入れると出ます。"
            )
        case _:
            return EMPTY_NOTICE


class MainWindow(QMainWindow):
    def __init__(self, config: Config | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config if config is not None else Config()
        self._vault = Vault(self._config.vault_path)
        # 版の履歴（ADR-0023）は束ごと切り出してある（ui/history_actions.py）。
        # **`_history` と名乗らない**——それは「直前のノートへ戻る」のスタック
        self._versions = HistoryActions(self)
        self._vault_ready = self._prepare_vault()

        # **開けない保管フォルダでも窓は出す**（ADR-0030 / ユーザー報告）。
        # 索引は管理フォルダの中なので、開けないときは覚えないだけにする。
        # 一覧は空になるが、設定から別の場所を選び直せる
        self._db = IndexDb(
            self._vault.managed_dir / "index.sqlite" if self._vault_ready else MEMORY_DB
        )
        self._note: Note | None = None
        self._deferred_reload: Note | None = None
        self._loading = False
        self._opening = False
        self._filter: Filter = ALL

        # ノートの CRUD（ゴミ箱・ピン・改名・雛形・片づけ）は束ごと
        # 切り出してある（ui/note_actions.py）。メニューの結線より先に作る
        self._notes = NoteActions(self)
        # ローカルLLM（読ませる・降ろす・関連・質問）も束ごと切り出して
        # ある（ui/assistant_actions.py）。_build_ui が相手を作るのに使う
        self._assistant_actions = AssistantActions(self)

        self._build_ui()
        self._build_menus()
        # ツールチップを自前の窓（黒地に白・角丸）で出す（ユーザー要望
        # 2026-08-24）。**組み終えてから 1 回**。個別に張ると張り漏れる
        tooltip.adopt(self)
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
        # **開けない場所は見張らない**（ADR-0030）。始めようとすると
        # そこでも `.trash` を作りにいって落ちる
        if self._vault_ready:
            self._watcher.start()

        # **親を付けない。** ウィンドウの子にすると、ワーカーが結果を返す前に
        # ウィンドウごと破棄されて "Signal source has been deleted" で落ちる。
        # Python 側の参照（ここと QRunnable）が生存を保つ
        self._sync_reporter = SyncReporter()
        self._sync_reporter.finished.connect(self._on_index_synced)
        self._sync_reporter.failed.connect(self._on_index_sync_failed)
        self._syncing_index = False
        self._full_sync: bool | None = None
        """押されて始めた走査かどうか（`None` なら起動時の走査）。"""
        self._closing = False
        # 開いたノートの履歴（C-8）。**今いるノートは入れない。**
        # 入れると「戻る」の 1 回目が今の場所になり、押しても何も起きない
        self._history: list[Path] = []
        self._going_back = False

        # **書ける場所のときだけ整える**（ADR-0030）。許可を断ったときに
        # ここで落ちて、窓が 1 つも出なかった
        if self._vault_ready:
            self._seed_manual()
            self._vault.seed_templates()
        else:
            self.notify(LOCKED_VAULT_NOTICE, NOTICE_MS * 3)
        self.refresh()  # 前回の索引で先に描く。走査を待たずに操作できる
        self._reopen_last_note()
        if self._vault_ready:
            self.start_index_sync()
        self.offer_recovery()

    # ------------------------------------------------------------------ 構築

    def _build_ui(self) -> None:
        """画面を組む。**呼ぶ順に意味がある**（部品 → 束ね → 結線 → 設定の
        反映）ので、段階ごとの 4 メソッドをこの順で呼ぶだけにしてある
        （レビュー 2026-08-25。1 本で 121 行に育っていた）。"""
        self._build_panes()
        self._assemble_layout()
        self._wire_signals()
        self._apply_config_to_ui()

    def _build_panes(self) -> None:
        """部品を作る。テーマは**保存された設定**で当てる。"""
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

        # 見出しの一覧（提案 5）。**本文の右**に置く。左に置くと、
        # 一覧・サイドバーと合わせて左だけが混み、本文が右へ押し出される
        self._outline = OutlinePane(theme=theme)
        self._outline.heading_activated.connect(self.jump_to_line)
        self._outline.hide()

        # ローカルLLM の答え（L-1 / ADR-0025）。**本文の右**。アウトラインと
        # 同じ理由で、左に寄せると本文が押し出される
        self._assistant = AssistantPane(theme=theme)
        # 横に置くもう 1 枚（U-1）。**読むだけ**——保存の道には触れない
        self._reference = ReferencePane(theme=theme)
        self._assistant.hide()
        self._assistant.requested.connect(self.ask_assistant)
        self._assistant.stopped.connect(self.stop_assistant)
        self._assistant.related_requested.connect(self.show_related)
        self._assistant.question_asked.connect(self.ask_question)
        self._assistant.note_activated.connect(
            lambda relative: self.open_and_select(self._vault.root / relative)
        )
        self._llm = self._assistant_actions.llm_from_config()
        # **回ごとに番号を振る。** 1 つの旗を使い回すと、頼み直したときに
        # 前の回が「まだ走ってよい」と誤解して喋り出す（レビュー指摘）
        self._assistant_run = 0

    def _assemble_layout(self) -> None:
        """部品をスプリッタへ束ね、協調オブジェクトとタイマを作る。"""
        theme = self._theme_watcher.colors
        self._splitter = PaneSplitter(theme.rule)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._list_pane)
        self._splitter.addWidget(self._pane)
        self._splitter.addWidget(self._outline)
        self._splitter.addWidget(self._assistant)
        # **最後に足す。** ペインの表示は添字で切り替えるので、
        # 途中に入れるとアウトラインとローカルLLM の添字がずれる
        self._splitter.addWidget(self._reference)
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
        # アウトラインの掛け直し。打鍵ごとに全文スキャンすると §6.6 の
        # 16ms 予算を食うので、統計と同じくデバウンスする（コードレビュー指摘）
        self._outline_timer = QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.setInterval(OUTLINE_DELAY_MS)
        self._outline_timer.timeout.connect(self._update_outline)

    def _wire_signals(self) -> None:
        """部品どうしを結線する。"""
        self._list_pane.new_note_requested.connect(self.new_note)
        self._list_pane.sort_order_changed.connect(self.set_sort_order)
        self._editor.link_activated.connect(self.activate_link)
        self._editor.tag_activated.connect(self.activate_tag)
        self._editor.wikilink_activated.connect(self.activate_note)
        self._editor.modes_changed.connect(self._update_modes)
        self._pane.toolbar.outline_toggled.connect(self.toggle_outline)
        self._pane.toolbar.table_requested.connect(self.insert_table)
        self._pane.favorite_toggled.connect(self._on_favorite_clicked)
        self._editor.composition_ended.connect(self._on_composition_ended)
        self._pane.backlinks.note_activated.connect(self._on_backlink_opened)
        self._pane.backlinks.toggled.connect(self._remember_backlinks)
        self._pane.backlinks.set_expanded(self._config.backlinks_expanded)
        self._list_pane.set_sort_order(self._config.sort_order)
        self._note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._note_list.customContextMenuRequested.connect(self._show_context_menu)

        self._sidebar.set_line_spacing(self._config.line_spacing)
        self._note_list.set_line_spacing(self._config.line_spacing)
        self._editor.set_content_width(CONTENT_WIDTH_PIXELS[self._config.content_width])
        self.reload_saved_searches()
        self._sidebar.filter_changed.connect(self._on_filter_changed)
        # 一覧の行をフォルダへ落として移す（ユーザー要望）
        self._sidebar.note_dropped.connect(self._on_note_dropped)
        self._sidebar.note_trashed.connect(self._on_note_trashed)
        self._sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sidebar.customContextMenuRequested.connect(self._show_sidebar_menu)
        self._note_list.note_activated.connect(self._on_note_activated)
        self._note_list.files_dropped.connect(self._notes.import_note_files)
        self._editor.textChanged.connect(self._on_text_changed)
        self._theme_watcher.changed.connect(self._on_theme_changed)

    def _apply_config_to_ui(self) -> None:
        """保存された設定を部品へ流し込む。"""
        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
        self._editor.set_tag_source(self._known_tags)
        self._editor.set_note_source(self._known_titles)
        # リンク先の覗き見（U-2）。中身を引く係を挿す
        self._editor.set_note_preview(self._note_preview)
        self._editor.set_mono_family(self._config.mono_family)
        self._editor.set_tab_width(self._config.tab_width)
        # 4 字下げをコードにするか（ADR-0033）。**書き出しも同じ旗を見る**
        self._editor.set_indented_code(self._config.indented_code)
        self._apply_list_font()
        self._editor.setFocus()

    def _apply_list_font(self) -> None:
        """一覧の文字も本文フォントに合わせる。"""
        font = self._note_list.font()
        font.setFamily(self._config.font_family)
        self._note_list.setFont(font)
        self._note_list.viewport().update()

    def _prepare_vault(self) -> bool:
        """保管フォルダを使える形にする。使えたら True（ADR-0030）。

        **開けなくても窓は出す。** macOS は書類フォルダへの立ち入りを尋ね、
        **断ると読めない**。そこで落ちていた——`ensure_layout()` が
        `.trash` を作れずに例外を上げ、窓が 1 つも出なかった（実測）。
        ADR-0030 は履歴の掃除だけを直していて、その手前が残っていた。

        **図が出ないのは我慢できるが、起動しないのは我慢できない。**
        開けないときは掃除も索引も諦めて、設定から選び直せる状態で出す。
        """
        try:
            self._vault.ensure_layout()
        except OSError as error:
            logger.warning("保管フォルダを開けない: %s", error)
            return False
        self._tidy_vault()
        return True

    def _tidy_vault(self) -> None:
        """起動時の片付け。**失敗しても「開けない」ではない**（S-2）。

        かつては `ensure_layout()` と同じ `try` に入れていたので、掃除が
        1 つ転ぶだけで `vault_ready = False` に化けた——一覧が空、監視も
        止まり、**ノートが消えたようにしか見えない**（2026-08-23 の
        ユーザー報告と同じ絵）。同期の下ではファイルが走査の途中で消える
        ので、これは珍しい話ではない。

        **開けるかどうかを決めるのは `ensure_layout()` だけ。** 片付けは
        次の起動でやり直せる。
        """
        chores = (
            ("ゴミ箱", lambda: self._vault.purge_trash(self._config.trash_days)),
            ("版の履歴", self._versions.prune),
            ("一時ファイル", self._vault.sweep_temp_files),  # クラッシュの残骸（H-1）
        )
        for name, chore in chores:
            try:
                chore()
            except OSError as error:
                logger.warning("%sを片付けられない: %s", name, error)

    def _build_menus(self) -> None:
        build_menus(self)
        # メニューを開く歯車（ユーザー要望）。置き場は**ステータスバー**。
        # 書式ツールバーは Cmd+3 で隠せるので、そこに置くと設定への入口ごと
        # 消える（ユーザー指摘）。ステータスバーは常に見えている
        self._menu_button = MenuButton(self.statusBar())
        self._menu_button.setAutoRaise(True)
        # 24px（ユーザー要望）。ブラウザの設定歯車と同じくらいの存在感にする
        self._menu_button.setIconSize(QSize(24, 24))
        self._menu_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_button.setToolTip("メニュー")
        self._menu_button.setAccessibleName("メニュー")
        # 枠は描かない（ユーザー要望）。部分的な QSS を当てると autoRaise でも
        # スタイル既定の枠が出る環境があるため、境界なしを明示する。
        # menu-indicator は右に付く小さな矢印で、絵が 2 つ並ぶと窮屈になる
        self._menu_button.setStyleSheet(
            "QToolButton { border: none; background: transparent; }"
            "QToolButton::menu-indicator { image: none; }"
        )
        self._menu_button.setMenu(build_gear_menu(self))
        # 起動直後のぶん。以後のテーマ変更は `_apply_theme_now` が塗り直す。
        # 色は控えめに（ユーザー要望）。本文と同じ濃さだと主張が強い
        self._menu_button.setIcon(
            glyph_icon(Glyph.GEAR, self._theme_watcher.colors.muted_foreground)
        )
        # **左端に置く**（ユーザー指摘）。右端は窓の角が丸く、埋もれて
        # 見えにくい。左側は showMessage が使う領域だが、一時通知は
        # 専用ラベル（notify）に移したので隠れない
        self.statusBar().insertWidget(0, self._menu_button)

    @property
    def menu_button(self) -> QToolButton:
        """ステータスバーの歯車。テストとテーマ適用が触る。"""
        return self._menu_button

    def notify(self, text: str, ms: int = NOTICE_MS) -> None:
        """ステータスバーの一時通知。showMessage の置き換え。

        showMessage はバー左側のウィジェットを隠すため、左に置いた歯車が
        通知のたびに消える。専用ラベルなら何も隠れない。
        """
        self._status.show_notice(text, ms)

    def notice(self) -> str:
        """いま出ている一時通知。テストが読む。"""
        return self._status.notice_label.text()

    def _restore_layout(self) -> None:
        geometry = self._config.window_geometry
        if geometry is not None:
            self.restoreGeometry(geometry)
        # **表示状態を先に決める。** 隠れているウィジェットは幅 0 になるので、
        # 順序が逆だと割り当てた幅がその場で捨てられる
        self._sidebar.setVisible(self._config.sidebar_visible)
        # 開いたままにしていた人には、次も開いた状態で出す（提案 5）
        self._splitter.set_pane_visible(
            self._splitter.indexOf(self._outline), self._config.outline_visible
        )
        self._splitter.set_pane_visible(
            self._splitter.indexOf(self._assistant), self._config.assistant_visible
        )
        if self._config.assistant_visible:
            self._assistant.set_available(self._llm.available())
        self._pane.toolbar.set_outline_checked(self._config.outline_visible)
        self._list_pane.setVisible(self._config.note_list_visible)
        self._reference.setVisible(self._config.reference_visible)
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
    def reference(self) -> ReferencePane:
        return self._reference

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
        """初回起動なら使い方ノートを置いて開く（サンプル兼マニュアル）。

        **書けない場所には置かない**（ADR-0030）。許可を断ったときに
        ここで落ちていた。
        """
        if not self._vault_ready:
            return
        note = self._vault.seed_manual()
        if note is None:
            return
        self._open_created(note)  # 帯も付いてくる（open_note の直呼びを避ける）
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

        self.open_and_select(path)

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
            # **元のフォルダに戻す**（K-1 と同じ理屈。コードレビュー指摘）。
            # 箱が消えていたら直下へ（無い箱は作らない。spec §7.1）
            folder = stashed.source.parent
            if not folder.is_dir():
                folder = self._vault.root
            target = unique_path(folder, f"{stashed.source.stem} (復元 {stamp})")
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

    def start_index_sync(self, *, full: bool = False) -> bool:
        """vault の走査を背景で始める。二重に走らせない。始めたら True。"""
        if self._syncing_index:
            return False
        self._syncing_index = True
        QThreadPool.globalInstance().start(
            IndexSyncTask(self._db.path, self._vault, self._sync_reporter, full=full)
        )
        return True

    def resync(self) -> bool:
        """「最新の情報に同期」。**Finder で触ったぶんを取り込む**（ユーザー要望）。

        監視（`storage/watcher.py`）は動いている間しか効かず、閉じている間の
        操作やネットワーク越しの変更は取りこぼす。**取りこぼしたことは画面
        から分からない**ので、押せば必ず合う道を用意する。

        差分だけなので速い（実測: 5,000 本で 144ms）。
        """
        self.flush()  # **打ちかけを先に書く。** 走査は保存済みのものを読む
        if not self.start_index_sync():
            self.notify(BUSY_NOTICE)  # **押しても無反応に見せない**
            return False
        self._full_sync = False
        self.notify("最新の情報に同期しています…")
        return True

    def rebuild_index(self) -> bool:
        """「索引を作り直す」。**索引そのものが疑わしいとき**（ユーザー要望）。

        全部読み直すので時間がかかる（実測: 5,000 本で 19 秒。差分の 100 倍）。
        **捨ててよいのは索引だけ**（R9 / ADR-0023）——`.md` も
        `.OboeGaki/history/` も触らない。
        """
        self.flush()
        if not self.start_index_sync(full=True):
            self.notify(BUSY_NOTICE)
            return False
        self._full_sync = True
        self.notify("索引を作り直しています…（ノートの数だけ時間がかかります）")
        return True

    def wait_for_import(self, timeout_ms: int = 30000) -> bool:
        """取り込みの完了を待つ。テストから使う（背景スレッドで読むため）。

        完了の合図はキュー経由で主スレッドへ戻るので、ここで受け取り切る
        （`wait_for_index_sync` と同じ理由）。
        """
        deadline = time.monotonic() + timeout_ms / 1000
        while not self._closing and self._exports.import_running and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        return not self._exports.import_running

    def wait_for_index_sync(self, timeout_ms: int = 30000) -> bool:
        """走査の完了を待つ。テストと終了処理から使う。

        **スレッドの終了だけでは足りない。** 完了の合図（`_on_index_synced`）
        はキュー経由で主スレッドへ戻るので、ここで受け取り切らないと
        「待ったのにまだ同期中」に見え、直後の `resync()` が話し中で
        弾かれる（テストの実行順で再現）。終了中は受け取らない
        （`_on_index_synced` 側の `_closing` ガードと対）。
        """
        done = QThreadPool.globalInstance().waitForDone(timeout_ms)
        deadline = time.monotonic() + timeout_ms / 1000
        while not self._closing and self._syncing_index and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        return done

    def _on_index_synced(self, result) -> None:
        self._syncing_index = False
        if self._closing:
            # ワーカーの完了は待てても、そこから飛んだシグナルは主スレッドの
            # 待ち行列に残る。`closeEvent` が DB を閉じた後にこれが処理されると
            # 閉じた接続へ問い合わせて落ちる
            return
        if result.changed:
            self.refresh()
        if self._full_sync is not None:
            # **押した人にだけ結果を返す。** 起動時の走査では黙っている
            # （毎回「変わりありません」と出ると、ただの雑音になる）
            self.notify(_sync_notice(result, full=self._full_sync))
            self._full_sync = None
        self.index_synced.emit(result)

    SYNC_FAILED_NOTICE = "ノートの一覧を読み込めませんでした（ファイルは無事です）"

    def _on_index_sync_failed(self, error: Exception) -> None:
        """走査に失敗した。**黙って空の一覧を出さない。**

        記録に残すだけだったので、索引の作りが古くて書き込みが失敗したとき、
        画面には「ノートはありません」としか出なかった——**ノートが消えた
        ようにしか見えない**（ユーザー報告 2026-08-23。ファイルは無事だった）。
        """
        self._syncing_index = False
        self._full_sync = None
        logger.warning("索引の同期に失敗: %s", error)
        if not self._closing:
            # **長めに出す。** 一覧が空の理由を伝えるものなので、
            # 目を離した隙に消えると「やっぱり消えた」になる
            self.notify(self.SYNC_FAILED_NOTICE, NOTICE_MS * 3)

    # ------------------------------------------------------------------ 一覧

    def refresh(self) -> None:
        """索引から一覧・フォルダ・タグツリーを引き直す。"""
        self._note_list.set_rows(self._rows_for(self._filter), showing=self._shown_path())
        # 件数は索引、存在はディスク（空フォルダも見せる。ユーザー要望）
        self._sidebar.set_folders(merge_folders(self._db.folder_tree(), self._vault.folders()))
        self._sidebar.set_tags(self._db.tag_tree())

    def _shown_path(self) -> Path | None:
        """いま本文に出しているノート（保管フォルダからの相対）。

        一覧が持つのは相対パスなので、そちらに合わせる。開いていなければ
        `None`——**開いていないのに何かを選ばせない**。
        """
        if self._note is None:
            return None
        try:
            return self._note.path.relative_to(self._vault.root)
        except ValueError:
            return None  # 保管フォルダの外（ありえないが、選ばない側へ倒す）

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
            case FilterKind.FOLDER:
                return self._db.notes_in_folder(target.folder or "", order=order)
            case FilterKind.SEARCH:
                # 保存した検索（K-4）。当たりの判定は全文検索と同じ
                parsed = searchquery.parse(target.query or "")
                return self._db.notes_matching(
                    text=parsed.text,
                    tags=parsed.tags,
                    after=parsed.after,
                    before=parsed.before,
                    order=order,
                )
        return []

    def set_sort_order(self, order: SortOrder) -> None:
        """一覧の並び順を変えて覚える（C-3）。"""
        self._config.sort_order = order
        self._list_pane.set_sort_order(order)
        self.refresh()

    @property
    def filter(self) -> Filter:
        """今の絞り込み。"""
        return self._filter

    def set_filter(self, target: Filter) -> None:
        self._filter = target
        self._list_pane.set_empty_notice(_empty_notice(target))
        self._note_list.set_rows(self._rows_for(target), showing=self._shown_path())

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

    def open_adjacent_daily(self, *, forward: bool) -> bool:
        """前後の日次ノートを開く。開けたら True。"""
        return self._notes.open_adjacent_daily(forward=forward)

    def reveal_note(self, path: Path) -> None:
        """Finder でそのノートを選んだ状態にする（一覧の右クリック）。"""
        self._notes.reveal_note(path)

    def duplicate_note(self, path: Path) -> Path | None:
        """ノートを複製して開く（一覧の右クリック）。"""
        return self._notes.duplicate_note(path)

    def register_template(self, path: Path) -> Path | None:
        """ノートを雛形として登録する（一覧の右クリック）。"""
        return self._notes.register_template(path)

    def move_note_to_folder(self, path: Path) -> Path | None:
        """ノートをフォルダへ移す（一覧の右クリック / K-3）。"""
        return self._notes.move_note_to_folder(path)

    def _on_note_dropped(self, relative: Path, folder: str) -> None:
        """サイドバーのフォルダへ落とされたノートを移す。

        **行き先を開くところまでが移動の後始末**（`move_note_to`）。
        メニューの「フォルダへ移動…」と揃える。
        """
        self._notes.move_note_to(self._vault.root / relative, folder)

    def _on_note_trashed(self, relative: Path) -> None:
        """ゴミ箱の行へ落とされたノートを捨てる（ユーザー要望 2026-08-28）。

        **メニューの「ゴミ箱へ入れる」と同じ道を通す**（`trash_note`）。
        お気に入りは捨てない、開いていれば閉じる、といった後始末が
        そちらに揃っているので、ここで真似ない。

        そのうえで**フォルダへ移したときと同じ動き**にする（ユーザー要望
        2026-08-28）——行き先で絞り、左の選択も動かし、知らせる。移した
        ものが今の一覧から消えるので、動かないと入ったのか分からない。

        **捨てられなかったときは動かさない**（お気に入りなど）。捨てて
        いないのに画面だけ動くと、入ったように見える。
        """
        path = self._vault.root / relative
        title = path.stem
        if not self._notes.trash_note(path):
            return
        self._show_filter(Filter(FilterKind.TRASH))
        self.notify(f"「{title}」をゴミ箱へ入れました")

    def move_note_to(self, path: Path, folder: str) -> Path | None:
        """ノートをフォルダへ移す（対話なし）。実体は NoteActions。"""
        return self._notes.move_note_to(path, folder)

    def create_folder(self, target: Filter) -> Path | None:
        """選んだフォルダの中に新しいフォルダを作る（サイドバーの右クリック）。"""
        return self._notes.create_folder(target)

    def rename_folder(self, target: Filter) -> Path | None:
        """フォルダの名前を変える（サイドバーの右クリック）。実体は NoteActions。"""
        return self._notes.rename_folder(target)

    def delete_folder(self, target: Filter) -> bool:
        """空のフォルダを消す（サイドバーの右クリック）。"""
        return self._notes.delete_folder(target)

    def reload_saved_searches(self) -> None:
        """保存した検索（K-4）を設定から読み直してサイドバーへ。"""
        self._sidebar.set_saved_searches(
            [(entry.name, entry.query) for entry in self._config.saved_searches]
        )

    def save_search(self) -> bool:
        """検索を保存する（K-4 / 検索メニュー）。"""
        return self._search.save_search()

    def copy_note_link(self, path: Path) -> str:
        """`[[名前]]` をクリップボードへ入れる（一覧の右クリック）。"""
        return self._notes.copy_note_link(path)

    def toggle_pin(self, path: Path) -> bool:
        return self._notes.toggle_pin(path)

    def toggle_pin_current(self) -> bool:
        return self._notes.toggle_pin_current()

    def _on_favorite_clicked(self) -> None:
        """本文の左の星（ユーザー要望 2026-08-27）。入口が増えるだけで、
        中身はメニューの「お気に入り」（⇧⌘P）と同じ。"""
        self.toggle_pin_current()

    def _sync_favorite(self) -> None:
        """星の塗りと出し入れを、今のノートの状態に合わせる。

        入口（星・メニュー・一覧の右クリック）がいくつあっても状態は
        1 つ。切り替えの実体（NoteActions.toggle_pin）がここを呼ぶ。
        """
        note = self._note
        self._pane.set_favorite_visible(note is not None)
        if note is not None:
            self._pane.set_favorite(self._notes.is_pinned(note.path))

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
            self.notify(HUGE_NOTE_NOTICE)

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

        **変換中は待たせる**（R6 / ユーザー報告 2026-08-27）。変換中に
        setPlainText するとプリエディットが古い文書に取り残されて
        描かれなくなる（未確定の文字が消えて見え、確定で現れる）。
        自分の保存のエコーが抑制窓（1.5 秒）を超えて届いたときに
        この経路へ入り得る。
        """
        if self._editor.is_composing():
            self._deferred_reload = note
            return
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

    def _on_composition_ended(self) -> None:
        """変換が終わった。待たせていた読み直しがあれば裁く（R6）。

        **確定で本文が変わっていたら捨てる。** 読み直すと打った文字を
        失う。ずれはいつも通り、次の保存の競合裁きが引き受ける。
        """
        note = self._deferred_reload
        self._deferred_reload = None
        if note is None or self._note is None or self._note.path != note.path:
            return
        if self._editor.document().isModified():
            return
        self._reload_open_note(note)

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

    def open_and_select(self, path: Path) -> None:
        """既にあるノートを開き、一覧の選択も合わせる。

        **開くだけでは足りない。** 一覧の帯が前のノートに残ると、今どれを
        見ているのかが画面から読めない（ユーザー報告）。作成系は
        `_open_created` が同じ面倒を見ている。**この 2 つ以外で
        `open_note()` を直に呼ばない**こと。呼ぶと select 漏れになる。
        """
        self.open_note(path)
        relative = path.relative_to(self._vault.root)
        # **見えないなら絞り込みのほうを動かす**（ユーザー報告 2026-08-22）。
        # フォルダで絞っている間に `[[…]]` で外のノートへ飛ぶと、一覧に行が
        # 無いので選択も付かず、左の選択も前のままだった
        if not self._note_list.has_path(relative):
            self._show_where(relative)
        self._note_list.select_path(relative)

    def show_folder(self, folder: str) -> None:
        """そのフォルダで絞る。**左の選択も動かす。**

        一覧だけ変わると、今どれで絞っているか分からなくなる
        （`activate_tag` と同じ考え方）。空文字は直下。
        """
        self._show_filter(Filter(FilterKind.FOLDER, folder=folder or ROOT_FOLDER))

    def _show_where(self, relative: Path) -> None:
        """そのノートが見える絞り込みへ移る。"""
        if relative.is_relative_to(TRASH_DIR):
            self._show_filter(TRASH)
            return
        folder = relative.parent
        self.show_folder("" if folder == Path() else folder.as_posix())

    def _show_filter(self, target: Filter) -> None:
        self._sidebar.select(target)
        self.set_filter(target)

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
        self._sync_favorite()
        self._update_outline()

    def new_note(self) -> None:
        self.flush()
        self._open_created(self._vault.create(NEW_NOTE_TITLE, folder=self.creation_folder()))

    def creation_folder(self) -> str | None:
        """新規作成の置き場（vault からの相対）。フォルダで絞っている間は
        そのフォルダの中。`None` は直下。

        直下に作ると、絞り込み中の一覧に現れもせず「押したのに何も
        起きない」ように見える（ユーザー要望）。日報フォルダに毎日
        書いていく、が素直にできる。
        """
        if self._filter.kind is FilterKind.FOLDER and self._filter.folder:
            if self._filter.folder == ROOT_FOLDER:
                return None  # ルートを選んでいるときは直下へ
            return self._filter.folder
        return None

    def _open_created(self, note: Note, cursor: int | None = None) -> None:
        """作った / 取り込んだノートを索引へ入れ、一覧を更新して開く。

        「upsert → refresh → open → select」の 4 連は作成系の全入口
        （新規・テンプレート・今日のノート・wikilink・取り込み・マニュアル設置）で
        同じ並びになる。ばらばらに書くと select 漏れが起きる
        （place_manual で実際に漏れていた）。
        """
        self._db.upsert_note(note, self._vault.root)
        self.refresh()
        # 絞り込みの外にできることがある（`[[…]]` から作った先は直下）。
        # `open_and_select` が「見えないなら絞り込みを動かす」まで面倒を見る
        self.open_and_select(note.path)
        if cursor is not None:
            self._place_cursor(cursor)

    # ------------------------------------------------------------- テンプレート

    def delete_template(self) -> bool:
        """テンプレートを選んで削除する。"""
        return self._notes.delete_template()

    def new_from_template(self) -> bool:
        """`Cmd+Shift+N`（E-4）。"""
        return self._notes.new_from_template()

    def create_from_template(self, path: Path) -> Note | None:
        return self._notes.create_from_template(path)

    def open_daily_note(self, day: datetime | None = None) -> Note | None:
        """`Cmd+T`（E-4）。"""
        return self._notes.open_daily_note(day)

    def _place_cursor(self, position: int | None) -> None:
        """`{{cursor}}` の位置へキャレットを置く（E-4）。

        文字は隠していても実在するので、ソースの位置がそのまま使える（R4）。
        ただし**単位は揃える**。`Vault` が数えた位置は Python 単位で、
        `setPosition` は UTF-16 単位（絵文字を挟むとずれる）。
        """
        if position is None:
            return
        text = self._editor.toPlainText()
        cursor = self._editor.textCursor()
        cursor.setPosition(textpos.py_to_utf16(text, min(position, len(text))))
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
        # 見出しの掛け直しはデバウンス。即時だと 1 打ごとに全文コピー +
        # 全行分類が走り、§6.6 の 16ms 予算を食う（コードレビュー指摘）
        if not self._outline.isHidden():
            self._outline_timer.start()
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
                self.open_and_select(target)
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

    def flush(self, *, interactive: bool = True, explicit: bool = False) -> None:
        """未保存の内容を今すぐ書く（§7.4）。実体は SaveController。

        `explicit` は「人が `Cmd+S` を押した」の印。版を残す間隔を
        「なし」にしていても、押したときは 1 版残す（ユーザーの選択）。
        """
        self._saver.flush(interactive=interactive, explicit=explicit)

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
        """開いているノートが外で消された（spec §7.5）。

        **閉じている最中は聞かない。** 終了の途中でモーダルを開くと
        アプリが終了できなくなる（`closeEvent` が既に守っている作法）。
        監視は遅れて届くので、閉じ始めたあとに来ることがある。

        **聞けないときは壊れないほうを選ぶ。** 打ちかけを抱えたまま
        開いておく——閉じると本文ごと捨てることになる。
        """
        if self._closing:
            logger.info("終了中なので聞かずに残す: %s", path.name)
            return

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

    def check_style(self):
        """`文体を見る`。日本語の言い回しを指摘する（U-4）。指摘が無ければ None。"""
        return self._search.check_style()

    def command_palette(self):
        """`Cmd+Shift+P`。命令を名前で探して動かす（U-3）。"""
        return self._search.command_palette()

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

    def _note_preview(self, name: str) -> str | None:
        """`[[ノート名]]` の中身を返す（U-2）。無ければ `None`。

        **照合は `activate_note` と同じ道**（`resolve`）。別に書くと、
        開けるのに覗けない／覗けるのに開けないがずれて出る。

        **無いノートは作らない。** 覗くのは読む操作で、`Cmd+クリック` の
        「無ければ作る」（ADR-0011）とは別の意味。
        """
        target = normalize(name)
        if not target:
            return None
        rows = self._db.notes()
        found = resolve(target, [row.title for row in rows])
        if found is None:
            return None
        row = next(row for row in rows if row.title == found)
        try:
            return self._vault.read(self._vault.root / row.path).text
        except OSError:
            return None  # 消えた・読めない。覗けないだけ

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
            self.open_and_select(path)
            return path

        self.flush()
        note = self._vault.create(target, f"# {target}\n\n", folder=self._link_folder())
        self._open_created(note)
        logger.info("リンク先が無かったので作った: %s", note.path.name)
        return note.path

    def extract_selection(self) -> Path | None:
        """`Cmd+Shift+X`。選択範囲を別のノートにする（M-1 / 仮身化）。"""
        return self._notes.extract_selection()

    def sync_edit_actions(self) -> None:
        """「編集」メニューの灰色を今の選択に合わせる（M-1）。"""
        sync_edit_actions(self)

    def _link_folder(self) -> str | None:
        """`[[…]]` から作るノートの置き場（ユーザー決定 2026-08-22）。

        **書いたノートの隣に生やす。** リンクは本文の中にあるので、書いた
        場所と同じフォルダにできるのがいちばん素直で、一覧をどこで絞って
        いても結果が変わらない。

        ゴミ箱の中（捨てたノートを開いたまま書いた）と vault の外は直下に
        戻す。**捨てた場所にノートを生やさない。**
        """
        if self._note is None:
            return None
        folder = self._note.path.parent
        if not folder.is_relative_to(self._vault.root):
            return None
        relative = folder.relative_to(self._vault.root)
        if relative.is_relative_to(TRASH_DIR) or not relative.parts:
            return None
        return relative.as_posix()

    def _remember_backlinks(self, expanded: bool) -> None:
        self._config.backlinks_expanded = expanded

    @property
    def outline_pane(self) -> OutlinePane:
        return self._outline

    def toggle_outline(self) -> None:
        """`Cmd+5`。見出しの一覧を開閉する（提案 5）。

        入口は 4 つ（キー・表示メニュー・歯車・ツールバーのボタン）。
        **どこから押しても同じ状態を指す**ように、ここで一度に揃える。
        """
        self._show_outline(self._outline.isHidden())

    def _show_outline(self, showing: bool) -> None:
        # スプリッタ経由で出し入れする（幅の退避・復元込み）。直に
        # setVisible すると、手で広げた幅が次の起動で失われる
        self._splitter.set_pane_visible(self._splitter.indexOf(self._outline), showing)
        self._config.outline_visible = showing
        self._pane.toolbar.set_outline_checked(showing)
        if showing:
            self._update_outline()

    # ----------------------------------------------------- ローカルLLM（L-1）

    @property
    def assistant_pane(self) -> AssistantPane:
        return self._assistant

    @property
    def llm(self):
        """読ませる相手。設定から作る（ADR-0025 追記）。"""
        return self._llm

    def set_llm(self, client) -> None:
        """読ませる相手を差し替える（テスト用）。"""
        self._llm = client

    def reload_llm(self) -> None:
        """設定を読み直して相手を作り直す。実体は AssistantActions。"""
        self._assistant_actions.reload_llm()

    def ocr_engine(self):
        """画像を文字にする読み手（ADR-0027）。実体は AssistantActions。"""
        return self._assistant_actions.ocr_engine()

    def toggle_assistant(self) -> None:
        """`Cmd+6`。ローカルLLM の欄を開閉する（L-1 / ADR-0025）。"""
        self.show_assistant(self._assistant.isHidden())

    def show_assistant(self, showing: bool) -> None:
        self._assistant_actions.show_assistant(showing)

    def unload_model(self) -> bool:
        """モデルをメモリから降ろす（ユーザー要望 2026-08-24）。"""
        return self._assistant_actions.unload_model()

    def _release_model(self) -> None:
        """黙って降ろす（閉じたとき・終わるとき）。実体は AssistantActions。"""
        self._assistant_actions.release_model()

    def ask_assistant(self, task: llm_module.Task) -> None:
        """今開いているノートを読ませる（L-1）。実体は AssistantActions。"""
        self._assistant_actions.ask_assistant(task)

    def show_related(self, *_args) -> None:
        """関係するノートを並べる（L-3）。実体は AssistantActions。"""
        self._assistant_actions.show_related()

    def ask_question(self, question: str) -> None:
        """vault 全体に質問する（L-2）。実体は AssistantActions。"""
        self._assistant_actions.ask_question(question)

    def stop_assistant(self) -> None:
        """待つのをやめる。実体は AssistantActions。"""
        self._assistant_actions.stop_assistant()

    def history_root(self) -> Path:
        """版の置き場。実体は HistoryActions。"""
        return self._versions.root()

    def keep_version(self, text: str, *, force: bool = False) -> Path | None:
        """今の内容を 1 版として残す（ADR-0023）。実体は HistoryActions。"""
        return self._versions.keep_version(text, force=force)

    def note_versions(self) -> list[history.Version]:
        return self._versions.note_versions()

    def restore_version(self, version: history.Version) -> bool:
        return self._versions.restore_version(version)

    def build_history_dialog(self) -> "HistoryDialog | None":
        return self._versions.build_history_dialog()

    def build_graph_window(self) -> "GraphWindow | None":
        """リンクの図を作る（M-2）。ノートを開いていなければ `None`。

        **起点が無い図は描けない。** 何を見ているのか分からない絵になる。

        **開く前に今の内容を書く。** 打ちかけの `[[…]]` は索引に入って
        いないので、書かずに開くと「さっき書いたリンクが図に無い」になる。
        """
        if self._note is None:
            return None
        self.flush()
        dialog = GraphWindow(
            self,
            start=self._note.title,
            links_for=lambda relation: self._db.link_map(relation=relation),
            relations=self._db.relations(),
            depth=self._config.graph_depth,
            theme=self._theme_watcher.colors,
        )
        dialog.opened.connect(self.activate_note)
        dialog.missed.connect(lambda title: self.notify(f"「{title}」はまだ無いノートです"))
        # **選んだ深さを覚える。** 開くたびに選び直させない。**変えた時点で
        # 書く** — 閉じ方によって覚えたり覚えなかったりすると理由が分からない
        dialog.depth_changed.connect(self._remember_graph_depth)
        return dialog

    def _remember_graph_depth(self, depth: int) -> None:
        self._config.graph_depth = depth

    def show_graph(self) -> None:
        """`Cmd+Shift+R`。リンクの図を開く（M-2 / 仮身ネットワーク）。"""
        dialog = self.build_graph_window()
        if dialog is None:
            self.notify("ノートを開いてから使ってください")
            return
        dialog.exec()
        dialog.deleteLater()

    def insert_table(self) -> None:
        """ツールバーの「表」ボタンと「編集」→「表を作る…」（ユーザー要望 2026-08-26）。

        大きさを聞いてから差し込む。**窓を開くのはここ**——`editor/` は
        ダイアログを持たない（書式ボタンと違うのはこの一点だけ）。
        """
        size = self._ask_table_size()
        if size is None:
            return
        rows, columns = size
        self._editor.insert_table(rows=rows, columns=columns)
        self._editor.setFocus()  # 打てばそのまま見出しが置き換わる

    def _ask_table_size(self) -> tuple[int, int] | None:
        """行と列を聞く。取り消しなら None。**テストが差し替える**。"""
        dialog = TableSizeDialog(self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            return dialog.values()
        finally:
            dialog.deleteLater()

    def show_history(self) -> None:
        """版の履歴を開く（ADR-0023）。実体は HistoryActions。"""
        self._versions.show_history()

    def _history_now(self):
        """今の時刻。**テストが差し替える**ので 1 か所にまとめる。"""
        return datetime.now()

    def _update_outline(self) -> None:
        """本文の見出しを一覧へ流す。

        **隠れているときは数えない。** 打つたびに全文を走査するので、
        出していない人に費用を払わせない。
        """
        if self._outline.isHidden():
            return
        self._outline.set_headings(headings(self._editor.toPlainText()))

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
        self.open_and_select(self._vault.root / relative)

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

    def _known_titles(self) -> list[str]:
        """`[[` の候補（ユーザー要望）。既に**あるノートの題名**。

        **今開いているノートは外す。** 自分へのリンクは意味が無く、
        候補に混ざると選び間違える。ゴミ箱の中も外す（`notes()` の既定）。
        """
        current = self._note.title if self._note is not None else None
        # 打鍵ごとに呼ばれるので、題名だけの軽い問い合わせを使う
        # （notes() は preview 込みの全列で、大きな vault では 16ms 予算を食う）
        return [title for title in self._db.titles() if title != current]

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

    def export_docx(self):
        """Word で書き出す（U-5）。実体は ExportActions。"""
        return self._exports.export_docx()

    def export_pptx(self) -> Path | None:
        return self._exports.export_pptx()

    def print_note(self) -> bool:
        """`Cmd+P`（C-9）。"""
        return self._exports.print_note()

    def hide_export_notice(self) -> None:
        self._exports.hide_notice()

    def reveal_in_finder(self, path: Path) -> None:
        self._exports.reveal_in_finder(path)

    def open_in_finder(self, path: Path) -> None:
        """フォルダ自体を Finder で開く。サイドバーの右クリックから。"""
        self._exports.open_in_finder(path)

    def open_folder_in_finder(self, target) -> None:
        """サイドバーで選んだフォルダを Finder で開く。実体は NoteActions。"""
        self._notes.open_folder_in_finder(target)

    def import_note_files(self, paths: list[Path]) -> list[Path]:
        """一覧へドロップされた `.md` を取り込む。実体は NoteActions。"""
        return self._notes.import_note_files(paths)

    def import_document(self) -> None:
        """「ファイル」→「読み込む…」（F-2）。"""
        self._exports.import_document()

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
        # **入っているモデルを候補に出す。** 名前を 1 文字間違えると動かない
        dialog = PreferencesDialog(self._config, self, models=self._llm.models())
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

        **設定と同じ値を触る。** 別に持つと、片方で変えたときに
        もう片方が古い値を書き戻す。

        **端では丸める。** 上限まで 0.5pt しか無くても、そこまでは動かす
        （押したのに何も起きないより、行けるところまで行くほうが素直）。
        """
        clamped = min(max(size, MIN_POINT_SIZE), MAX_POINT_SIZE)
        if clamped == self._config.font_point_size:
            return False
        self._config.font_point_size = clamped
        self._editor.set_base_point_size(clamped)
        # 横に置くほうも一緒に（U-1）。片方だけ古い大きさで残さない
        self._reference.set_text_style(
            family=self._config.font_family,
            point_size=clamped,
            mono=self._config.mono_family,
        )
        # 1pt の差は見て取りにくい。**変えたことが分かるように**数字を出す
        self.notify(f"文字サイズ {clamped:g}pt")
        return True

    def _apply_preferences(self) -> None:
        """設定を今の画面へ反映する。保管フォルダだけは再起動が要る。"""
        self._editor.set_font_family(self._config.font_family)
        self._editor.set_base_point_size(self._config.font_point_size)
        self._reference.set_text_style(
            family=self._config.font_family,
            point_size=self._config.font_point_size,
            mono=self._config.mono_family,
        )
        self._editor.set_attachment_handler(self.save_attachment)
        self._editor.set_image_base(self._vault.root)
        self._editor.set_mono_family(self._config.mono_family)
        self._editor.set_tab_width(self._config.tab_width)
        self._sidebar.set_line_spacing(self._config.line_spacing)
        self._note_list.set_line_spacing(self._config.line_spacing)
        self._editor.set_content_width(CONTENT_WIDTH_PIXELS[self._config.content_width])
        # 4 字下げの扱い（ADR-0033）。**掛け直しはエディタ側が判断する**
        # （変わっていなければ何もしない）
        self._editor.set_indented_code(self._config.indented_code)
        self._apply_list_font()
        self._theme_watcher.set_mode(self._config.theme_mode)
        self._vault.purge_trash(self._config.trash_days)
        self.reload_llm()
        self._versions.prune()

    # ------------------------------------------------------------------ 表示

    def open_beside(self, path: Path) -> bool:
        """ノートを横の参照ペインに出す（U-1）。出せたら True。

        **本文は入れ替えない。** 書いているノートを奪わずに、もう 1 枚を
        並べるための道。読むだけなので保存も監視も繋がない。
        """
        try:
            note = self._vault.read(path)
        except OSError as error:
            logger.warning("横に開けなかった: %s", error)
            self.notify("そのノートを開けませんでした")
            return False
        self._reference.show_note(note.title, note.text)
        self._splitter.set_pane_visible(self._reference_index(), True)
        return True

    def toggle_reference(self) -> None:
        """横の参照ペインを出し入れする。"""
        self._splitter.toggle_pane(self._reference_index())

    def _reference_index(self) -> int:
        """参照ペインの添字。**末尾に置いてある**ので数え直す。"""
        return self._splitter.indexOf(self._reference)

    def toggle_sidebar(self) -> None:
        self._splitter.toggle_pane(0)

    def toggle_note_list(self) -> None:
        self._splitter.toggle_pane(1)

    def toggle_toolbar(self) -> None:
        self._pane.set_toolbar_visible(not self._pane.toolbar_visible())

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
        self._menu_button.setIcon(glyph_icon(Glyph.GEAR, colors.muted_foreground))
        self._pane.set_theme(colors)
        # 横に置くほうも同じ配色にする（U-1）。片方だけ古い色で描かない
        self._reference.set_theme(colors)
        self._list_pane.set_theme(colors)
        self._sidebar.set_theme(colors)
        # 右の 2 ペインが追従していなかった（ダークで白いままだった）
        self._outline.set_theme(colors)
        self._assistant.set_theme(colors)
        self._splitter.set_rule_color(colors.rule)

    # ------------------------------------------------------------------ 終了

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            # **2 度目は何もしない。** `close()` は明示にも Qt からも来る
            # （テストの後片付けで実際に 2 回来た）。索引を閉じたあとに
            # 保存へ入ると、閉じた DB を触って落ちる
            super().closeEvent(event)
            return
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
        self._config.reference_visible = not self._reference.isHidden()
        self._config.toolbar_visible = self._pane.toolbar_visible()
        self._config.window_geometry = self.saveGeometry()
        self._config.sync()

        self._save_timer.stop()
        self._watcher.stop()
        # **閉じるのを待たせない。** 生成は最長 120 秒かかる（ADR-0025）。
        # 番号を進めておけば、次の 1 行で自分から降りる
        self._assistant_run += 1
        # 閉じたあとに 8.0GB を抱えたままにしない（ユーザー要望 2026-08-24）
        self._release_model()
        # ワーカーが自分の接続で書いている最中に落とさない。
        # **ただし待ちすぎない**（コードレビュー指摘）。既定の 30 秒だと、
        # 大きな vault の走査中に閉じると終わらない窓に見える。索引は
        # 捨ててよいキャッシュ（R9）なので、待ちを打ち切っても作り直せる
        self.wait_for_index_sync(CLOSE_INDEX_WAIT_MS)
        self._db.close()
        super().closeEvent(event)
