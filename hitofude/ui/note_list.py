"""ノート一覧（spec §5.1, §6.6）。

`QListWidget` は使わない（§6.6）。5,000 件のノートを扱うため、
行を widget として持つのではなくモデルから引く。

表示に必要な情報（タイトル・プレビュー・日付）は索引の `NoteRow` に
入っているので、**一覧を描くのにファイルを開かない**。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from hitofude.config import LineSpacing
from hitofude.storage.index_db import NoteRow
from hitofude.storage.vault import MARKDOWN_SUFFIXES
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.icons import Glyph, glyph_icon

# ドラッグで運ぶノートの合図。中身は vault からの相対パス（UTF-8）。
# 外のアプリへ渡すものではないので、独自の型で十分
NOTE_MIME = "application/x-hitofude-note"


def dropped_note(mime) -> Path | None:
    """ドラッグ中のノートの相対パス。ノートのドラッグでなければ None。"""
    if not mime.hasFormat(NOTE_MIME):
        return None
    raw = bytes(mime.data(NOTE_MIME)).decode("utf-8", errors="replace").strip()
    return Path(raw) if raw else None


def dropped_markdown(mime) -> list[Path]:
    """ドロップに含まれるローカルの `.md` を取り出す。

    一覧は「何が落ちてきたか」を知らせるだけで、vault へのコピーは
    MainWindow 側（NoteActions）の仕事。画像などは対象外
    （画像の受け口はエディタで、添付として保存される）。
    """
    if not mime.hasUrls():
        return []
    found: list[Path] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() in MARKDOWN_SUFFIXES and path.is_file():
            found.append(path)
    return found


# ピン留めの印。星は小さく出すので塗り潰す（輪郭だけだと形が読めない）
PIN_SIZE = 12
PIN_GAP = 5


class NoteRole(IntEnum):
    TITLE = int(Qt.ItemDataRole.UserRole) + 1
    PREVIEW = TITLE + 1
    DATE = TITLE + 2
    PATH = TITLE + 3
    PINNED = TITLE + 4
    FOLDER = TITLE + 5


def folder_label(path: Path) -> str:
    """行に添える置き場所（K-2）。保管フォルダ直下なら空。

    **直下は出さない。** ほとんどのノートが直下にあるので、全行に出すと
    目印にならないうえ、題名に使える幅を毎行削ることになる。

    **隠しフォルダも出さない**（コードレビュー指摘）。ゴミ箱の一覧は
    `.trash/名前.md` の相対パスで来るので、素通しにすると内部の
    ディレクトリ名が全行に描かれる。
    """
    parent = path.parent
    if parent == Path():
        return ""
    if parent.parts[0].startswith("."):
        # 隠しフォルダ自体は見せない。ただしゴミ箱（K-5 で階層を保つ）の
        # 中では**その先＝元の場所**が「戻る先」の案内になるので出す
        inner = parent.parts[1:]
        return "/".join(inner) if inner else ""
    return parent.as_posix()


def format_date(value: str) -> str:
    """ノート一覧に出す短い日付。

    今日なら時刻、今年なら月日、それ以前は年から。front matter は手で
    編集されうるので、読めない値は空文字にして落ちないようにする。
    """
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return ""

    now = datetime.now(moment.tzinfo)
    if moment.date() == now.date():
        return f"{moment.hour:02d}:{moment.minute:02d}"
    if moment.year == now.year:
        return f"{moment.month}/{moment.day}"
    return f"{moment.year}/{moment.month}/{moment.day}"


class NoteListModel(QAbstractListModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[NoteRow] = []
        self._folder_labels: list[str] = []

    def set_rows(self, rows: list[NoteRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        # 置き場所ラベルはここで 1 回だけ作る。data() は描画のたびに
        # 呼ばれるので、そこで pathlib を回すと行数 × 再描画ぶん無駄になる
        # （コードレビュー指摘）
        self._folder_labels = [folder_label(row.path) for row in rows]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        # Qt からは QModelIndex() が渡る。既定値に呼び出しを書けないので
        # None を受けて中で判定する

        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        row = self.note_at(index)
        if row is None:
            return None
        match role:
            case Qt.ItemDataRole.DisplayRole | NoteRole.TITLE:
                return row.title
            case NoteRole.PREVIEW:
                return row.preview
            case NoteRole.DATE:
                return format_date(row.modified_at)
            case NoteRole.PATH:
                return row.path
            case NoteRole.PINNED:
                return row.pinned
            case NoteRole.FOLDER:
                return self._folder_labels[index.row()]
            case _:
                return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """行はドラッグの元になる（フォルダへ移すため）。"""
        found = super().flags(index)
        if index.isValid():
            found |= Qt.ItemFlag.ItemIsDragEnabled
        return found

    def mimeTypes(self) -> list[str]:
        return [NOTE_MIME]

    def mimeData(self, indexes) -> QMimeData:
        """運ぶのは**場所だけ**。中身はドロップ先が索引とファイルから読む。"""
        mime = QMimeData()
        for index in indexes:
            row = self.note_at(index)
            if row is not None:
                mime.setData(NOTE_MIME, str(row.path).encode("utf-8"))
                break
        return mime

    def note_at(self, index: QModelIndex) -> NoteRow | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()]

    def index_of(self, path: Path) -> QModelIndex:
        """パスから行を引く。外部変更のあとで選択を保つのに使う。"""
        for number, row in enumerate(self._rows):
            if row.path == path:
                return self.index(number)
        return QModelIndex()


PREVIEW_MAX_LINES = 2

# 行と行のあいだの仕切り（ユーザー要望）。**太いと飾りに見える**ので 1px
SEPARATOR_HEIGHT = 1

# 置き場所と日付のあいだ。詰めると 1 つの語に見える
FOLDER_GAP = 8


@dataclass(frozen=True, slots=True)
class _Metrics:
    padding: int = 9
    """行の上下左右の余白。

    **拡大して並べて選んだ。** 12px は行間が空いて 1 画面に入る件数が減り、
    7px はタイトル同士が近すぎる。
    """
    spacing: int = 6
    """タイトルとプレビューの間。

    **ここを広げる（ユーザー指摘）。** 上下の余白（`padding`）は
    「拡大して選んだ」記録がある（12px だと 4 件目が画面外）ので動かさない。
    文字どうしの間だけ 4px → 6px にすると、1 行あたり 2px の増加で
    済みながら、題名と本文が別のものとして読める。
    """

    date_width: int = 48


# 環境設定の「行間」から引く値。**上下の余白は控えめに動かす。**
# 9px は「拡大して並べて選んだ」もので、12px にすると 4 件目が画面外に出る。
# ゆったりを選んだ人はそれを承知で選んでいるので、そこで初めて 12px にする
_SPACINGS = {
    LineSpacing.TIGHT: _Metrics(padding=7, spacing=4),
    LineSpacing.NORMAL: _Metrics(),
    LineSpacing.RELAXED: _Metrics(padding=12, spacing=8),
}


def metrics_for(spacing: LineSpacing) -> _Metrics:
    return _SPACINGS[spacing]


def preview_height(font: QFont, text: str, width: int) -> int:
    """プレビューに要る高さ。

    **`QFontMetrics.height()` で数えてはいけない。** 折り返しの組版は
    `lineSpacing()` で進む。Hiragino Sans 12pt は height 12 / lineSpacing 18 で、
    2 行だと 12px 足りず、実機でプレビューの 2 行目が切れていた。

    実際に折り返した行数で数えるので、**1 行しかないノートの行は低くなる**。
    常に 2 行ぶん取ると一覧がすかすかになる。長い本文は 2 行で止める。
    """
    if not text:
        return 0
    metrics = QFontMetrics(font)
    spacing = metrics.lineSpacing()
    needed = metrics.boundingRect(
        QRect(0, 0, max(width, 1), spacing * PREVIEW_MAX_LINES),
        int(Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
        text,
    ).height()
    lines = max(1, min(PREVIEW_MAX_LINES, round(needed / spacing)))
    return spacing * lines


class NoteItemDelegate(QStyledItemDelegate):
    """1 行に「タイトル / 日付 / プレビュー 2 行」を描く（spec §5.1）。"""

    def __init__(self, theme: ThemeColors = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._metrics = _Metrics()
        # 置き場所ラベルの省略計算のキャッシュ（コードレビュー指摘）。
        # paint は可視行 × 再描画のたびに呼ばれ、QFontMetrics の生成と
        # elidedText を毎回やると 16ms の描画予算に乗る。ラベルは
        # 数種類しか無いので、(ラベル, 上限幅) で覚えれば実質ゼロになる
        self._folder_cache: dict[tuple[str, int], tuple[str, int]] = {}
        self._folder_font_key: tuple[str, float] | None = None

    def _draw_separator(self, painter: QPainter, option, index: QModelIndex) -> None:
        """行の下に 1px の仕切り線を引く（ユーザー要望）。

        **いちばん下の行にも引く**（ユーザー要望 2026-08-18）。以前は
        「宙に浮いて見える」として最後だけ引いていなかったが、最後の
        ノートの領域がどこで終わるか分からない、という指摘で全行に揃えた。

        色は罫線（`theme.rule`）と同じ。同じ役目の線に色を増やさない。
        本文の左端に合わせて内側に寄せる（端まで引くと窓の枠に見える）。
        """
        inset = self._metrics.padding
        painter.fillRect(
            option.rect.left() + inset,
            option.rect.bottom() - SEPARATOR_HEIGHT + 1,
            option.rect.width() - inset * 2,
            SEPARATOR_HEIGHT,
            QColor(self._theme.rule),
        )

    def set_metrics(self, metrics: _Metrics) -> None:
        self._metrics = metrics

    def _elided_folder(self, folder: str, font, cap: int) -> tuple[str, int]:
        """置き場所ラベルの省略形と幅。同じ入力は計算し直さない。"""
        key = (font.family(), font.pointSizeF())
        if key != self._folder_font_key:
            self._folder_font_key = key
            self._folder_cache.clear()
        found = self._folder_cache.get((folder, cap))
        if found is None:
            metrics = QFontMetrics(font)
            limit = min(cap, metrics.horizontalAdvance(folder))
            elided = metrics.elidedText(folder, Qt.TextElideMode.ElideLeft, limit)
            found = (elided, metrics.horizontalAdvance(elided) + FOLDER_GAP)
            self._folder_cache[(folder, cap)] = found
        return found

    def set_theme(self, theme: ThemeColors) -> None:
        self._theme = theme

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """**本文で高さを変えない**（ユーザー報告）。

        `NoteListView` は `setUniformItemSizes(True)` で高さの計算を 1 回に
        まとめている（5,000 件で 29ms。行ごとに測ると 906ms かかり、一覧は
        保存のたびに引き直すので選べない）。ここが本文の行数で変わると、
        1 つの高さを全行に当てる前提と食い違い、**背の高い行に次の行が
        重なる**。実測では 70px 描く行に 34px しか割り当たっていなかった。

        プレビューが 1 行のノートには空きができるが、重なるよりはよい。
        """
        del index  # 高さは行の中身に依らない
        metrics = QFontMetrics(option.font)
        preview = metrics.lineSpacing() * PREVIEW_MAX_LINES
        height = self._metrics.padding * 2 + metrics.height() + self._metrics.spacing + preview
        return QSize(option.rect.width(), height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        self._draw_separator(painter, option, index)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, QColor(self._theme.selection_background))

        pad = self._metrics.padding
        body = option.rect.adjusted(pad, pad, -pad, -pad)

        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        line_height = QFontMetrics(title_font).height()

        date = index.data(NoteRole.DATE) or ""
        date_width = self._metrics.date_width if date else 0

        # 置き場所は日付の左隣。**題名を削り過ぎない**よう上限を設ける
        # （深い階層でも題名が読めるほうが大事）
        folder = index.data(NoteRole.FOLDER) or ""
        folder_width = 0
        if folder:
            folder, folder_width = self._elided_folder(folder, option.font, body.width() // 3)

        title_rect = QRect(
            body.left(), body.top(), body.width() - date_width - folder_width, line_height
        )

        painter.setPen(QColor(self._theme.foreground))
        if index.data(NoteRole.PINNED):
            star = glyph_icon(Glyph.PINNED, self._theme.pin_mark, filled=True)
            top = title_rect.top() + (line_height - PIN_SIZE) // 2
            painter.drawPixmap(
                QRect(title_rect.left(), top, PIN_SIZE, PIN_SIZE),
                star.pixmap(QSize(PIN_SIZE, PIN_SIZE)),
            )
            title_rect = title_rect.adjusted(PIN_SIZE + PIN_GAP, 0, 0, 0)

        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(title_font).elidedText(
                index.data(NoteRole.TITLE) or "", Qt.TextElideMode.ElideRight, title_rect.width()
            ),
        )

        painter.setFont(option.font)
        painter.setPen(QColor(self._theme.muted_foreground))
        if folder:
            painter.drawText(
                QRect(
                    body.right() - date_width - folder_width,
                    body.top(),
                    folder_width - FOLDER_GAP,
                    line_height,
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                folder,
            )
        if date:
            painter.drawText(
                QRect(body.right() - date_width, body.top(), date_width, line_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                date,
            )

        preview_rect = QRect(
            body.left(),
            body.top() + line_height + self._metrics.spacing,
            body.width(),
            preview_height(option.font, index.data(NoteRole.PREVIEW) or "", body.width()),
        )
        painter.drawText(
            preview_rect,
            Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            index.data(NoteRole.PREVIEW) or "",
        )
        painter.restore()


class NoteListView(QListView):
    note_activated = Signal(object)
    """選択されたノートの `Path`。"""

    files_dropped = Signal(list)
    """ドロップされた `.md` の `list[Path]`（ユーザー要望 2026-08-18）。
    取り込み（vault へのコピー）は MainWindow の仕事。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        # setModel() の途中で currentChanged が呼ばれるので、
        # ガードは何よりも先に用意しておく
        self._suppress_activation = False
        self._model = NoteListModel(self)
        self._delegate = NoteItemDelegate(theme, self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.setUniformItemSizes(True)  # 5,000 件でも高さ計算を 1 回で済ませる
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setAcceptDrops(True)
        # 行をつまんでサイドバーのフォルダへ落とせるようにする（ユーザー要望）。
        # 受けるほうは `.md` の取り込みだけで、一覧の中での並べ替えはしない
        self.setDragEnabled(True)
        self.setDragDropMode(QListView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    # ------------------------------------------------- ドラッグ＆ドロップ

    def dragEnterEvent(self, event) -> None:
        if dropped_markdown(event.mimeData()):
            event.acceptProposedAction()
            return
        if dropped_note(event.mimeData()) is not None:
            # 自分から出たノート。一覧の中に落としても行き先が無い
            event.ignore()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if dropped_markdown(event.mimeData()):
            event.acceptProposedAction()
            return
        if dropped_note(event.mimeData()) is not None:
            # 自分から出たノート。一覧の中に落としても行き先が無い
            event.ignore()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        found = dropped_markdown(event.mimeData())
        if not found:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        self.files_dropped.emit(found)

    def set_line_spacing(self, spacing: LineSpacing) -> None:
        """行間を変える（環境設定）。

        `setUniformItemSizes(True)` は高さを 1 度だけ測って全行に当てる。
        **測り直させないと古い高さのまま**なので、明示的に組み直す。
        """
        self._delegate.set_metrics(metrics_for(spacing))
        self.reset()

    def set_rows(self, rows: list[NoteRow]) -> None:
        current = self.current_path()
        self._model.set_rows(rows)
        if current is not None:
            self.select_path(current)

    def set_theme(self, theme: ThemeColors) -> None:
        self._delegate.set_theme(theme)
        self.viewport().update()

    def has_path(self, path: Path) -> bool:
        """その行が今の一覧にあるか。**絞り込みで見えているか**の判定に使う。"""
        return self._model.index_of(path).isValid()

    def current_path(self) -> Path | None:
        row = self._model.note_at(self.currentIndex())
        return row.path if row is not None else None

    def select_path(self, path: Path, *, notify: bool = False) -> None:
        """選択を移す。

        既定では `note_activated` を出さない。一覧の更新（`set_rows`）でも
        選択をやり直すため、ここで通知すると**更新のたびにノートが開き直され**、
        保存や競合ダイアログまで連鎖する。ユーザーの操作による選択だけが
        ノートを開くべき。
        """
        index = self._model.index_of(path)
        if not index.isValid():
            return
        self._suppress_activation = not notify
        try:
            self.setCurrentIndex(index)
        finally:
            self._suppress_activation = False

    def currentChanged(self, current: QModelIndex, previous: QModelIndex) -> None:
        super().currentChanged(current, previous)
        if self._suppress_activation:
            return
        row = self._model.note_at(current)
        if row is not None:
            self.note_activated.emit(row.path)
