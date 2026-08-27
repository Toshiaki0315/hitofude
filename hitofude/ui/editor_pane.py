"""エディタと検索バーをまとめた 3 ペイン目。

検索バーはエディタの上に積む。`MarkdownEditor` の中に浮かせると、
本文の余白計算（`_update_content_margins`）や `paintEvent` の装飾と
座標を取り合うことになる。レイアウトに任せれば衝突しない。
"""

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from hitofude.editor.editor_widget import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_POINT_SIZE,
    MarkdownEditor,
)
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.backlink_bar import BacklinkBar
from hitofude.ui.find_bar import FindBar
from hitofude.ui.format_toolbar import FormatToolbar
from hitofude.ui.icons import Glyph, glyph_icon

# お気に入りの星（ユーザー要望 2026-08-27 / Qiita 風）。本文の左の
# 沈んだ領域に浮かせる。大きめ——遠目にも入り切りが分かる的
FAVORITE_BUTTON_SIZE = 48
FAVORITE_ICON_SIZE = 34
FAVORITE_GAP = 16
"""星と紙（本文の左端）の間。**幅の設定（標準 / 広め）によらず一定**
（ユーザー要望 2026-08-27）。領域の真ん中に置くと、幅の設定で星が
泳いで見える。"""

FAVORITE_TOP = 16
"""本文の上端（documentMargin ぶん下がった 1 行目）に目線が揃う高さ。"""


class EditorPane(QWidget):
    favorite_toggled = Signal()
    """お気に入りの星を押された。**切り替えるのは呼び出し側**
    （ここはノートを知らない。アウトラインのボタンと同じ形）。"""

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

        # お気に入りの星（ユーザー要望 2026-08-27 / Qiita 風）。エディタの
        # 子として浮かせ、本文の左の沈んだ領域（幅を絞ったときの余白）に置く
        self._theme = theme
        self._favorite = QToolButton(self._editor)
        self._favorite.setCheckable(True)
        self._favorite.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._favorite.setFixedSize(FAVORITE_BUTTON_SIZE, FAVORITE_BUTTON_SIZE)
        self._favorite.setIconSize(QSize(FAVORITE_ICON_SIZE, FAVORITE_ICON_SIZE))
        self._favorite.setAccessibleName("お気に入り")
        self._favorite.setToolTip("お気に入り（⇧⌘P）")
        self._favorite.setStyleSheet("QToolButton { border: none; background: transparent; }")
        self._favorite.toggled.connect(lambda _on: self._apply_favorite_icon())
        self._favorite.clicked.connect(lambda _checked: self.favorite_toggled.emit())
        self._favorite_allowed = False
        """ノートが開いているか。場所の有無（沈んだ領域）とは別の条件。"""
        self._favorite.hide()
        self._apply_favorite_icon()
        # 置き直しはエディタの大きさが決まってから。resize の**あと**に
        # 走らせる（余白 setViewportMargins は resize の中で確定する）
        self._editor.installEventFilter(_Relayout(self, self._reposition_favorite))

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

    @property
    def favorite_button(self) -> QToolButton:
        return self._favorite

    # ------------------------------------------------------------ お気に入り

    def set_favorite(self, on: bool) -> None:
        """星の塗りを状態に合わせる（押した通知は出さない）。"""
        self._favorite.blockSignals(True)
        self._favorite.setChecked(on)
        self._favorite.blockSignals(False)
        self._apply_favorite_icon()

    def favorite_visible(self) -> bool:
        """出す意思があるか（ノートが開いているか）。

        **`isVisible()` では答えられない**（`toolbar_visible` と同じ罠）。
        実際に見えるかは場所（左の沈んだ領域の幅）しだい。
        """
        return self._favorite_allowed

    def set_favorite_visible(self, visible: bool) -> None:
        """ノートが開いているときだけ出す。実際に見えるかは場所しだい。"""
        self._favorite_allowed = visible
        self._reposition_favorite()

    def _apply_favorite_icon(self) -> None:
        if self._favorite.isChecked():
            # 一覧の星（note_list）と同じ金色・塗り潰し
            self._favorite.setIcon(glyph_icon(Glyph.PINNED, self._theme.pin_mark, filled=True))
        else:
            self._favorite.setIcon(glyph_icon(Glyph.PINNED, self._theme.muted_foreground))

    def _reposition_favorite(self) -> None:
        """左の沈んだ領域の真ん中に置く。領域が狭ければ隠す。

        本文に重ねると開閉三角（左余白のクリックで開閉）と取り合いに
        なるので、**置き場が無いときは出さない**。メニューと ⇧⌘P は
        いつでも効く。
        """
        margin = self._editor.viewportMargins().left()
        # **紙に寄せる**（ユーザー要望 2026-08-27）。間隔は幅の設定
        # （標準 / 広め）によらず FAVORITE_GAP で一定。全幅（余白 0）や
        # 置き場が足りない窓では出さない
        x = margin - FAVORITE_GAP - FAVORITE_BUTTON_SIZE
        if not (self._favorite_allowed and x >= 0):
            self._favorite.hide()
            return
        self._favorite.move(x, FAVORITE_TOP)
        self._favorite.show()
        self._favorite.raise_()

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


class _Relayout(QObject):
    """エディタの大きさが変わったら置き直す。

    余白（setViewportMargins）は resize の処理の中で確定するので、
    **一拍あと**（イベントループ経由）に読む。
    """

    def __init__(self, parent: QObject, reposition) -> None:
        super().__init__(parent)
        self._reposition = reposition

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._reposition)
        return False
