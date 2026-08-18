"""ライブプレビュー付きのテキスト編集ウィジェット（spec §4.1, §5.1, §6.4）。

`QPlainTextEdit` を選んだ理由と、`QTextEdit` へ移る可能性については §4.1。
**基底クラスへの依存はこのクラスに閉じ込める**。後で差し替えるときの
コストを下げるため、他のモジュールから `QPlainTextEdit` を直接触らない。
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QInputMethodEvent,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
    QTextBlock,
    QTextCursor,
)
from PySide6.QtWidgets import QListWidget, QPlainTextEdit, QTextEdit, QWidget

from hitofude.core import frontmatter, search, table, tags
from hitofude.core.activation import ActivationKind, activation_at
from hitofude.core.document import plain_text
from hitofude.core.models import BlockInfo
from hitofude.core.textpos import py_to_utf16, utf16_to_py
from hitofude.editor import attachments, commands, painter_overlay
from hitofude.editor.highlighter import TABLE_FAMILIES, MarkdownHighlighter
from hitofude.editor.image_cache import ImageCache
from hitofude.editor.input_handler import EnterKind, enter_action, indent_action
from hitofude.theme import LIGHT, ThemeColors

# 本文を書き換えるキー。front matter を守るために丸める必要がある入力
_EDITING_KEYS = frozenset(
    {
        Qt.Key.Key_Backspace,
        Qt.Key.Key_Delete,
        Qt.Key.Key_Return,
        Qt.Key.Key_Enter,
        Qt.Key.Key_Tab,
        Qt.Key.Key_Backtab,
    }
)

DEFAULT_FONT_FAMILY = "Hiragino Sans"
DEFAULT_POINT_SIZE = 15.0
# タブ幅（文字数）。既定は `config.DEFAULT_TAB_WIDTH` と揃える
DEFAULT_TAB_WIDTH = 4

# タグ補完のポップアップ（C-4）
TAG_POPUP_ROWS = 8
TAG_POPUP_PADDING = 24

logger = logging.getLogger(__name__)


def _modifies_text(event: QKeyEvent) -> bool:
    """その打鍵が本文を書き換えるか。"""
    if event.key() in _EDITING_KEYS:
        return True
    return bool(event.text()) and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)


type _Interval = tuple[int, int]
"""両端を含むブロック番号の範囲。"""


def _interval_symmetric_difference(old: _Interval | None, new: _Interval | None) -> list[_Interval]:
    """2 つの範囲の対称差（片方だけに入る部分）。

    ドラッグで選択を 1 行伸ばしたとき、掛け直すべきは伸びた 1 行だけ。
    集合を作らず区間のまま計算する（10,000 行の選択で set を作らない）。
    """
    if old is None and new is None:
        return []
    if old is None:
        return [new]  # type: ignore[list-item]
    if new is None:
        return [old]

    if old[1] < new[0] or new[1] < old[0]:
        return [old, new]  # 離れていれば両方まるごと

    pieces: list[_Interval] = []
    if old[0] != new[0]:
        pieces.append((min(old[0], new[0]), max(old[0], new[0]) - 1))
    if old[1] != new[1]:
        pieces.append((min(old[1], new[1]) + 1, max(old[1], new[1])))
    return pieces


class MarkdownEditor(QPlainTextEdit):
    link_activated = Signal(str)
    """`Cmd+クリック` されたリンクの URL（D-1）。**開くのは呼び出し側**。
    エディタからブラウザを起動すると、判定と副作用が同じ場所に混ざる。"""

    tag_activated = Signal(str)
    """`Cmd+クリック` されたタグ（D-2）。一覧の絞り込みは `MainWindow` の仕事。"""

    note_activated = Signal(str)
    """`Cmd+クリック` された `[[ノート名]]`（E-6）。名前を解決して開く（無ければ
    作る）のは `MainWindow` の仕事。エディタは vault を知らない。"""

    source_mode_changed = Signal(bool)
    """ソースモードが切り替わった。**入口が 2 つある**（`Cmd+/` と Raw ボタン）
    ので、片方で変えたらもう片方も追従させる。"""

    modes_changed = Signal()
    """書き方のモード（Raw / フォーカス / タイプライタ）が変わった。

    **何がどう変わったかは載せない。** 受け手（ステータスバー）は今の状態を
    見に来ればよく、差分を追う必要がない。"""

    # spec §5.1: 読みやすさのため本文は中央寄せで最大 720px
    MAX_CONTENT_WIDTH = 720

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        theme: ThemeColors = LIGHT,
        font_family: str = DEFAULT_FONT_FAMILY,
        base_point_size: float = DEFAULT_POINT_SIZE,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        # 添付の保存先を知らないまま受け取るための口（R3 の分担を UI 側でも保つ）
        self._attachment_handler: Callable[[bytes, str], str | None] | None = None
        # 既存タグの取り出し口（C-4）。索引はエディタの外にある
        self._tag_source: Callable[[], list[str]] | None = None
        self._tag_candidates: list[str] = []
        self._tag_popup = QListWidget(self)
        self._tag_popup.setWindowFlags(Qt.WindowType.ToolTip)
        self._tag_popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tag_popup.itemClicked.connect(lambda entry: self.complete_tag(entry.text()))
        self._tag_popup.hide()

        font = QFont(font_family)
        font.setPointSizeF(base_point_size)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setTabChangesFocus(False)
        # ボタンを押していない移動も受け取る。**これが無いと `mouseMoveEvent`
        # そのものが来ない**ので、ホバーの判定に一切入らない（G-2）
        self.viewport().setMouseTracking(True)
        self._tab_width = DEFAULT_TAB_WIDTH

        # 表 1 行に使える桁数。幅とフォントで決まる（`_update_table_columns`）
        self._table_columns = 0
        self._images = ImageCache()
        self._highlighter = MarkdownHighlighter(
            self.document(), theme, base_point_size=base_point_size
        )
        self._highlighter.set_image_source(self._images, self.image_width())
        # 等幅フォントの字幅で決まるので、ハイライタを作ったあとに呼ぶ
        self._apply_tab_width()

        # リビールで掛け直す「旧ブロック」を覚えておく（R7）
        self._last_block = 0
        self._last_selection: tuple[int, int] | None = None
        # rehighlightBlock() は selectionChanged を再発火させる。
        # ガードが無いと _sync_reveal が自分自身を呼び続けて再帰で落ちる。
        self._syncing = False
        # IME のプリエディット中かどうか（R6）
        self._composing = False
        self._focus_mode = False
        # 最後にマウスが居た場所（viewport 座標）。`Cmd` を押しただけのときに
        # どこを指しているかを知るために覚える。まだ来ていなければ `None`
        self._hover_point: QPoint | None = None
        self._typewriter_mode = False
        # 整形が走っている最中に自分自身を呼ばないためのガード
        self._formatting = False

        self.cursorPositionChanged.connect(self._sync_reveal)
        self.selectionChanged.connect(self._sync_reveal)

        self._apply_palette()
        self._update_table_columns()
        self._sync_reveal()

    @property
    def highlighter(self) -> MarkdownHighlighter:
        return self._highlighter

    # --------------------------------------------------------------- テーマ

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._apply_palette()
        self._highlighter.set_theme(theme)

    def _apply_palette(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(self._theme.background))
        palette.setColor(QPalette.ColorRole.Text, QColor(self._theme.foreground))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(self._theme.selection_background))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(self._theme.foreground))
        self.setPalette(palette)

    # ----------------------------------------------------------- ソースモード

    def set_source_mode(self, enabled: bool) -> None:
        """`Cmd+/`。全マーカーを表示する（§6.4）。

        表示ルールが文書全体で変わるため、ここは全体再ハイライトしてよい。
        """
        if enabled == self._highlighter.source_mode:
            return
        self._highlighter.set_source_mode(enabled)
        self._highlighter.rehighlight()
        self.viewport().update()  # 飾りの有無が変わる（`painter_overlay`）
        self.source_mode_changed.emit(enabled)
        self.modes_changed.emit()

    def toggle_source_mode(self) -> None:
        self.set_source_mode(not self._highlighter.source_mode)

    # --------------------------------------------------- 執筆用のモード（§5.4）

    def set_focus_mode(self, enabled: bool) -> None:
        """`Cmd+Shift+D`。現在段落以外を減光する。"""
        if enabled == self._focus_mode:
            return
        self._focus_mode = enabled
        self.viewport().update()
        self.modes_changed.emit()

    def toggle_focus_mode(self) -> None:
        self.set_focus_mode(not self._focus_mode)

    @property
    def focus_mode(self) -> bool:
        return self._focus_mode

    def set_typewriter_mode(self, enabled: bool) -> None:
        """`Cmd+Shift+Y`。キャレット行を画面中央に保つ。"""
        if enabled == self._typewriter_mode:
            return
        self._typewriter_mode = enabled
        if enabled:
            self._center_caret()
        self.modes_changed.emit()

    def toggle_typewriter_mode(self) -> None:
        self.set_typewriter_mode(not self._typewriter_mode)

    @property
    def typewriter_mode(self) -> bool:
        return self._typewriter_mode

    @property
    def source_mode(self) -> bool:
        """生の Markdown を出しているか（`Cmd+/` / Raw ボタン）。"""
        return self._highlighter.source_mode

    def _center_caret(self) -> None:
        """キャレット行が画面中央に来るようスクロールする。"""
        cursor_rect = self.cursorRect()
        middle = self.viewport().height() // 2
        delta = cursor_rect.center().y() - middle
        if delta == 0:
            return
        bar = self.verticalScrollBar()
        line_height = max(1, cursor_rect.height())
        bar.setValue(bar.value() + round(delta / line_height))

    def plain_text_selection(self) -> str:
        """`Cmd+Shift+C`。マーカーを除いた文字列を返す（spec §5.4）。

        選択が無ければ本文全体。ソースは変えない（R1）。
        """
        cursor = self.textCursor()
        source = cursor.selection().toPlainText() if cursor.hasSelection() else self.toPlainText()
        # QTextCursor は改行を U+2029 で返す
        return plain_text(source.replace("\u2029", "\n"))

    def copy_as_plain_text(self) -> bool:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.plain_text_selection())
        return True

    def tab_width(self) -> int:
        """タブを何文字ぶんの幅で見せているか。"""
        return self._tab_width

    def set_tab_width(self, width: int) -> None:
        """タブ幅を文字数で決める。

        **px ではなく「空白いくつぶん」で持つ。** px で覚えると、文字サイズや
        フォントを変えたときにタブだけ幅が合わなくなる。Qt の既定は 80px 固定で、
        本文フォントだと 12 文字ぶんもあった（実測。違和感の元）。
        """
        self._tab_width = max(1, int(width))
        self._apply_tab_width()

    def _apply_tab_width(self) -> None:
        """**等幅フォントの空白幅**で決める。

        本文フォントで決めると、コードブロックの中で文字数が合わない。
        Hiragino Sans の空白は 6.66px、Menlo は 12.03px（15pt での実測）なので、
        「4 文字」と設定してもコードの中では 2.2 文字ぶんにしか見えなかった
        （ユーザー報告）。タブを使うのはほぼコードの中なので、そちらに合わせる。
        """
        font = QFont(self._highlighter.mono_family)
        font.setPointSizeF(self.font().pointSizeF())
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" " * self._tab_width))
        # 文字が大きくなれば表に入る桁数も減る
        self._update_table_columns()

    def set_font_family(self, family: str) -> None:
        font = self.font()
        font.setFamily(family)
        self.setFont(font)
        self._apply_tab_width()  # 字幅が変わるとタブの文字数も変わる

    def set_mono_family(self, family: str) -> None:
        self._highlighter.set_mono_family(family)
        self._apply_tab_width()  # タブ幅は等幅フォントの字幅で決まる

    def format_table(self) -> bool:
        """キャレットのある表の縦線を揃える（spec §1.2）。

        WYSIWYG な表エディタは作らない代わりに、ソースを整えて等幅で見せる。
        日本語は全角 2 桁で数えるので、文字数ではなく表示幅で揃う。
        """
        if self._composing:
            return False  # R6: メニューからも呼ばれる。打鍵経路のガードでは足りない
        cursor = self.textCursor()
        lines = self.toPlainText().split("\n")
        found = table.find_table(lines, self._table_anchor_line(cursor))
        if found is None:
            return False
        return self._apply_table_format(lines, found)

    def _autoformat_left_table(self, old_line: int, new_line: int) -> None:
        """表の行から離れたら縦線を揃える（§1.2）。

        打っている最中は動かさない。整形はキャレットを動かすので、
        入力のたびに走らせると書けたものではなくなる。
        """
        if old_line == new_line or self._composing or self._formatting:
            return
        # Redo の待ちがあるうちは触らない。整形は見た目の都合であって、
        # Cmd+Z で戻した直後に本文を書き換えると Redo スタックが消え、
        # 「整形のやり直し」が事実上できなくなる。次の編集で待ちが消えれば
        # 整形も再開する
        if self.document().isRedoAvailable():
            return

        lines = self.toPlainText().split("\n")
        found = table.find_table(lines, old_line)
        if found is None or found[0] <= new_line < found[1]:
            return  # 表の中を移動しただけ

        self._formatting = True
        try:
            self._apply_table_format(lines, found)
        finally:
            self._formatting = False

    def _apply_table_format(self, lines: list[str], found: tuple[int, int]) -> bool:
        """表の範囲を整形する。キャレットは今いる場所に残す。"""
        start, end = found
        formatted = table.format_table(lines[start:end])
        if formatted is None or formatted == lines[start:end]:
            return False

        cursor = self.textCursor()
        keep_line, keep_column = cursor.blockNumber(), cursor.positionInBlock()

        document = self.document()
        first = document.findBlockByNumber(start)
        last = document.findBlockByNumber(end - 1)

        edit = QTextCursor(first)
        edit.beginEditBlock()
        edit.setPosition(first.position())
        edit.setPosition(last.position() + last.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        edit.insertText("\n".join(formatted))
        edit.endEditBlock()

        # 行数は変わらないので、行番号と桁で戻せる
        block = document.findBlockByNumber(keep_line)
        if block.isValid():
            edit.setPosition(block.position() + min(keep_column, max(0, block.length() - 1)))
            self.setTextCursor(edit)

        # 整形中はキャレットが表の中を通るため、その時点のリビール状態で
        # ハイライトされた行が残る。R7 により以後は掛け直されないので、
        # ここで表の範囲だけ明示的に掛け直す
        for number in range(start, end):
            target = document.findBlockByNumber(number)
            if target.isValid():
                self._highlighter.rehighlightBlock(target)
        return True

    def _table_anchor_line(self, cursor: QTextCursor) -> int:
        """整形の起点にする行。

        選択があるときはキャレットが選択の**末尾**にあり、表全体を選ぶと
        表の下の空行を指してしまう。選択の先頭側を見る。
        """
        if not cursor.hasSelection():
            return cursor.blockNumber()
        probe = QTextCursor(cursor)
        probe.setPosition(cursor.selectionStart())
        return probe.blockNumber()

    def set_base_point_size(self, size: float) -> None:
        font = self.font()
        font.setPointSizeF(size)
        self.setFont(font)
        self._highlighter.set_base_point_size(size)
        self._apply_tab_width()  # 字幅が変わるとタブの文字数も変わる

    # --------------------------------------------------------------- 入力

    def is_composing(self) -> bool:
        """IME で変換中か（R6 / spec §5.5）。"""
        return self._composing

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        # プリエディット文字列の有無が変換中かどうかそのもの。
        # `inputMethodQuery()` では確定前後を確実には区別できない。
        if not self._composing:
            # 変換の開始位置を本文の中へ寄せる。変換中に動かすと
            # プリエディットが壊れるので、始まる前だけ
            self._guard_front_matter()
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Control:
            # **リンクの上にマウスを置いたまま `Cmd` を押す**のが自然な順。
            # 移動を待っていると、そのとき形が変わらず「押せる」ことが伝わらない
            self._update_hover(held=True)

        if event.key() == Qt.Key.Key_Escape and self._tag_candidates:
            # 候補が出ているときの Esc は「候補を閉じる」。本文には触らない
            self._tag_candidates = []
            self._hide_tag_popup()
            return

        # **変換中は特殊処理をすべて無効化する（R6）。** 日本語変換の確定 Enter を
        # リスト継続と取り違えると、確定のたびに項目が増えて日本語入力が破綻する。
        # 仕様書が「ここを怠ると壊滅的」と名指ししている箇所。
        # （関数の途中に文字列リテラルとして置かれていて docstring として
        # 機能していなかったため、コメントに直した）
        if self._composing:
            super().keyPressEvent(event)
            return

        if event.matches(QKeySequence.StandardKey.SelectAll):
            # `cut()` と同じ理由。標準のキー割り当ては仮想メソッドを通らない
            self.selectAll()
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Cut):
            # `QPlainTextEdit` は標準のキー割り当てを内部で処理し、仮想メソッドの
            # `cut()` を通らない。守りのある経路へ寄せる
            self.cut()
            event.accept()
            return

        if _modifies_text(event) and self._guard_front_matter(event):
            event.accept()
            return

        plain = event.modifiers() in (
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.KeypadModifier,
        )
        key = event.key()

        if plain and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._handle_return():
            return
        if plain and key == Qt.Key.Key_Tab and self._handle_indent(forward=True):
            return
        if key == Qt.Key.Key_Backtab and self._handle_indent(forward=False):
            return
        if self._handle_shortcut(event):
            return
        if plain and self._handle_auto_pair(event.text()):
            return
        if self._is_unhandled_command(event):
            # 知らない Cmd の組み合わせで文字を入れない。macOS では
            # Cmd+Option+T が `†` を生む。選択中だと**選択範囲が消える**
            event.accept()
            return

        super().keyPressEvent(event)
        # 打ったあとに候補を出し直す（C-4）。変換中は中で弾く
        self.update_tag_completion()

    # -------------------------------------------------- front matter の保護

    def _guard_front_matter(self, event: QKeyEvent | None = None) -> bool:
        """front matter より前を編集させない。捨てるべき入力なら True。

        front matter はハイライタが潰すので**画面には見えない**。位置 0 は
        見た目の先頭でも実際には `---` の前で、そこへ打つと front matter が
        本文の下へ押し出される。`split()` が認識できなくなり、`id` と
        `modified` が黙って失われる（新規ノートを作ってすぐ打つと起きた）。

        選択があるときは**始点だけ**を本文の先頭へ丸める。`Cmd+A` で選んで
        打ち直す操作を、front matter を残したまま成立させるため。
        """
        source = self.toPlainText()
        offset = frontmatter.body_offset(source)
        if offset == 0:
            return False
        offset = py_to_utf16(source, offset)  # カーソル位置（UTF-16）と比べる

        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        if start < offset:
            cursor.setPosition(offset)
            if end > offset:
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            cursor = self.textCursor()

        # 本文の先頭で Backspace を押しても front matter を食べさせない
        return (
            event is not None
            and event.key() == Qt.Key.Key_Backspace
            and not cursor.hasSelection()
            and cursor.position() <= offset
        )

    @staticmethod
    def _is_unhandled_command(event: QKeyEvent) -> bool:
        return bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and bool(event.text())

    # ----------------------------------------------------------- コマンド

    def _handle_shortcut(self, event: QKeyEvent) -> bool:
        """spec §5.4 のキーバインド。macOS では ControlModifier が Cmd。"""
        modifiers = event.modifiers()
        command = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        # macOS では物理 Ctrl が MetaModifier に入る
        meta = bool(modifiers & Qt.KeyboardModifier.MetaModifier)
        if not command:
            return False

        key = event.key()
        if meta:
            # 見出しレベル ± は spec §5.4 どおり `Cmd+Ctrl+↑/↓`。
            # 以前の `Cmd+Shift+↑/↓` は macOS 標準の「文頭 / 文末まで選択」を
            # 奪っていた。ここで return して、Cmd+Ctrl の他の組み合わせが
            # 下の Cmd 単独の分岐に落ちないようにする
            if not shift and not alt:
                match key:
                    case Qt.Key.Key_Up:
                        return self.shift_heading(-1)
                    case Qt.Key.Key_Down:
                        return self.shift_heading(1)
            return False
        if not shift and not alt:
            match key:
                case Qt.Key.Key_B:
                    return self.toggle_strong()
                case Qt.Key.Key_I:
                    return self.toggle_emphasis()
                case Qt.Key.Key_E:
                    return self.toggle_code()
                case Qt.Key.Key_K:
                    return self.insert_link()
                case Qt.Key.Key_Slash:
                    self.toggle_source_mode()
                    return True
        if shift and not alt:
            match key:
                case Qt.Key.Key_X:
                    return self.toggle_strike()
                case Qt.Key.Key_H:
                    return self.toggle_highlight()
                case Qt.Key.Key_T:
                    return self.toggle_checkbox()
                case Qt.Key.Key_C:
                    return self.copy_as_plain_text()
                case Qt.Key.Key_D:
                    self.toggle_focus_mode()
                    return True
                case Qt.Key.Key_Y:
                    self.toggle_typewriter_mode()
                    return True
        return False

    def toggle_strong(self) -> bool:
        return self._toggle_wrap("**")

    def toggle_emphasis(self) -> bool:
        return self._toggle_wrap("*")

    def toggle_code(self) -> bool:
        return self._toggle_wrap("`")

    def toggle_strike(self) -> bool:
        return self._toggle_wrap("~~")

    def toggle_highlight(self) -> bool:
        return self._toggle_wrap("::")

    def _toggle_wrap(self, marker: str) -> bool:
        if self._composing:
            # R6: ツールバーのボタンは NoFocus なので、プリエディットが
            # 生きたままクリックできる。keyPressEvent のガードだけでは足りない
            return False
        cursor = self.textCursor()
        source = self.toPlainText()
        # 選択位置は UTF-16 単位、commands は Python 文字列を切り貼りする
        replacement = commands.toggle_wrap(
            source,
            utf16_to_py(source, cursor.selectionStart()),
            utf16_to_py(source, cursor.selectionEnd()),
            marker,
        )
        self._apply(replacement)
        return True

    def insert_link(self, url: str = "") -> bool:
        """`Cmd+K`。選択文字を `[選択](url)` にする（spec §5.4）。"""
        if self._composing:
            return False  # R6
        cursor = self.textCursor()
        source = self.toPlainText()
        replacement = commands.insert_link(
            source,
            utf16_to_py(source, cursor.selectionStart()),
            utf16_to_py(source, cursor.selectionEnd()),
            url,
        )
        self._apply(replacement)
        return True

    def shift_heading(self, delta: int) -> bool:
        """見出しレベルの増減。`delta` が負だと `#` が減って見出しが大きくなる。"""
        block = self.textCursor().block()
        if self._composing:
            return False  # R6
        new_line = commands.shift_heading(block.text(), delta)
        if new_line is None:
            return False
        self._replace_current_block(new_line)
        return True

    def toggle_checkbox(self) -> bool:
        if self._composing:
            return False  # R6
        block = self.textCursor().block()
        new_line = commands.toggle_checkbox(block.text(), self._current_info())
        if new_line is None:
            return False
        self._replace_current_block(new_line)
        return True

    def cycle_heading(self) -> bool:
        """段落 → H1 → H2 → H3 → 段落（ツールバーの「見出し」）。"""
        if self._composing:
            return False
        self._replace_current_block(commands.cycle_heading(self.textCursor().block().text()))
        return True

    def toggle_bullet(self) -> bool:
        """箇条書きにする / 外す。選んだ行すべてが対象。"""
        return self._toggle_lines(commands.toggle_bullet)

    def toggle_ordered(self) -> bool:
        """番号付きにする / 外す。番号は 1 から振り直す。"""
        return self._toggle_lines(commands.toggle_ordered)

    def toggle_quote(self) -> bool:
        """引用にする / 外す。"""
        return self._toggle_lines(commands.toggle_quote)

    def _toggle_lines(self, toggle: Callable[[list[str]], list[str]]) -> bool:
        """行単位のトグルを選択範囲に当てる。

        **行の一部だけを選んでいても、その行は丸ごと対象にする。** 行の途中に
        リスト記号は付けられない。
        """
        if self._composing:
            return False  # R6: 確定前の文字列を巻き込むとプリエディットが壊れる

        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart())
        last = document.findBlock(cursor.selectionEnd())

        lines = [
            document.findBlockByNumber(number).text()
            for number in range(first.blockNumber(), last.blockNumber() + 1)
        ]
        replaced = toggle(lines)
        if replaced == lines:
            return False  # 何も変わらないなら Undo スタックを消費しない

        start = first.position()
        edit = QTextCursor(first)
        edit.beginEditBlock()
        edit.setPosition(start)
        edit.setPosition(last.position() + last.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        edit.insertText("\n".join(replaced))
        edit.endEditBlock()

        # **選択は行を覆ったまま残す。** 残さないと 2 回目が 1 行にしか
        # 効かず、押し間違えたときに同じボタンで戻せない
        edit.setPosition(start)
        edit.setPosition(start + len("\n".join(replaced)), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(edit)
        return True

    def _handle_auto_pair(self, character: str) -> bool:
        """選択したまま囲み記号を押すと選択範囲を囲む（spec §5.5-4）。"""
        cursor = self.textCursor()
        if not cursor.hasSelection() or character not in commands.AUTO_PAIRS:
            return False
        closing = commands.AUTO_PAIRS[character]
        selected = cursor.selectedText()
        start = cursor.selectionStart()
        cursor.insertText(f"{character}{selected}{closing}")
        cursor.setPosition(start + len(character))
        cursor.setPosition(start + len(character) + len(selected), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        return True

    # ------------------------------------------------------------------ 画像

    @property
    def image_cache(self) -> ImageCache:
        return self._images

    def image_width(self) -> int:
        """本文中に描く画像の最大幅。本文の折り返し幅に合わせる。"""
        return self.MAX_CONTENT_WIDTH - int(self.document().documentMargin()) * 2

    def set_image_base(self, base_path) -> None:
        """画像を探す起点（保管フォルダ）。変えると抱えていた絵を捨てる。"""
        self._images.set_base_path(base_path)
        self._highlighter.set_image_source(self._images, self.image_width())
        # 等幅フォントの字幅で決まるので、ハイライタを作ったあとに呼ぶ
        self._apply_tab_width()
        self._highlighter.rehighlight()

    def refresh_images(self) -> None:
        """外で画像が差し替わったときに読み直す。"""
        self._images.clear()
        self._highlighter.rehighlight()

    # ------------------------------------------------------------------ 添付

    # ------------------------------------------------------------- タグ補完

    def set_tag_source(self, source: Callable[[], list[str]] | None) -> None:
        """既存タグの取り出し口（C-4）。

        **エディタは索引を知らない。** 呼び出し側（`MainWindow`）が渡す。
        添付の保存先と同じ形で、R3 の分担を UI 側でも保つ。
        """
        self._tag_source = source

    def tag_candidates(self) -> list[str]:
        """今出ている候補。空なら出していない。"""
        return list(self._tag_candidates)

    def update_tag_completion(self) -> None:
        """打っている位置を見て候補を出し直す（C-4）。

        **変換中は出さない**（R6）。確定前に一覧が出ると変換候補と重なる。
        """
        self._tag_candidates = []
        if self._composing or self._tag_source is None:
            self._hide_tag_popup()
            return

        cursor = self.textCursor()
        line = cursor.block().text()
        prefix = tags.prefix_at(line, utf16_to_py(line, cursor.positionInBlock()))
        if prefix is None:
            self._hide_tag_popup()
            return

        self._tag_candidates = tags.matches(prefix, self._tag_source())
        if not self._tag_candidates:
            self._hide_tag_popup()
            return
        self._show_tag_popup()

    def complete_tag(self, tag: str) -> None:
        """打ちかけのタグを候補で置き換える（C-4）。"""
        cursor = self.textCursor()
        line = cursor.block().text()
        prefix = tags.prefix_at(line, utf16_to_py(line, cursor.positionInBlock()))
        if prefix is None:
            return

        cursor.beginEditBlock()
        # 戻る距離は UTF-16 単位で数える（タグに BMP 外の文字が入っても壊さない）
        prefix_units = py_to_utf16(prefix, len(prefix))
        cursor.setPosition(cursor.position() - prefix_units, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(tag)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self._tag_candidates = []
        self._hide_tag_popup()

    def _show_tag_popup(self) -> None:
        popup = self._tag_popup
        popup.clear()
        popup.addItems(self._tag_candidates)
        popup.setCurrentRow(0)
        rect = self.cursorRect()
        popup.move(self.viewport().mapToGlobal(rect.bottomLeft()))
        popup.resize(
            popup.sizeHintForColumn(0) + TAG_POPUP_PADDING,
            popup.sizeHintForRow(0) * min(len(self._tag_candidates), TAG_POPUP_ROWS)
            + TAG_POPUP_PADDING,
        )
        popup.show()

    def _hide_tag_popup(self) -> None:
        if self._tag_popup.isVisible():
            self._tag_popup.hide()

    def _dismiss_tag_popup(self) -> None:
        """候補ごと閉じる。

        ポップアップは独立ウィンドウ（ToolTip）なので、閉じ忘れると画面に
        浮いたまま残る。出し直す契機（打鍵）以外でキャレットが動いたり、
        エディタから離れたりしたらここで畳む。候補も消すのは、残っていると
        Esc がポップアップ閉じに吸われて本文へ届かないため。
        """
        self._tag_candidates = []
        self._hide_tag_popup()

    def focusOutEvent(self, event) -> None:
        self._dismiss_tag_popup()
        super().focusOutEvent(event)

    def set_attachment_handler(self, handler: Callable[[bytes, str], str | None] | None) -> None:
        """画像を受け取ったときの保存先を差し込む。

        エディタは**どこへ保存するかを知らない**。バイト列と拡張子を渡し、
        返ってきた Markdown を挿すだけ。保存先を決めるのは `storage/vault.py`。
        繋がっていなければ画像を受け取らない（壊れたリンクを本文へ書かない）。
        """
        self._attachment_handler = handler

    def selectAll(self) -> None:
        """本文だけを選ぶ。

        front matter まで選ぶと、`id` や日時が画面に現れて選択色で塗られる
        （選択範囲に入った要素は記号を見せる仕組みのため）。編集の経路では
        丸めているので消えはしないが、**消えるように見える**し、コピーすれば
        実際に混ざる。ユーザーにとっての「すべて」は本文。
        """
        source = self.toPlainText()
        offset = frontmatter.body_offset(source)
        if offset == 0:
            super().selectAll()
            return

        cursor = self.textCursor()
        cursor.setPosition(py_to_utf16(source, offset))
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def cut(self) -> None:
        """front matter ごと切り取らせない。

        **`cut()` は `keyPressEvent` も `insertFromMimeData` も通らない。**
        `Cmd+A` から `Cmd+X` で front matter が消えていた（ユーザー報告）。
        入力の経路ごとに守りを足していたため、ここだけ抜けていた。
        """
        self._guard_front_matter()
        super().cut()

    def canInsertFromMimeData(self, source) -> bool:
        if self._looks_like_attachment(source):
            return True
        return super().canInsertFromMimeData(source)

    def _looks_like_attachment(self, source) -> bool:
        return self._attachment_handler is not None and attachments.looks_like_attachment(source)

    def _insert_attachments(self, found: list[tuple[bytes, str]]) -> bool:
        """保存して Markdown を挿す。1 回の Undo で戻せるようまとめる。"""
        handler = self._attachment_handler
        if handler is None:
            return False

        links = []
        for data, suffix in found:
            link = handler(data, suffix)
            if link:
                links.append(link)
        if not links:
            return False

        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            cursor.insertText("\n".join(links))
        finally:
            cursor.endEditBlock()
        return True

    def insertFromMimeData(self, source) -> None:
        """選択があってクリップボードが URL ならリンクにする（spec §5.5-5）。"""
        self._guard_front_matter()

        if self._looks_like_attachment(source):
            self._insert_attachments(attachments.extract(source))
            return

        cursor = self.textCursor()
        text = source.text() if source.hasText() else ""
        if cursor.hasSelection() and commands.is_url(text):
            replacement = commands.insert_link(
                self.toPlainText(), cursor.selectionStart(), cursor.selectionEnd(), text.strip()
            )
            self._apply(replacement)
            return
        super().insertFromMimeData(source)

    def _apply(self, replacement: commands.Replacement) -> None:
        # `Replacement` の位置は Python 単位。start/end は置き換え前、
        # select_* は置き換え後のテキストに対する位置なので、別々に直す
        source = self.toPlainText()
        updated = source[: replacement.start] + replacement.text + source[replacement.end :]
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(py_to_utf16(source, replacement.start))
        cursor.setPosition(py_to_utf16(source, replacement.end), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement.text)
        cursor.endEditBlock()
        cursor.setPosition(py_to_utf16(updated, replacement.select_start))
        cursor.setPosition(
            py_to_utf16(updated, replacement.select_end), QTextCursor.MoveMode.KeepAnchor
        )
        self.setTextCursor(cursor)

    def _replace_current_block(self, text: str) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()
        column = utf16_to_py(line, cursor.positionInBlock()) + len(text) - len(line)
        self._replace_block(cursor, text, column=max(0, column))
        self.setTextCursor(cursor)

    def _current_info(self) -> BlockInfo | None:
        data = self.textCursor().block().userData()
        return data.info if data is not None else None

    def _handle_return(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False  # 選択の置き換えという通常の挙動を邪魔しない

        block = cursor.block()
        column = utf16_to_py(block.text(), cursor.positionInBlock())
        action = enter_action(block.text(), column, self._current_info())

        match action.kind:
            case EnterKind.DEFAULT:
                return False
            case EnterKind.CONTINUE:
                cursor.insertText("\n" + action.text)
            case EnterKind.RESET:
                self._replace_block(cursor, action.text, column=len(action.text))
        self.setTextCursor(cursor)
        return True

    def _handle_indent(self, *, forward: bool) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False

        block = cursor.block()
        new_line = indent_action(block.text(), self._current_info(), forward=forward)
        if new_line is None:
            return False

        # 同じ文字の上にキャレットを残す。行頭の空白が増減した分だけずらす
        shift = len(new_line) - len(block.text())
        column = max(0, utf16_to_py(block.text(), cursor.positionInBlock()) + shift)
        self._replace_block(cursor, new_line, column=column)
        self.setTextCursor(cursor)
        return True

    def _replace_block(self, cursor: QTextCursor, text: str, *, column: int) -> None:
        """現在行の中身を差し替える。Undo は 1 手にまとめる。

        `column` は Python 単位（`text` の文字位置）で受け取る。
        """
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        cursor.endEditBlock()
        cursor.setPosition(cursor.block().position() + py_to_utf16(text, min(column, len(text))))

    # ------------------------------------------------------------- リビール

    def _sync_reveal(self) -> None:
        """キャレット位置をハイライタへ伝え、**必要なブロックだけ**掛け直す。

        全体再ハイライトは絶対にしない（R7）。10,000 語のノートで
        カーソルを動かすたびに全ブロックを走査すると G5（16ms）が壊れる。
        """
        if self._syncing:
            return
        previous_block = self._last_block
        self._syncing = True
        try:
            cursor = self.textCursor()
            selection = (
                (cursor.selectionStart(), cursor.selectionEnd()) if cursor.hasSelection() else None
            )
            self._highlighter.set_reveal(cursor.position(), selection)

            for block in self._affected_blocks(cursor.blockNumber(), selection):
                self._highlighter.rehighlightBlock(block)

            self._last_block = cursor.blockNumber()
            self._last_selection = selection
        finally:
            self._syncing = False

        self._autoformat_left_table(previous_block, self.textCursor().blockNumber())

        if self._typewriter_mode:
            self._center_caret()
        if self._focus_mode:
            self.viewport().update()

    def _affected_blocks(
        self, current_block: int, selection: tuple[int, int] | None
    ) -> list[QTextBlock]:
        """表示が変わりうるブロックだけを集める。

        通常は旧ブロックと新ブロックの高々 2 個。選択があるときは、
        「選択範囲に交差するブロックは全表示」（§6.4）を満たしつつ、
        掛け直すのは旧選択と新選択の**対称差**だけにする。両方に入っている
        ブロックは前回すでに全表示になっていて変わらない。和集合を毎回
        掛け直すと、ドラッグや `Cmd+A` で実質の全体再ハイライトになり、
        大きなノートで R7（§6.6 の 16ms）が破れる。
        """
        document = self.document()
        numbers: set[int] = {self._last_block, current_block}

        old = self._block_span(self._last_selection)
        new = self._block_span(selection)
        for begin, end in _interval_symmetric_difference(old, new):
            numbers.update(range(begin, end + 1))

        blocks = []
        for number in sorted(numbers):
            block = document.findBlockByNumber(number)
            if block.isValid():
                blocks.append(block)
        return blocks

    def _block_span(self, selection: tuple[int, int] | None) -> tuple[int, int] | None:
        """選択が覆うブロック番号の範囲（両端含む）。選択が無ければ None。"""
        if selection is None:
            return None
        document = self.document()
        return (
            document.findBlock(selection[0]).blockNumber(),
            document.findBlock(selection[1]).blockNumber(),
        )

    # ----------------------------------------------------------- レイアウト

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Control:
            self._update_hover(held=False)
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        """`Cmd+クリック` でリンクを開き、タグで絞り込む（D-1 / D-2）。

        **キャレットは動かす。** 開いたあとそのまま本文を直せるほうがよい。
        素のクリックは今まで通り（判定を挟むと編集の邪魔になる）。
        """
        super().mousePressEvent(event)
        self._dismiss_tag_popup()  # クリックでキャレットが動く。候補は打鍵で出し直す
        point = event.position().toPoint()
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._maybe_toggle_checkbox(point)
            return
        found = self._activation_at(point)
        if found is None:
            return
        match found.kind:
            case ActivationKind.LINK:
                self.link_activated.emit(found.payload)
            case ActivationKind.NOTE:
                self.note_activated.emit(found.payload)
            case _:
                self.tag_activated.emit(found.payload)

    def mouseMoveEvent(self, event) -> None:
        """押せるものの上で、カーソルを手の形にする（G-2）。

        **`Cmd` を押している間だけ。** 素の移動で形が変わると、文字を
        選ぼうとしただけで手になって落ち着かない。開く操作自体が
        `Cmd+クリック` なので、条件も揃う。

        判定は `activation_at()`（`core/activation.py`）に任せる。
        **押せないもの（`javascript:` など）は押せそうに見せない。**
        """
        super().mouseMoveEvent(event)
        self._hover_point = event.position().toPoint()
        self._update_hover(held=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))

    def _update_hover(self, *, held: bool) -> None:
        """今の位置と `Cmd` の状態から、カーソルの形を決める。"""
        clickable = (
            held and self._hover_point is not None and self._activation_at(self._hover_point)
        )
        shape = Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.IBeamCursor
        if self.viewport().cursor().shape() is not shape:
            self.viewport().setCursor(shape)

    def _activation_at(self, point):
        """その位置で `Cmd+クリック` したときに何か起きるか。"""
        cursor = self.cursorForPosition(point)
        data = cursor.block().userData()
        if data is None:
            return None
        line = cursor.block().text()
        return activation_at(data.spans, utf16_to_py(line, cursor.positionInBlock()))

    def _maybe_toggle_checkbox(self, point) -> None:
        """印の上を押したらチェックを切り替える（E-1）。

        **`Cmd` は要らない。** 押す場所が印の上に限られていて誤爆しにくく、
        毎回修飾キーを押させるほうが煩わしい。**本文の上では切り替えない。**
        読んでいるだけで状態が変わっては困る。

        Raw では何もしない。記号を直に触るモードなので、クリックは素の意味
        （キャレットの移動）のままにする。
        """
        if self._highlighter.source_mode:
            return
        block = self.cursorForPosition(point).block()
        data = block.userData()
        if data is None or data.info.checked is None:
            return

        geometry = self.blockBoundingGeometry(block).translated(self.contentOffset())
        box = painter_overlay.checkbox_rect(self, block, data.info, geometry)
        if box is None or not box.contains(point):
            return
        self.toggle_checkbox()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """スクロールしたら**画面全体**を描き直す。

        Qt は既にある絵をずらして、新しく出た帯だけを塗り直す。ふつうは
        それで足りるが、**飾りは画面の外の行にも依存する**（ADR-0002 で
        ブロック書式を使わないため、表の罫線もヘッダの帯もここで描く）。

        表のヘッダの帯は区切り行（`|---|`）が見えて初めて決まる。区切り行が
        下から入ってきた時点では、ヘッダ行はもう帯の外にあるので塗られず、
        白いまま上へずれていく（ユーザー報告）。カーソルキーで動かすと
        直って見えるのは、キャレット移動が別に塗り直しを起こすため。

        実測: 中央値 1.9ms、95 パーセンタイル 3.0ms（マニュアルを全面
        スクロール、273 回）。60fps の 16.7ms に対して十分収まる。
        """
        super().scrollContentsBy(dx, dy)
        self._dismiss_tag_popup()  # 画面に置き去りにしない（キャレット位置とずれる）
        self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """本文の下に背景要素を、上にチェックボックス記号を描く（§5.2, ADR-0002）。

        ブロック書式が使えないため、引用の縦バーもコードの背景も水平線も
        ここでしか描けない。順序が重要で、背景は `super()` の前、
        本文に重ねる記号は後に描く。
        """
        try:
            decorations = painter_overlay.visible_decorations(self)
            if self._focus_mode:
                decorations = decorations + painter_overlay.focus_dim_rects(self)
        except Exception:
            # **飾りの不具合で本文を隠さない。** ここで例外が出ると
            # `super().paintEvent()` に届かず、その領域が真っ白になる
            # （表が 2 つ見えると必ず起きていた。ユーザー報告）。
            # 握り潰さずログには残す
            logger.exception("装飾の組み立てに失敗した。本文だけ描く")
            decorations = []

        background = QPainter(self.viewport())
        painter_overlay.paint(background, decorations, self._theme)
        background.end()

        super().paintEvent(event)

        foreground = QPainter(self.viewport())
        painter_overlay.paint_foreground(foreground, decorations, self._theme, self.font())
        foreground.end()

    # ------------------------------------------------------------ 検索・置換

    def match_count(self, query: str, *, case_sensitive: bool = False) -> int:
        return len(search.find_all(self.toPlainText(), query, case_sensitive=case_sensitive))

    def find_text(
        self, query: str, *, backward: bool = False, case_sensitive: bool = False
    ) -> bool:
        """次（前）の一致を選択する。見つかったら True。

        **空振りではカーソルを動かさない。** 打ちかけの場所を見失うため。
        """
        cursor = self.textCursor()
        source = self.toPlainText()
        # カーソル位置は UTF-16 単位、`core/search` は Python 単位（🍎 = 1 文字）
        origin = utf16_to_py(source, cursor.selectionStart() if backward else cursor.selectionEnd())
        found = search.find_next(
            source, query, origin, backward=backward, case_sensitive=case_sensitive
        )
        if found is None:
            return False

        begin, end = found
        cursor.setPosition(py_to_utf16(source, begin))
        cursor.setPosition(py_to_utf16(source, end), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def replace_selection(
        self, query: str, replacement: str, *, case_sensitive: bool = False
    ) -> bool:
        """選択中の一致を置き換えて次へ進む。

        選択が一致していなければ**探すだけ**にする。何が置き換わるか
        見えていない状態で本文を書き換えない。
        """
        cursor = self.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        matches = selected == query or (
            not case_sensitive and selected.casefold() == query.casefold()
        )
        if not (query and matches):
            return self.find_text(query, case_sensitive=case_sensitive)

        cursor.insertText(replacement)
        self.find_text(query, case_sensitive=case_sensitive)
        return True

    def replace_all_text(
        self, query: str, replacement: str, *, case_sensitive: bool = False
    ) -> int:
        """すべての一致を置き換える。置き換えた件数を返す。

        **`setPlainText()` を使わない。** 文書を作り直すと Undo 履歴が消え、
        ハイライタの解析結果（`QTextBlockUserData`）も失われる。
        `QTextCursor` で編集し、`beginEditBlock()` で 1 段にまとめるので
        `Cmd+Z` 一回で元に戻る（R5 と同じ約束）。

        後ろから置き換える。前から書き換えると、以降の位置がずれる。
        """
        source = self.toPlainText()
        matches = search.find_all(source, query, case_sensitive=case_sensitive)
        if not matches:
            return 0

        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            # 後ろから置き換えるので、置き換え前のテキストで直した位置が
            # そのまま使える（編集は常に自分より後ろで起きている）
            for begin, end in reversed(matches):
                cursor.setPosition(py_to_utf16(source, begin))
                cursor.setPosition(py_to_utf16(source, end), QTextCursor.MoveMode.KeepAnchor)
                cursor.insertText(replacement)
        finally:
            cursor.endEditBlock()
        return len(matches)

    def set_search_highlights(self, query: str, *, case_sensitive: bool = False) -> None:
        """一致箇所すべてに下敷きを敷く。

        `extraSelections` は文書を書き換えないので、マーカーの隠蔽（R4）にも
        ブロックの解析結果にも触らない。空のクエリで消える。
        """
        source = self.toPlainText()
        matches = search.find_all(source, query, case_sensitive=case_sensitive)
        # ExtraSelection は QTextEdit 側に定義されている（QPlainTextEdit には無い）
        selections: list[QTextEdit.ExtraSelection] = []
        for begin, end in matches:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(self._theme.search_highlight))
            cursor = QTextCursor(self.document())
            cursor.setPosition(py_to_utf16(source, begin))
            cursor.setPosition(py_to_utf16(source, end), QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        self.setExtraSelections(selections)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_content_margins()
        self._update_table_columns()

    def table_columns(self) -> int:
        """表 1 行に使える桁数（半角換算）。**覚えた値を返すだけ**。

        `paintEvent` から毎回呼ばれるので、ここで測り直さない
        （`QFontMetricsF` を作るコストが描画のたびに乗る）。
        """
        return self._table_columns

    def _measure_table_columns(self) -> int:
        """今の幅とフォントで何桁入るか。

        表は `BIZ UDGothic` で描く。**全角は半角のちょうど 2 倍**（ADR-0003 の
        実測）なので、桁数で数えれば画面の幅と 1 対 1 で対応する。
        """
        available = self.viewport().width() - self.document().documentMargin() * 2
        font = QFont()
        font.setFamilies(TABLE_FAMILIES)
        font.setPointSizeF(self.font().pointSizeF())
        advance = QFontMetricsF(font).horizontalAdvance("0")
        if advance <= 0:
            return 0
        return int(available / advance)

    def _update_table_columns(self) -> None:
        """幅が変わったらハイライタへ伝え、表の行だけ掛け直す。

        **全体再ハイライトはしない**（R7）。`|` を含む行だけを見る。
        本文の大半は表ではないので、これで十分に安い。
        """
        columns = self._measure_table_columns()
        if columns == self._table_columns:
            return
        self._table_columns = columns
        self._highlighter.set_table_columns(columns)

        block = self.document().firstBlock()
        while block.isValid():
            if "|" in block.text():
                self._highlighter.rehighlightBlock(block)
            block = block.next()

    def content_margin(self) -> int:
        """本文の左右に入っている余白（px）。"""
        return self.viewportMargins().left()

    def _update_content_margins(self) -> None:
        """本文を中央寄せし、最大幅を超えないようにする（§5.1）。"""
        margin = max(0, (self.width() - self.MAX_CONTENT_WIDTH) // 2)
        current = self.viewportMargins()
        if current.left() == margin and current.right() == margin:
            return  # 同じ値を入れ直すと resize が再帰する
        self.setViewportMargins(margin, current.top(), margin, current.bottom())
