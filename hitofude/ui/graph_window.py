"""リンクの図（M-2 / 仮身ネットワーク）。

BTRON の「あるファイルを起点としたリンク構造」。形と座標は
`core/graph.py` が決める（R3）ので、ここは**描いて押せるようにするだけ**。

**別の窓にする。** 本文の横には既に 5 つの領域が並んでいて、図はそこに
入れると狭すぎる。`Cmd+Shift+F` の窓と同じ作法（枠なし・Esc で閉じる・
言葉で書いた閉じるボタン）。

**図は読むためのもの。** 図の上でノートを作ったり繋ぎ替えたりはしない。
真実は `.md` の側にある（R1）ので、図から線を引けると**どちらが本体か
曖昧になる**。
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hitofude.config import MAX_GRAPH_DEPTH, MIN_GRAPH_DEPTH
from hitofude.core import graph
from hitofude.theme import LIGHT, ThemeColors
from hitofude.ui.format_toolbar import BUTTON_RADIUS
from hitofude.ui.icons import Glyph, glyph_icon
from hitofude.ui.quick_open import CLOSE_ICON

NODE_RADIUS = 6
"""点の大きさ。押せる大きさと、200 点並べても潰れない大きさの折り合い。"""

START_RADIUS = 9
"""起点だけ大きく描く。**色だけでは埋もれる** — 34 点の図を実際に描いて
見たところ、同じ大きさの丸が並ぶ中で赤 1 つは見つけにくかった。
「今どこを見ているか」が図の意味の半分なので、大きさでも差を付ける。"""

HIT_RADIUS = 14
"""押したと見なす範囲。**点より広く取る。** 6px を正確に狙わせない。"""

MARGIN = 40
"""枠の内側の余白。題名が窓の外へはみ出さないぶん。"""

LABEL_GAP = 4

MAX_LABEL_WIDTH = 150
"""題名の幅の上限。**切り詰めてでも出す** — 34 点の図を描いて見たところ、
題名があるほうが読めた（M-4）。窓がこれより狭ければ窓に合わせる。"""

ALL_RELATIONS = "すべての続柄"
"""続柄で絞らないときの選択肢（M-3）。"""


@dataclass(frozen=True, slots=True)
class Label:
    """題名の置き場。**描く前に決めておく**（`painter_overlay` と同じ作法）。"""

    number: int
    """どの点のものか。**隠すものがある**ので、並びだけでは辿れない。"""

    text: str
    """切り詰めたあとの文字。"""

    x: int
    """描き始めの左端。**窓の中に収まっている。**"""

    y: int


def place_labels(
    nodes: list[graph.Node],
    points: list[QPoint],
    *,
    width: int,
    metrics: QFontMetrics,
    height: int | None = None,
) -> list[Label]:
    """点の題名をどこにどう描くか決める（M-4）。

    **実測で見つけた不具合を直すためのもの。** 長い題名のノートが 8 本
    ぶら下がる図で、9 点のうち 4 つの題名が窓からはみ出していた
    （左端で先頭が欠け、右端で末尾が欠ける）。

    やることは 3 つ。**切り詰める**（`…` を付ける）、**窓の中へ押し込む**
    （縁の点は中央揃えをやめる）、**重なるものは上下に逃がし、それでも
    重なるなら出さない**。

    切り詰めるだけでは足りない（レビュー指摘。実測: 200 点で 234 組が
    重なっていた）。**200 点ぶんの題名が入る場所は無い**ので、どこかで
    諦めるしかない。諦める順は**起点から遠いほう**から——`nodes` は幅優先の
    並び（`core/graph.build`）なので、前から詰めれば近いものが残る。

    出さなかった題名は**カーソルを乗せれば出る**（`GraphView.hover`）。
    """
    limit = max(min(MAX_LABEL_WIDTH, width), 1)
    line = metrics.height()
    floor = height if height is not None else None
    found: list[Label] = []
    taken: list[tuple[int, int, int, int]] = []
    for number, (node, center) in enumerate(zip(nodes, points, strict=True)):
        # **真ん中で切る。** 末尾を落とすと、`…その30`〜`…その37` のように
        # **見分けが付く部分だけが消える**（実測: 8 本ぶら下げたら題名が
        # 全部同じに読めた）。日付や連番は末尾に来ることが多い
        text = metrics.elidedText(node.title, Qt.TextElideMode.ElideMiddle, limit)
        span = metrics.horizontalAdvance(text)
        # 中央揃えを基本に、**縁ではそちらへ寄せる**
        left = max(0, min(center.x() - span // 2, width - span))
        radius = START_RADIUS if node.depth == 0 else NODE_RADIUS
        # 上に置けなければ下へ逃がす。**丸には重ねない**
        above = center.y() - radius - LABEL_GAP
        below = center.y() + radius + LABEL_GAP + metrics.ascent()
        for baseline in (above, below):
            if floor is not None and not (line <= baseline <= floor):
                continue
            box = (left, baseline - line, left + span, baseline)
            if any(_hits(box, other) for other in taken):
                continue
            taken.append(box)
            found.append(Label(number=number, text=text, x=left, y=baseline))
            break
    return found


def _hits(one: tuple[int, int, int, int], other: tuple[int, int, int, int]) -> bool:
    return one[0] < other[2] and other[0] < one[2] and one[1] < other[3] and other[1] < one[3]


class GraphView(QWidget):
    """点と線を描く。**座標は 0〜1 で受け取り**、描く直前に窓へ合わせる。"""

    picked = Signal(int)
    """押された点の番号。"""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeColors = LIGHT) -> None:
        super().__init__(parent)
        self._theme = theme
        self._graph = graph.Graph()
        self.places: list[tuple[float, float]] = []
        self._hovered: int | None = None
        self.setMinimumSize(QSize(360, 260))
        self.setMouseTracking(True)

    def set_graph(self, found: graph.Graph, places: list[tuple[float, float]]) -> None:
        self._graph = found
        self.places = places
        self._hovered = None  # 図が変われば番号の意味も変わる
        self.update()

    def point_of(self, number: int) -> QPoint:
        """点の番号 → 窓の中の場所。**当たり判定と描画で同じ式を使う。**"""
        x, y = self.places[number]
        width = max(self.width() - 2 * MARGIN, 1)
        height = max(self.height() - 2 * MARGIN, 1)
        return QPoint(round(MARGIN + x * width), round(MARGIN + y * height))

    def node_at(self, where: QPoint) -> int | None:
        """その場所にある点。無ければ `None`。**手前のものから見る。**"""
        best: tuple[int, int] | None = None
        for number in range(len(self.places)):
            offset = self.point_of(number) - where
            distance = offset.x() * offset.x() + offset.y() * offset.y()
            if distance <= HIT_RADIUS * HIT_RADIUS and (best is None or distance < best[0]):
                best = (distance, number)
        return None if best is None else best[1]

    def mousePressEvent(self, event) -> None:
        number = self.node_at(event.position().toPoint())
        if number is not None:
            self.picked.emit(number)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._theme.background))
        if not self.places:
            return

        # **線を先に描く。** 後から描くと点の上に乗って、丸が欠けて見える
        painter.setPen(QPen(QColor(self._theme.rule), 1))
        for source, target in self._graph.edges:
            painter.drawLine(self.point_of(source), self.point_of(target))

        labels = self.labels()
        for number, node in enumerate(self._graph.nodes):
            center = self.point_of(number)
            radius = START_RADIUS if node.depth == 0 else NODE_RADIUS
            path = QPainterPath()
            path.addEllipse(center, radius, radius)
            if node.exists:
                # 起点だけ強く。**今どこを見ているか**が図の意味の半分
                color = self._theme.accent if node.depth == 0 else self._theme.muted_foreground
                painter.fillPath(path, QColor(color))
            else:
                # **中抜き。** まだ無いノート（`[[…]]` の行き先が無い）
                painter.setPen(QPen(QColor(self._theme.muted_foreground), 1))
                painter.drawPath(path)
        painter.setPen(QPen(QColor(self._theme.foreground)))
        for label in labels:
            painter.drawText(label.x, label.y, label.text)
        painter.end()

    def hover(self, where: QPoint) -> None:
        """カーソルの下の点を覚える。**隠した題名をそこだけ出す。**

        混んだ図では題名を出せない点が出る（200 点ぶんの場所は無い）。
        名前が分からないままでは図として使えないので、指したものは出す。
        """
        number = self.node_at(where)
        if number != self._hovered:
            self._hovered = number
            self.update()

    def mouseMoveEvent(self, event) -> None:
        self.hover(event.position().toPoint())

    def leaveEvent(self, event) -> None:
        self.hover(QPoint(-1, -1))

    def labels(self) -> list[Label]:
        """今の大きさでの題名の置き場。**描く式と試験で同じものを見る。**"""
        points = [self.point_of(number) for number in range(len(self.places))]
        found = place_labels(
            self._graph.nodes,
            points,
            width=self.width(),
            height=self.height(),
            metrics=QFontMetrics(self.font()),
        )
        if self._hovered is None or any(label.number == self._hovered for label in found):
            return found
        # **指したものは重ねてでも出す。** 隠れている名前を読むための操作
        # なので、ここで遠慮すると何も起きないように見える
        metrics = QFontMetrics(self.font())
        node = self._graph.nodes[self._hovered]
        center = points[self._hovered]
        text = metrics.elidedText(
            node.title,
            Qt.TextElideMode.ElideMiddle,
            max(min(MAX_LABEL_WIDTH, self.width()), 1),
        )
        span = metrics.horizontalAdvance(text)
        left = max(0, min(center.x() - span // 2, self.width() - span))
        return [
            *found,
            Label(
                number=self._hovered,
                text=text,
                x=left,
                y=center.y() - NODE_RADIUS - LABEL_GAP,
            ),
        ]


class GraphWindow(QDialog):
    """図の窓。深さを変えられる（記事の「何段階先まで」）。"""

    opened = Signal(str)
    """押された点の題名。**開くのは呼ぶ側**（ここは索引もフォルダも知らない）。"""

    missed = Signal(str)
    """まだ無いノートが押された。**作らない**ので、呼ぶ側が知らせるだけ。"""

    depth_changed = Signal(int)
    """深さが変わった。**変えた時点で覚える** — 閉じ方（Esc・ボタン・窓ごと）
    によって覚えたり覚えなかったりすると、覚えていない理由が分からない。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        start: str,
        links_for: Callable[[str | None], dict[str, list[str]]],
        relations: list[str] | None = None,
        depth: int = graph.DEFAULT_DEPTH,
        theme: ThemeColors = LIGHT,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.resize(680, 480)
        self.setStyleSheet(f"QDialog {{ background: {theme.background}; }}")

        self._start = start
        # **続柄で絞るたびに引き直す**（M-3）。絞った結果を持ち回ると、
        # どの続柄で作った表なのかが分からなくなる
        self._links_for = links_for
        self._relation: str | None = None
        self._depth = depth
        self._limit = graph.MAX_NODES
        self._graph = graph.Graph()

        self.view = GraphView(self, theme=theme)
        self.view.picked.connect(self._pick)

        self._depth_box = QSpinBox(self)
        self._depth_box.setRange(MIN_GRAPH_DEPTH, MAX_GRAPH_DEPTH)
        self._depth_box.setValue(depth)
        self._depth_box.setToolTip("起点から何段先まで辿るか")
        self._depth_box.valueChanged.connect(self.set_depth)

        # 続柄で絞る（M-3）。**使っていなければ置かない** — 空の枠が並ぶと邪魔
        self.relation_box = QComboBox(self)
        self.relation_box.addItem(ALL_RELATIONS, None)
        for name in relations or []:
            self.relation_box.addItem(name, name)
        self.relation_box.setToolTip("リンクに付けた続柄で絞る")
        self.relation_box.currentIndexChanged.connect(
            lambda _index: self.set_relation(self.relation_box.currentData())
        )
        self.relation_box.setVisible(bool(relations))

        self._notice = QLabel(self)
        self._notice.setStyleSheet(f"QLabel {{ color: {theme.muted_foreground}; }}")

        # **言葉で書いた閉じるボタン**（`Cmd+Shift+F` で 2 回報告があった。
        # 薄い × は大きくしても見つけてもらえない）
        self.close_button = QPushButton("閉じる", self)
        self.close_button.setIcon(glyph_icon(Glyph.CLOSE, theme.muted_foreground))
        self.close_button.setIconSize(QSize(CLOSE_ICON, CLOSE_ICON))
        self.close_button.setToolTip("閉じる（Esc）")
        self.close_button.setStyleSheet(
            f"QPushButton {{ color: {theme.muted_foreground}; "
            f"border: 1px solid {theme.rule}; border-radius: {BUTTON_RADIUS}px; "
            f"padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {theme.tag_background}; }}"
        )
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.reject)

        header = QHBoxLayout()
        header.addWidget(QLabel(f"「{start}」から", self))
        header.addWidget(QLabel("深さ", self))
        header.addWidget(self._depth_box)
        header.addWidget(self.relation_box)
        header.addWidget(self._notice, 1)
        header.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.view, 1)

        self._rebuild()

    # ------------------------------------------------------------------ 参照

    def graph(self) -> graph.Graph:
        return self._graph

    def depth(self) -> int:
        return self._depth

    def relation(self) -> str | None:
        """絞っている続柄。絞っていなければ `None`。"""
        return self._relation

    def notice(self) -> str:
        return self._notice.text()

    # ------------------------------------------------------------------ 操作

    def set_depth(self, depth: int) -> None:
        self._depth = depth
        if self._depth_box.value() != depth:
            self._depth_box.setValue(depth)
        self._rebuild()
        self.depth_changed.emit(depth)

    def set_relation(self, relation: str | None) -> None:
        """続柄で絞る（M-3）。`None` なら絞らない。"""
        self._relation = relation
        index = self.relation_box.findData(relation)
        if index >= 0 and self.relation_box.currentIndex() != index:
            self.relation_box.setCurrentIndex(index)
        self._rebuild()

    def set_limit(self, limit: int) -> None:
        """描く点の上限。**試験と、狭い窓のためだけ**（ふだんは既定のまま）。"""
        self._limit = limit
        self._rebuild()

    # ------------------------------------------------------------------ 内部

    def _rebuild(self) -> None:
        self._graph = graph.build(
            self._start,
            self._links_for(self._relation),
            depth=self._depth,
            limit=self._limit,
        )
        # **座標も作り直す。** 使い回すと数が合わず、点がはみ出す
        self.view.set_graph(self._graph, graph.layout(self._graph))
        self._notice.setText(
            f"多いので {self._graph.dropped} 件は描いていません" if self._graph.dropped else ""
        )

    def _pick(self, number: int) -> None:
        node = self._graph.nodes[number]
        if not node.exists:
            # **作らない。** 図は読むためのもので、真実は `.md` の側にある
            self.missed.emit(node.title)
            return
        self.opened.emit(node.title)
        self.accept()
