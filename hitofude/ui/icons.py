"""サイドバーのアイコンを線で描く。あわせて、上部のバーの倍率を置く。

**絵文字も画像ファイルも使わない。** 絵文字は色を指定できずテーマから浮き、
画像ファイルはライト / ダーク × 解像度のぶんだけ用意することになる。
線で描けば色を渡すだけで済み、`scripts/make_icon.py`（アプリアイコン）と
同じやり方に揃う。

既定は輪郭だけで塗り潰さない。文字と同じ太さに見えるほうが、一覧として
落ち着く。小さく出す印（一覧のピン留め）だけ `filled=True` で中まで塗る。
輪郭だけでは形が読めないため。
"""

import functools
from enum import Enum, auto
from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

from hitofude import APP_NAME

# 上部のバー（一覧の並び順・新規、本文の書式ツールバー）の倍率。
# **1 か所に持つ。** 各ファイルに数字を散らすと、直すときに片方だけ残る。
# 1.0 が元の大きさ（ユーザー要望で 1.5 倍を試し、1.3 に落ち着いた）
TOOLBAR_SCALE = 1.3

# 描画は倍率をかけた大きさ（CANVAS）で行い、表示側で縮小する。線が滑らかになる
CANVAS = 64
STROKE = 5.0
_CACHE: dict[tuple["Glyph", str, bool], QIcon] = {}


class Glyph(Enum):
    ALL = auto()
    """すべて。重なった紙。"""

    PINNED = auto()
    """お気に入り。星。"""

    TRASH = auto()
    """ゴミ箱。"""

    TAG = auto()
    """タグ。"""

    FOLDER = auto()
    """サブフォルダ（K-2）。**タグと見分けが付く形**にする。"""

    SEARCH = auto()
    """保存した検索（K-4）。虫めがね。"""

    # ------------------------------------------------- 一覧の上のボタン

    SORT = auto()
    """並び順。上下の矢印。"""

    NEW_NOTE = auto()
    """新規ノート。＋。"""

    OUTLINE = auto()
    """アウトライン。**段差の付いた行**で入れ子を表す。"""

    CLOSE = auto()
    """閉じる（×）。枠の無い窓には OS の閉じるボタンが無い。"""

    GEAR = auto()
    """メニュー。歯車。"""

    # ------------------------------------------- 書式ツールバー（B-1）

    BOLD = auto()
    """太字。"""

    ITALIC = auto()
    """斜体。"""

    STRIKE = auto()
    """打ち消し。"""

    CODE = auto()
    """コード。山括弧。"""

    MARKER = auto()
    """マーカー。引いた線。"""

    LINK = auto()
    """リンク。鎖の輪。"""

    HEADING = auto()
    """見出し。"""

    BULLET = auto()
    """箇条書き。点と行。"""

    ORDERED = auto()
    """番号付き。数字と行。"""

    CHECKBOX = auto()
    """チェックボックス。"""

    QUOTE = auto()
    """引用。縦線と行。本文での見え方（`painter_overlay`）に合わせる。"""


def glyph_icon(glyph: Glyph, color: str, *, filled: bool = False) -> QIcon:
    """線で描いたアイコン。同じ指定なら描き直さない。

    `filled` は中まで塗る。小さく出すときは輪郭だけだと形が読めない
    （一覧のピン留めの印がそれ）。
    """
    key = (glyph, color, filled)
    found = _CACHE.get(key)
    if found is not None:
        return found

    pixmap = QPixmap(CANVAS, CANVAS)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(STROKE)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(color)) if filled else Qt.BrushStyle.NoBrush)

    _DRAW[glyph](painter)
    painter.end()

    icon = QIcon(pixmap)
    _CACHE[key] = icon
    return icon


def _draw_all(painter: QPainter) -> None:
    """重なった紙。"""
    painter.drawRect(QRectF(10, 18, 32, 38))
    painter.drawPolyline(
        [QPointF(22, 10), QPointF(54, 10), QPointF(54, 46)]  # 後ろの 1 枚
    )


def _draw_pinned(painter: QPainter) -> None:
    """星。5 つの頂点を外周と内周で交互に結ぶ。"""
    import math

    center = QPointF(32, 33)
    outer, inner = 22.0, 9.0
    path = QPainterPath()
    for step in range(10):
        radius = outer if step % 2 == 0 else inner
        angle = math.radians(-90 + step * 36)
        point = QPointF(
            center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle)
        )
        if step == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_trash(painter: QPainter) -> None:
    """ゴミ箱。ふたと本体と縦線 2 本。"""
    painter.drawLine(QPointF(11, 18), QPointF(53, 18))
    painter.drawPolyline([QPointF(26, 18), QPointF(26, 11), QPointF(38, 11), QPointF(38, 18)])
    painter.drawPolyline([QPointF(16, 18), QPointF(19, 55), QPointF(45, 55), QPointF(48, 18)])
    painter.drawLine(QPointF(27, 27), QPointF(28, 46))
    painter.drawLine(QPointF(37, 27), QPointF(36, 46))


def _draw_folder(painter: QPainter) -> None:
    """フォルダ。左上に見出しの出っ張りを付ける。"""
    painter.drawPolyline(
        [
            QPointF(8, 50),
            QPointF(8, 16),
            QPointF(24, 16),
            QPointF(30, 24),
            QPointF(56, 24),
            QPointF(56, 50),
            QPointF(8, 50),
        ]
    )


def _draw_close(painter: QPainter) -> None:
    """×。**線 2 本だけ**（丸で囲むと押せる範囲より大きく見える）。"""
    painter.drawLine(QPointF(20, 20), QPointF(44, 44))
    painter.drawLine(QPointF(44, 20), QPointF(20, 44))


def _draw_tag(painter: QPainter) -> None:
    """タグ。角を落とした札と穴。"""
    path = QPainterPath()
    path.moveTo(QPointF(33, 10))
    path.lineTo(QPointF(54, 31))
    path.lineTo(QPointF(31, 54))
    path.lineTo(QPointF(10, 33))
    path.lineTo(QPointF(10, 10))
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawEllipse(QPointF(21, 21), 4.5, 4.5)


# ------------------------------------------------- 書式ツールバー（B-1）
#
# 太字・斜体・打ち消し・見出しは**字そのもの**を描く。B / I / S / H は
# どの編集ソフトでも同じ絵で、線で描いた抽象記号より早く読める。
# 残りは線で描く。引用は本文での見え方（`painter_overlay` の縦線）に揃える。

_LETTER_SIZE = 44
_LINE_LEFT, _LINE_RIGHT = 24.0, 54.0
_LINE_ROWS = (17.0, 32.0, 47.0)


def _letter(painter: QPainter, char: str, *, bold: bool = False, italic: bool = False) -> None:
    font = painter.font()
    font.setPixelSize(_LETTER_SIZE)
    font.setBold(bold)
    font.setItalic(italic)
    painter.setFont(font)
    # 字は塗りではなくペンの色で出る。輪郭用の太いペンは字には効かない
    painter.drawText(QRectF(0, 0, CANVAS, CANVAS), Qt.AlignmentFlag.AlignCenter, char)


def _rows(painter: QPainter, rows=_LINE_ROWS) -> None:
    """本文を表す横線。リスト系のアイコンで共通に使う。"""
    for y in rows:
        painter.drawLine(QPointF(_LINE_LEFT, y), QPointF(_LINE_RIGHT, y))


def _draw_bold(painter: QPainter) -> None:
    _letter(painter, "B", bold=True)


def _draw_italic(painter: QPainter) -> None:
    """傾いた I。**字を斜体にしただけでは斜線にしか見えない**（実際に描いて確認）。
    上下の横棒を足すと I だと読める。"""
    painter.drawLine(QPointF(26, 14), QPointF(48, 14))
    painter.drawLine(QPointF(16, 50), QPointF(38, 50))
    painter.drawLine(QPointF(38, 14), QPointF(26, 50))


def _draw_strike(painter: QPainter) -> None:
    _letter(painter, "S")
    painter.drawLine(QPointF(12, 32), QPointF(52, 32))


def _draw_code(painter: QPainter) -> None:
    """山括弧。"""
    painter.drawPolyline([QPointF(24, 18), QPointF(10, 32), QPointF(24, 46)])
    painter.drawPolyline([QPointF(40, 18), QPointF(54, 32), QPointF(40, 46)])


def _draw_marker(painter: QPainter) -> None:
    """マーカーペンと引いた線。

    **横線だけで表すと箇条書き・引用と見分けが付かない**（実際に並べて確認）。
    ペンの形を足して区別する。
    """
    pen = painter.pen()
    painter.setBrush(Qt.BrushStyle.NoBrush)

    body = QPainterPath()  # 傾けたペン先
    body.moveTo(QPointF(40, 8))
    body.lineTo(QPointF(56, 24))
    body.lineTo(QPointF(28, 44))
    body.lineTo(QPointF(16, 44))
    body.lineTo(QPointF(16, 32))
    body.closeSubpath()
    painter.drawPath(body)

    stroke = QPen(pen)  # 引いた跡
    stroke.setWidthF(9.0)
    painter.setPen(stroke)
    painter.drawLine(QPointF(14, 55), QPointF(50, 55))
    painter.setPen(pen)


def _draw_link(painter: QPainter) -> None:
    """鎖の輪 2 つ。傾けた角丸で表す。"""
    painter.save()
    painter.translate(32, 32)
    painter.rotate(-40)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(-26, -11, 30, 22), 11, 11)
    painter.drawRoundedRect(QRectF(-4, -11, 30, 22), 11, 11)
    painter.restore()


def _draw_heading(painter: QPainter) -> None:
    _letter(painter, "H", bold=True)


def _draw_outline(painter: QPainter) -> None:
    """アウトライン。**段差の付いた行**（見出しの入れ子）。

    箇条書き（`BULLET`）と紛らわしくならないよう、点は描かず**左端を
    ずらす**ことで階層を表す。行の長さも段ごとに短くして、下ほど細かい
    話になる形を見せる。
    """
    for y, left in zip(_LINE_ROWS, (12.0, 22.0, 32.0), strict=True):
        painter.drawLine(QPointF(left, y), QPointF(_LINE_RIGHT, y))


def _draw_bullet(painter: QPainter) -> None:
    """点と行。"""
    _rows(painter)
    painter.setBrush(QBrush(painter.pen().color()))
    for y in _LINE_ROWS:
        painter.drawEllipse(QPointF(12, y), 3.5, 3.5)


def _draw_ordered(painter: QPainter) -> None:
    """数字と行。"""
    _rows(painter)
    font = painter.font()
    font.setPixelSize(17)
    painter.setFont(font)
    for index, y in enumerate(_LINE_ROWS, start=1):
        painter.drawText(
            QRectF(0, y - 11, 20, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            str(index),
        )


def _draw_checkbox(painter: QPainter) -> None:
    """四角とチェック。"""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(11, 11, 42, 42), 8, 8)
    painter.drawPolyline([QPointF(20, 33), QPointF(29, 42), QPointF(45, 22)])


def _draw_quote(painter: QPainter) -> None:
    """縦線と行。本文での引用の見え方に合わせる。"""
    pen = painter.pen()
    bar = QPen(pen)
    bar.setWidthF(7.0)
    painter.setPen(bar)
    painter.drawLine(QPointF(13, 15), QPointF(13, 49))
    painter.setPen(pen)
    _rows(painter, rows=(20.0, 32.0, 44.0))


def _draw_search(painter: QPainter) -> None:
    """保存した検索。虫めがね（輪 + 柄）。"""
    painter.drawEllipse(QRectF(16, 16, 22, 22))
    painter.drawLine(QPointF(35, 35), QPointF(48, 48))


def _draw_sort(painter: QPainter) -> None:
    """並び順。**上向きと下向きの矢印を並べる。**

    文字の `⇅` は書体で形が変わるうえ、ポップアップ用の三角と近づくと
    重なった（ユーザー報告）。線で描けば大きさも間隔もこちらで決まる。
    """
    for x, tip, tail in ((24.0, 14.0, 50.0), (40.0, 50.0, 14.0)):
        painter.drawLine(QPointF(x, tail), QPointF(x, tip))
        head = 9.0 if tip < tail else -9.0
        painter.drawPolyline(
            [QPointF(x - 7, tip + head), QPointF(x, tip), QPointF(x + 7, tip + head)]
        )


def _draw_new_note(painter: QPainter) -> None:
    """新規。十字。"""
    painter.drawLine(QPointF(32, 14), QPointF(32, 50))
    painter.drawLine(QPointF(14, 32), QPointF(50, 32))


def _draw_gear(painter: QPainter) -> None:
    """メニュー。歯車。輪 + 8 枚の歯 + 軸穴。

    歯は線 1 本ではなく**太いペンの短い線**で描く（ユーザー要望）。
    細い線だとトゲに見えて歯車に読めない。丸キャップなので先が丸い
    歯になり、輪の線とのつながりも滑らか。
    """
    tooth = QPen(painter.pen())
    tooth.setWidthF(STROKE * 1.6)
    rim = painter.pen()
    painter.setPen(tooth)
    for step in range(8):
        angle = radians(step * 45)
        x, y = cos(angle), sin(angle)
        painter.drawLine(QPointF(32 + 13 * x, 32 + 13 * y), QPointF(32 + 18 * x, 32 + 18 * y))
    painter.setPen(rim)
    painter.drawEllipse(QRectF(21, 21, 22, 22))
    painter.drawEllipse(QRectF(28, 28, 8, 8))


_DRAW = {
    Glyph.SORT: _draw_sort,
    Glyph.SEARCH: _draw_search,
    Glyph.NEW_NOTE: _draw_new_note,
    Glyph.OUTLINE: _draw_outline,
    Glyph.GEAR: _draw_gear,
    Glyph.ALL: _draw_all,
    Glyph.PINNED: _draw_pinned,
    Glyph.TRASH: _draw_trash,
    Glyph.TAG: _draw_tag,
    Glyph.CLOSE: _draw_close,
    Glyph.FOLDER: _draw_folder,
    Glyph.BOLD: _draw_bold,
    Glyph.ITALIC: _draw_italic,
    Glyph.STRIKE: _draw_strike,
    Glyph.CODE: _draw_code,
    Glyph.MARKER: _draw_marker,
    Glyph.LINK: _draw_link,
    Glyph.HEADING: _draw_heading,
    Glyph.BULLET: _draw_bullet,
    Glyph.ORDERED: _draw_ordered,
    Glyph.CHECKBOX: _draw_checkbox,
    Glyph.QUOTE: _draw_quote,
}


def menu_icon(label: str) -> QIcon | None:
    """メニューの項目に付ける絵。台帳に無い言葉なら `None`。

    **先に絵（pixmap）へ焼いてから渡す**（性能。2026-08-25 の実測）。
    `QIcon.fromTheme()` の戻りをそのままネイティブメニューへ入れると
    **1 種類 16ms** かかり、メニューバーの 35 個で 569ms——起動が基準
    （1500ms）を割っていた。焼いてから渡すと **20 個で 14ms**（18 倍）で、
    見た目は変わらない。

    | 20 個をメニューバーへ | 所要 |
    | --- | --- |
    | `fromTheme` をそのまま | 255ms |
    | **焼いてから** | **14ms** |

    遅いのは**ネイティブメニューへの挿入**だけで、`fromTheme` を呼ぶこと
    自体は 0ms、ポップアップへの挿入も 0ms（実測）。

    **画面の倍率で焼く。** 16x16 で焼くと Retina でぼやける。
    """
    name = MENU_ICONS.get(label)
    if not name:
        return None
    app = QApplication.instance()
    return _baked_icon(name, app.devicePixelRatio() if app else 1.0)


@functools.cache
def _baked_icon(name: str, ratio: float) -> QIcon:
    """焼いた絵を覚えておく。**同じ絵はメニューバーと右クリックで共用**。"""
    return QIcon(QIcon.fromTheme(name).pixmap(QSize(MENU_ICON_SIZE, MENU_ICON_SIZE), ratio))


MENU_ICON_SIZE = 16
"""メニューの絵の大きさ（論理 px）。実際は画面の倍率を掛けて焼く。"""

MENU_ICONS = {
    # **アイコンは OS からもらう**（`QIcon.fromTheme`）。自分で描くと
    # SF Symbols と並んだときに浮く。macOS 以外や offscreen では空の
    # アイコンが返り、**付かないだけ**で何も壊れない。
    #
    # **チェック印の付く項目には付けない**（ユーザー要望 2026-08-24 の
    # 際に実測）。印は絵と同じ場所に描かれるので、入のときは絵が消え、
    # 切のときだけ絵が出る。切り替えるたびに見た目が変わって分かりにくい。
    #
    # 右クリックとメニューバーで**同じ言葉には同じ絵**を使う。
    # 一覧・サイドバーの右クリック
    "ピン留め": "emblem-favorite",
    "ピン留めを外す": "emblem-favorite",
    "名前を変更…": "document-properties",
    "複製": "edit-copy",
    "テンプレートに登録…": "document-new",
    "フォルダへ移動…": "go-next",
    "リンクをコピー": "insert-link",
    "Finder で表示": "system-file-manager",
    "Finder で開く": "system-file-manager",
    "ゴミ箱へ移動": "user-trash",
    "元に戻す": "edit-undo",
    "完全に削除…": "edit-delete",
    "新しいフォルダ…": "folder-new",
    "フォルダを削除…": "edit-delete",
    "ゴミ箱を空にする…": "user-trash",
    "この検索を削除…": "edit-delete",
    # ファイル
    "新規ノート": "document-new",
    "テンプレートから新規…": "list-add",
    "テンプレートを削除…": "edit-delete",
    "今日のノート": "appointment-new",
    "前の日のノート": "go-previous",
    "次の日のノート": "go-next",
    "保存": "document-save",
    "最新の情報に同期": "view-refresh",
    "索引を作り直す": "system-search",
    "モデルを降ろす": "media-eject",
    "版の履歴…": "document-open-recent",
    "読み込む…": "document-open",
    "書き出す": "document-send",
    # 手入れ（2026-08-25 に畳んだ）。**道具箱の絵**——同期・索引・添付・
    # テンプレート・モデルの片づけがここに入る
    "手入れ": "wrench.and.screwdriver",
    "印刷…": "document-print",
    "ブラウザで確認": "applications-internet",
    "HTML をコピー": "edit-copy",
    "使っていない添付を片づける…": "edit-clear",
    # 検索
    "クイックオープン": "document-open",
    "全文検索": "system-search",
    "検索を保存…": "document-save",
    "このノート内を検索": "edit-find",
    "次を検索": "go-down",
    "前を検索": "go-up",
    # 編集
    "取り消す": "edit-undo",
    "やり直す": "edit-redo",
    "切り取り": "edit-cut",
    "コピー": "edit-copy",
    "貼り付け": "edit-paste",
    "表を整形": "format-justify-fill",
    "選択範囲をノートにする": "document-new",
    # 表示
    "直前のノートへ戻る": "go-previous",
    "文字を大きく": "zoom-in",
    "文字を小さく": "zoom-out",
    # ヘルプ
    f"{APP_NAME} について": "help-about",
}
"""メニューの項目名 → OS のアイコン名（`QIcon.fromTheme`）。

ここに無い言葉には絵を付けない。**無理に付けない**——意味の合う絵が
無いもの（「見出しへ飛ぶ」「標準の大きさ」「設定…」など）は文字だけで出す。
"""
