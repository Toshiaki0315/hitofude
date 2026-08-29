"""リンク先をその場で覗く（U-2。ユーザー要望 2026-08-29）。

`[[ノート]]` に `Cmd` を押しながら触れると、**開かずに**冒頭が浮いて出る。
確かめるために開いて戻る往復が要らなくなる。

**`Cmd` を要る条件にする。** 素の移動で泡が出ると、文字を選ぼうとした
だけで邪魔になる——カーソルの形（`_update_hover`）が同じ理由で `Cmd` を
条件にしており、開く操作自体も `Cmd+クリック` なので揃う。

ここは **vault を知らない**（`set_note_source` と同じ作法）。題名を渡すと
中身を返す係を呼び出し側が挿す。泡そのものは `ui/tooltip` が出す——
黒地に白の同じ見た目を 2 つ作らない。
"""

from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QTimer

from hitofude.core import frontmatter
from hitofude.core.activation import ActivationKind
from hitofude.core.document import title_of
from hitofude.ui import tooltip

DELAY_MS = 400
"""触れてから出すまでの待ち。

**短すぎると通り過ぎるだけで出る。** 読むつもりで止めたときにだけ
出したい。ツールチップの標準（500ms 前後）より気持ち早める——
こちらは `Cmd` を押している時点で「見たい」意思が入っている。
"""

EXCERPT_LINES = 6
"""覗かせる行数。**全部は出さない**（それは開くこと）。"""

EXCERPT_CHARS = 240
"""行が長いときの上限。泡が画面を覆わないように。"""


def excerpt(text: str) -> str:
    """本文の冒頭。**題名の行は落とす**（泡の見出しと重なる）。

    記号は落とさない——`- ` や `` ` `` が消えると、箇条書きなのかコード
    なのか分からなくなる。読めれば十分なので、行数と字数だけで切る。
    """
    # **front matter は出さない。** 実物のノートには作成日時と id が
    # 付いており、そのまま出すと泡が YAML で埋まる（実機で確認）
    body = frontmatter.split(text).body
    title = title_of(text, "")
    lines: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if not lines and (stripped.lstrip("#").strip() == title or stripped.startswith("#")):
            continue  # 題名の行
        lines.append(line.rstrip())
        if len(lines) >= EXCERPT_LINES:
            break
    found = "\n".join(lines)
    return found if len(found) <= EXCERPT_CHARS else found[:EXCERPT_CHARS] + "…"


class LinkPreview(QObject):
    """マウスの位置を受け取って、出すか隠すかを決める係。"""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self._editor = editor
        self._source: Callable[[str], str | None] | None = None
        self._title: str | None = None
        self._at: QPoint | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self.show_now)

        # 位置が古くなったら隠すだけ。次に触れれば出直す（写しの印と同じ作法）
        editor.textChanged.connect(self.hide)
        editor.verticalScrollBar().valueChanged.connect(self.hide)

    def set_source(self, source: Callable[[str], str | None] | None) -> None:
        """題名から中身を引く係を挿す。`None` を返せば出さない。"""
        self._source = source

    # ------------------------------------------------------------------ 表示

    def update(self, point: QPoint, *, held: bool) -> None:
        """今の位置と `Cmd` の状態から、出す用意をする。"""
        title = self._note_at(point) if held else None
        if title is None:
            self.hide()
            return
        if title == self._title and tooltip.is_showing():
            return  # 同じリンクの上。出し直さない
        self._title = title
        self._at = point
        self._timer.start()

    def show_now(self) -> None:
        """待ちを飛ばして出す。**中身が無ければ出さない。**"""
        self._timer.stop()
        if self._title is None or self._at is None or self._source is None:
            return
        text = self._source(self._title)
        if not text:
            return  # まだ無いノート。空の泡を出さない
        body = excerpt(text)
        if not body:
            return
        tooltip.show(self._editor.viewport().mapToGlobal(self._at), f"{self._title}\n\n{body}")

    def hide(self) -> None:
        self._timer.stop()
        self._title = None
        self._at = None
        tooltip.hide()

    # ------------------------------------------------------------------ 判定

    def _note_at(self, point: QPoint) -> str | None:
        """その位置にあるノートへのリンクの題名。無ければ `None`。"""
        found = self._editor._activation_at(point)
        if found is None or found.kind is not ActivationKind.NOTE:
            return None
        return found.payload
