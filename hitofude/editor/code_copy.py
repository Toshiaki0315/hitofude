"""コードブロックのコピーボタン（ユーザー要望 2026-08-27 / Qiita 風）。

コードの上にマウスが来たら帯の右上に写しの印を浮かせ、押すと
**フェンスを除いた中身**をクリップボードへ入れる。ソースには触らない。

置き場は帯（`painter_overlay` の CODE_BACKGROUND）の右上。スクロールや
編集で控えた位置が古くなったら隠すだけ——次にマウスが動けば出直すので、
追いかけて動かす仕掛けは要らない。
"""

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QTextBlock
from PySide6.QtWidgets import QApplication, QToolButton

from hitofude.core.models import BlockType
from hitofude.editor.painter_overlay import BAND_MARGIN, band_top
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.icons import Glyph, glyph_icon

BUTTON_SIZE = 26
ICON_SIZE = 16
PAD = 5.0
"""帯の縁からの離し。"""

COPIED_MS = 1200
"""押したあとチェックの印を見せる長さ。"""

_FENCES = frozenset(
    {BlockType.CODE_FENCE_OPEN, BlockType.CODE_FENCE_BODY, BlockType.CODE_FENCE_CLOSE}
)


def _block_type(block: QTextBlock):
    data = block.userData()
    return data.info.type if data is not None else None


class CodeCopyButton(QObject):
    """マウスの位置を受け取って、出す・隠す・コピーするだけの係。"""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self._editor = editor
        self._theme: ThemeColors = LIGHT
        self._run: tuple[int, int] | None = None
        """今出している帯のコードの行範囲 `[開始, 終了]`（フェンス込み）。"""

        self._button = QToolButton(editor.viewport())
        self._button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self._button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._button.setToolTip("コードをコピー")
        self._button.setAccessibleName("コードをコピー")
        self._button.hide()
        self._button.clicked.connect(self._copy)

        self._revert = QTimer(self)
        self._revert.setSingleShot(True)
        self._revert.setInterval(COPIED_MS)
        self._revert.timeout.connect(self._apply_icon)

        # 行番号が動くと控えた範囲が古くなる。隠すだけ——次の hover で出直す
        editor.textChanged.connect(self.hide)
        editor.verticalScrollBar().valueChanged.connect(self.hide)
        self._apply_style()

    @property
    def button(self) -> QToolButton:
        return self._button

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme
        self._apply_style()

    # ------------------------------------------------------------------ 表示

    def update(self, pos: QPoint) -> None:
        """マウスの位置から、出すか隠すかを決める（mouseMoveEvent から）。"""
        if self._editor.highlighter.source_mode:
            # Raw では出さない（ユーザー要望 2026-08-28）。記号を直に触る
            # モードで飾りは一切描かないので、帯が無いのに印だけ浮くと
            # 何に付いた印なのか分からない
            self.hide()
            return
        block = self._block_at(pos)
        if block is None or _block_type(block) not in _FENCES:
            self.hide()
            return
        start, end = self._run_of(block)
        if self._run == (start, end) and self._button.isVisible():
            return
        self._run = (start, end)
        self._place(start)

    def hide(self) -> None:
        self._run = None
        self._button.hide()

    def _block_at(self, pos: QPoint) -> QTextBlock | None:
        """位置のブロック。**行の外なら None**（cursorForPosition は
        いちばん近い行へ丸めるので、下の余白までコード扱いになる）。"""
        cursor = self._editor.cursorForPosition(pos)
        block = cursor.block()
        geometry = self._editor.blockBoundingGeometry(block).translated(
            self._editor.contentOffset()
        )
        if not (geometry.top() <= pos.y() <= geometry.bottom()):
            return None
        return block

    def _run_of(self, block: QTextBlock) -> tuple[int, int]:
        """ブロックが属するフェンスの範囲 `[開始, 終了]`。

        型だけで歩くと、隣り合う 2 つのフェンスがつながる。上へは
        開きに当たるまで、下へは閉じに当たるまで歩く。
        """
        start = block
        while _block_type(start) is not BlockType.CODE_FENCE_OPEN:
            probe = start.previous()
            if not probe.isValid() or _block_type(probe) not in _FENCES:
                break
            if _block_type(probe) is BlockType.CODE_FENCE_CLOSE:
                break
            start = probe
        end = block
        while _block_type(end) is not BlockType.CODE_FENCE_CLOSE:
            probe = end.next()
            if not probe.isValid() or _block_type(probe) not in _FENCES:
                break
            if _block_type(probe) is BlockType.CODE_FENCE_OPEN:
                break
            end = probe
        return start.blockNumber(), end.blockNumber()

    def _place(self, start_line: int) -> None:
        block = self._editor.document().findBlockByNumber(start_line)
        # **帯の上端に合わせる**（行の上端ではない）。字下げのコードには
        # 縁の行が無く、帯だけが上へ伸びるので、行に合わせると印が下がる
        top = band_top(self._editor, block)
        band_right = self._editor.viewport().width() - BAND_MARGIN
        self._button.move(round(band_right - PAD - BUTTON_SIZE), round(top + PAD))
        self._button.show()
        self._button.raise_()

    # ---------------------------------------------------------------- コピー

    def _copy(self) -> None:
        if self._run is None:
            return
        start, end = self._run
        document = self._editor.document()
        lines: list[str] = []
        for number in range(start, end + 1):
            block = document.findBlockByNumber(number)
            if block.isValid() and _block_type(block) is BlockType.CODE_FENCE_BODY:
                lines.append(block.text())
        QApplication.clipboard().setText("\n".join(lines) + "\n" if lines else "")
        # できた合図。印を一瞬チェックに替える（文字を選ばず音も出さない）
        self._button.setIcon(glyph_icon(Glyph.CHECK, self._theme.note_info))
        self._revert.start()

    # ---------------------------------------------------------------- 見た目

    def _apply_icon(self) -> None:
        self._button.setIcon(glyph_icon(Glyph.COPY, self._theme.muted_foreground))

    def _apply_style(self) -> None:
        self._apply_icon()
        # 帯（コードの背景）の上に載るので、下地は付けず印だけ。
        # 触ったときだけ薄く受ける
        self._button.setStyleSheet(
            "QToolButton { border: none; background: transparent; }"
            f"QToolButton:hover {{ background: {self._theme.selection_background};"
            " border-radius: 4px; }"
        )
