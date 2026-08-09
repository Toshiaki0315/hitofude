"""ライブプレビュー付きのテキスト編集ウィジェット（spec §4.1, §5.1, §6.4）。

`QPlainTextEdit` を選んだ理由と、`QTextEdit` へ移る可能性については §4.1。
**基底クラスへの依存はこのクラスに閉じ込める**。後で差し替えるときの
コストを下げるため、他のモジュールから `QPlainTextEdit` を直接触らない。
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
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
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from hitofude.core import frontmatter, search
from hitofude.core.document import plain_text
from hitofude.core.models import BlockInfo
from hitofude.editor import attachments, commands, painter_overlay, table
from hitofude.editor.highlighter import MarkdownHighlighter
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

logger = logging.getLogger(__name__)


def _modifies_text(event: QKeyEvent) -> bool:
    """その打鍵が本文を書き換えるか。"""
    if event.key() in _EDITING_KEYS:
        return True
    return bool(event.text()) and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)


class MarkdownEditor(QPlainTextEdit):
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

        font = QFont(font_family)
        font.setPointSizeF(base_point_size)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setTabChangesFocus(False)

        self._images = ImageCache()
        self._highlighter = MarkdownHighlighter(
            self.document(), theme, base_point_size=base_point_size
        )
        self._highlighter.set_image_source(self._images, self.image_width())

        # リビールで掛け直す「旧ブロック」を覚えておく（R7）
        self._last_block = 0
        self._last_selection: tuple[int, int] | None = None
        # rehighlightBlock() は selectionChanged を再発火させる。
        # ガードが無いと _sync_reveal が自分自身を呼び続けて再帰で落ちる。
        self._syncing = False
        # IME のプリエディット中かどうか（R6）
        self._composing = False
        self._focus_mode = False
        self._typewriter_mode = False
        # 整形が走っている最中に自分自身を呼ばないためのガード
        self._formatting = False

        self.cursorPositionChanged.connect(self._sync_reveal)
        self.selectionChanged.connect(self._sync_reveal)

        self._apply_palette()
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

    def toggle_source_mode(self) -> None:
        self.set_source_mode(not self._highlighter.source_mode)

    # --------------------------------------------------- 執筆用のモード（§5.4）

    def set_focus_mode(self, enabled: bool) -> None:
        """`Cmd+Shift+D`。現在段落以外を減光する。"""
        self._focus_mode = enabled
        self.viewport().update()

    def toggle_focus_mode(self) -> None:
        self.set_focus_mode(not self._focus_mode)

    @property
    def focus_mode(self) -> bool:
        return self._focus_mode

    def set_typewriter_mode(self, enabled: bool) -> None:
        """`Cmd+Shift+Y`。キャレット行を画面中央に保つ。"""
        self._typewriter_mode = enabled
        if enabled:
            self._center_caret()

    def toggle_typewriter_mode(self) -> None:
        self.set_typewriter_mode(not self._typewriter_mode)

    @property
    def typewriter_mode(self) -> bool:
        return self._typewriter_mode

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

    def set_font_family(self, family: str) -> None:
        font = self.font()
        font.setFamily(family)
        self.setFont(font)

    def set_mono_family(self, family: str) -> None:
        self._highlighter.set_mono_family(family)

    def format_table(self) -> bool:
        """キャレットのある表の縦線を揃える（spec §1.2）。

        WYSIWYG な表エディタは作らない代わりに、ソースを整えて等幅で見せる。
        日本語は全角 2 桁で数えるので、文字数ではなく表示幅で揃う。
        """
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
        """入力補助を差し込む（spec §5.5）。

        **変換中は特殊処理をすべて無効化する（R6）。** 日本語変換の確定 Enter を
        リスト継続と取り違えると、確定のたびに項目が増えて日本語入力が破綻する。
        仕様書が「ここを怠ると壊滅的」と名指ししている箇所。
        """
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
        offset = frontmatter.body_offset(self.toPlainText())
        if offset == 0:
            return False

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
        if not command:
            return False

        key = event.key()
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
                case Qt.Key.Key_Up:
                    return self.shift_heading(-1)
                case Qt.Key.Key_Down:
                    return self.shift_heading(1)
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
        cursor = self.textCursor()
        replacement = commands.toggle_wrap(
            self.toPlainText(), cursor.selectionStart(), cursor.selectionEnd(), marker
        )
        self._apply(replacement)
        return True

    def insert_link(self, url: str = "") -> bool:
        """`Cmd+K`。選択文字を `[選択](url)` にする（spec §5.4）。"""
        cursor = self.textCursor()
        replacement = commands.insert_link(
            self.toPlainText(), cursor.selectionStart(), cursor.selectionEnd(), url
        )
        self._apply(replacement)
        return True

    def shift_heading(self, delta: int) -> bool:
        """見出しレベルの増減。`delta` が負だと `#` が減って見出しが大きくなる。"""
        block = self.textCursor().block()
        new_line = commands.shift_heading(block.text(), delta)
        if new_line is None:
            return False
        self._replace_current_block(new_line)
        return True

    def toggle_checkbox(self) -> bool:
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
        self._highlighter.rehighlight()

    def refresh_images(self) -> None:
        """外で画像が差し替わったときに読み直す。"""
        self._images.clear()
        self._highlighter.rehighlight()

    # ------------------------------------------------------------------ 添付

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
        offset = frontmatter.body_offset(self.toPlainText())
        if offset == 0:
            super().selectAll()
            return

        cursor = self.textCursor()
        cursor.setPosition(offset)
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
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(replacement.start)
        cursor.setPosition(replacement.end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement.text)
        cursor.endEditBlock()
        cursor.setPosition(replacement.select_start)
        cursor.setPosition(replacement.select_end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _replace_current_block(self, text: str) -> None:
        cursor = self.textCursor()
        column = cursor.positionInBlock() + len(text) - len(cursor.block().text())
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
        action = enter_action(block.text(), cursor.positionInBlock(), self._current_info())

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
        column = max(0, cursor.positionInBlock() + shift)
        self._replace_block(cursor, new_line, column=column)
        self.setTextCursor(cursor)
        return True

    def _replace_block(self, cursor: QTextCursor, text: str, *, column: int) -> None:
        """現在行の中身を差し替える。Undo は 1 手にまとめる。"""
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        cursor.endEditBlock()
        cursor.setPosition(cursor.block().position() + min(column, len(text)))

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
        「選択範囲に交差するブロックは全表示」（§6.4）を満たすため、
        旧選択と新選択の和集合にかかるブロックを対象にする。
        """
        document = self.document()
        numbers: set[int] = {self._last_block, current_block}

        for span in (self._last_selection, selection):
            if span is None:
                continue
            start_block = document.findBlock(span[0]).blockNumber()
            end_block = document.findBlock(span[1]).blockNumber()
            numbers.update(range(start_block, end_block + 1))

        blocks = []
        for number in sorted(numbers):
            block = document.findBlockByNumber(number)
            if block.isValid():
                blocks.append(block)
        return blocks

    # ----------------------------------------------------------- レイアウト

    def paintEvent(self, event: QPaintEvent) -> None:
        """本文の下に背景要素を、上にチェックボックス記号を描く（§5.2, ADR-0002）。

        ブロック書式が使えないため、引用の縦バーもコードの背景も水平線も
        ここでしか描けない。順序が重要で、背景は `super()` の前、
        本文に重ねる記号は後に描く。
        """
        decorations = painter_overlay.visible_decorations(self)
        if self._focus_mode:
            decorations = decorations + painter_overlay.focus_dim_rects(self)

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
        origin = cursor.selectionStart() if backward else cursor.selectionEnd()
        found = search.find_next(
            self.toPlainText(), query, origin, backward=backward, case_sensitive=case_sensitive
        )
        if found is None:
            return False

        begin, end = found
        cursor.setPosition(begin)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
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
        matches = search.find_all(self.toPlainText(), query, case_sensitive=case_sensitive)
        if not matches:
            return 0

        cursor = self.textCursor()
        cursor.beginEditBlock()
        try:
            for begin, end in reversed(matches):
                cursor.setPosition(begin)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cursor.insertText(replacement)
        finally:
            cursor.endEditBlock()
        return len(matches)

    def set_search_highlights(self, query: str, *, case_sensitive: bool = False) -> None:
        """一致箇所すべてに下敷きを敷く。

        `extraSelections` は文書を書き換えないので、マーカーの隠蔽（R4）にも
        ブロックの解析結果にも触らない。空のクエリで消える。
        """
        matches = search.find_all(self.toPlainText(), query, case_sensitive=case_sensitive)
        # ExtraSelection は QTextEdit 側に定義されている（QPlainTextEdit には無い）
        selections: list[QTextEdit.ExtraSelection] = []
        for begin, end in matches:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(self._theme.search_highlight))
            cursor = QTextCursor(self.document())
            cursor.setPosition(begin)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        self.setExtraSelections(selections)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_content_margins()

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
