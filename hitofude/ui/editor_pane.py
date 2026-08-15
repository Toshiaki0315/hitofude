"""エディタと検索バーをまとめた 3 ペイン目。

検索バーはエディタの上に積む。`MarkdownEditor` の中に浮かせると、
本文の余白計算（`_update_content_margins`）や `paintEvent` の装飾と
座標を取り合うことになる。レイアウトに任せれば衝突しない。
"""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from hitofude.editor.editor_widget import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_POINT_SIZE,
    MarkdownEditor,
)
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.backlink_bar import BacklinkBar
from hitofude.ui.find_bar import FindBar
from hitofude.ui.format_toolbar import FormatToolbar


class EditorPane(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        theme: ThemeColors = LIGHT,
        font_family: str = DEFAULT_FONT_FAMILY,
        base_point_size: float = DEFAULT_POINT_SIZE,
    ) -> None:
        super().__init__(parent)
        self._editor = MarkdownEditor(
            theme=theme, font_family=font_family, base_point_size=base_point_size
        )
        self._find = FindBar(theme=theme)
        self._find.hide()
        self._toolbar = FormatToolbar(self._editor, theme=theme)
        # **本文の下**（ADR-0011）。0 件のノートでは自分で隠れる
        self._backlinks = BacklinkBar(theme=theme)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # ツールバーは検索バーより上。押す頻度が高いものほど動かない位置に置く
        layout.addWidget(self._toolbar)
        layout.addWidget(self._find)
        layout.addWidget(self._editor, 1)
        layout.addWidget(self._backlinks)

        self._find.query_changed.connect(self._on_query_changed)
        self._find.find_requested.connect(self._on_find)
        self._find.replace_requested.connect(self._on_replace)
        self._find.replace_all_requested.connect(self._on_replace_all)
        self._find.dismissed.connect(self.close_find)

    # ------------------------------------------------------------------ 参照

    @property
    def editor(self) -> MarkdownEditor:
        return self._editor

    @property
    def find_bar(self) -> FindBar:
        return self._find

    @property
    def toolbar(self) -> FormatToolbar:
        return self._toolbar

    @property
    def backlinks(self) -> BacklinkBar:
        return self._backlinks

    # ------------------------------------------------------------------ 操作

    def open_find(self) -> None:
        selected = self._editor.textCursor().selectedText().replace(" ", "\n")
        self._find.open_with(selected)
        self._on_query_changed(self._find.query)

    def close_find(self) -> None:
        """バーを閉じる。**強調も一緒に消す。**

        閉じたのに下敷きが残っていると、本文の一部が装飾されているように
        見えてしまう。
        """
        self._find.hide()
        self._editor.set_search_highlights("")
        self._editor.setFocus()

    def refresh_highlights(self) -> None:
        """本文が入れ替わったあとに強調を掛け直す。

        `setPlainText()` で文書ごと差し替わると、`extraSelections` が
        指していた位置は別の文字を指す。ノートを切り替えたのに前のノートの
        検索結果が光ったままにならないよう、開き直すたびに引き直す。
        """
        self._on_query_changed(self._find.query if self._find.isVisible() else "")

    def find_again(self, *, backward: bool = False) -> None:
        """バーを開かずに次（前）を探す（`Cmd+G`）。"""
        if self._find.query:
            self._on_find(self._find.query, backward)

    def set_toolbar_visible(self, visible: bool) -> None:
        self._toolbar.setVisible(visible)

    def toolbar_visible(self) -> bool:
        """隠す意思があるか。

        **`isVisible()` では答えられない。** ウィンドウを出す前とウィンドウを
        隠している間は、隠していなくても False になる（`ui/panes.py` と同じ罠）。
        """
        return not self._toolbar.isHidden()

    def set_theme(self, theme: ThemeColors) -> None:
        self._editor.set_theme(theme)
        self._find.set_theme(theme)
        self._toolbar.set_theme(theme)
        self._backlinks.set_theme(theme)

    # ------------------------------------------------------------------ 連携

    def _on_query_changed(self, query: str) -> None:
        sensitive = self._find.case_sensitive
        self._editor.set_search_highlights(query, case_sensitive=sensitive)
        self._find.set_status(self._editor.match_count(query, case_sensitive=sensitive))

    def _on_find(self, query: str, backward: bool) -> None:
        self._editor.find_text(query, backward=backward, case_sensitive=self._find.case_sensitive)

    def _on_replace(self, query: str, replacement: str) -> None:
        self._editor.replace_selection(query, replacement, case_sensitive=self._find.case_sensitive)
        self._on_query_changed(query)

    def _on_replace_all(self, query: str, replacement: str) -> None:
        self._editor.replace_all_text(query, replacement, case_sensitive=self._find.case_sensitive)
        self._on_query_changed(query)
