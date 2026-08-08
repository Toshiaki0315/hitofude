"""ライブプレビュー付きのテキスト編集ウィジェット（spec §4.1, §5.1, §6.4）。

`QPlainTextEdit` を選んだ理由と、`QTextEdit` へ移る可能性については §4.1。
**基底クラスへの依存はこのクラスに閉じ込める**。後で差し替えるときの
コストを下げるため、他のモジュールから `QPlainTextEdit` を直接触らない。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QInputMethodEvent,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
    QTextBlock,
    QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from hitofude.core.models import BlockInfo
from hitofude.editor import commands, painter_overlay
from hitofude.editor.highlighter import MarkdownHighlighter
from hitofude.editor.input_handler import EnterKind, enter_action, indent_action
from hitofude.theme import LIGHT, ThemeColors

DEFAULT_FONT_FAMILY = "Hiragino Sans"
DEFAULT_POINT_SIZE = 15.0


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

        font = QFont(font_family)
        font.setPointSizeF(base_point_size)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setTabChangesFocus(False)

        self._highlighter = MarkdownHighlighter(
            self.document(), theme, base_point_size=base_point_size
        )

        # リビールで掛け直す「旧ブロック」を覚えておく（R7）
        self._last_block = 0
        self._last_selection: tuple[int, int] | None = None
        # rehighlightBlock() は selectionChanged を再発火させる。
        # ガードが無いと _sync_reveal が自分自身を呼び続けて再帰で落ちる。
        self._syncing = False
        # IME のプリエディット中かどうか（R6）
        self._composing = False

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

    def set_font_family(self, family: str) -> None:
        font = self.font()
        font.setFamily(family)
        self.setFont(font)

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

        super().keyPressEvent(event)

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

    def insertFromMimeData(self, source) -> None:
        """選択があってクリップボードが URL ならリンクにする（spec §5.5-5）。"""
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

        background = QPainter(self.viewport())
        painter_overlay.paint(background, decorations, self._theme)
        background.end()

        super().paintEvent(event)

        foreground = QPainter(self.viewport())
        painter_overlay.paint_foreground(foreground, decorations, self._theme, self.font())
        foreground.end()

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
