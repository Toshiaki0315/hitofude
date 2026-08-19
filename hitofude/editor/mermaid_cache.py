"""Mermaid 図の描画（I-1 / ADR-0021）。

同梱の mermaid.min.js（v11.16.1 / MIT、resources/vendor/）を
QtWebEngine のオフスクリーンページで実行し、図を QPixmap にする。
**ネットには繋がない**（JS もフォントも手元のもの）。

描画は非同期（Chromium 側で数百 ms）なので、キャッシュは 3 状態を持つ:
未依頼（頼んで None）/ 依頼中（None）/ 完了（絵、または失敗の記録）。
完了すると `rendered` シグナルが飛び、エディタが該当ブロックを掛け直す。

QtWebEngine は QApplication より先に import されている必要がある。
アプリは `app.py` が、テストは `tests/conftest.py` が済ませる。
"""

import json
import logging
from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor

logger = logging.getLogger(__name__)

# 書き出し（B-4 / exporter.py）と同じ同梱物を使う。ライセンス表記は
# resources/vendor/mermaid-LICENSE.txt（MIT）
_JS_PATH = Path(__file__).parent.parent / "resources" / "vendor" / "mermaid.min.js"

# 覚えておく絵の数。1 ノートに載る図はせいぜい数枚
_CACHE_SIZE = 16

# 図の描画領域の上限。これより大きい図は Chromium 側で切れる
_VIEW_SIZE = QSize(1600, 1600)

# DOM の更新から grab までの待ち。描画パイプラインが 1 拍遅れる
_GRAB_DELAY_MS = 120

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="mermaid.min.js"></script></head>
<body style="margin:0;background:transparent">
<div id="out"></div>
<script>
let seq = 0;
async function draw(source, dark) {
  seq += 1;
  const id = "m" + seq;
  mermaid.initialize({startOnLoad: false, theme: dark ? "dark" : "default"});
  try {
    const {svg} = await mermaid.render(id, source);
    document.getElementById("out").innerHTML = svg;
    const box = document.querySelector("#out svg").getBoundingClientRect();
    document.title = "ok " + seq + " " + Math.ceil(box.width) + " " + Math.ceil(box.height);
  } catch (error) {
    // 失敗の後始末。mermaid はエラー図を DOM に残すことがある
    document.getElementById("out").innerHTML = "";
    const litter = document.getElementById("d" + id);
    if (litter) litter.remove();
    document.title = "err " + seq;
  }
}
document.title = "ready";
</script></body></html>"""


class MermaidCache(QObject):
    """図ごとの描画結果。壊れた図は「失敗」を覚える（毎回試さない）。"""

    rendered = Signal()
    """1 枚描き上がった（または失敗が確定した）。受け手は表示を掛け直す。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._results: OrderedDict[tuple[str, bool], object] = OrderedDict()
        self._queue: deque[tuple[str, bool]] = deque()
        self._current: tuple[str, bool] | None = None
        self._view = None
        self._page_ready = False
        # 図の下に敷く色。透明は grab で白に落ちるので、エディタが
        # コードブロックの背景色を渡して馴染ませる（set_background）
        self._background = "#FFFFFF"

    def set_background(self, color: str) -> None:
        """図の下に敷く色。テーマのコード背景に合わせる。

        変えたら覚えている絵を捨てる（前の背景で焼き込まれているため）。
        """
        if color == self._background:
            return
        self._background = color
        self._results.clear()

    # ------------------------------------------------------------------ 参照

    def pixmap(self, source: str, *, dark: bool, max_width: int):
        """描いた絵。未依頼なら描画を予約して None（後で `rendered` が飛ぶ）。"""
        key = (source, dark)
        if key in self._results:
            found = self._results[key]
            if found is None:
                return None  # 失敗の記録
            if max_width > 0 and found.width() / found.devicePixelRatio() > max_width:
                return found.scaledToWidth(
                    round(max_width * found.devicePixelRatio()),
                    Qt.TransformationMode.SmoothTransformation,
                )
            return found
        self._request(key)
        return None

    def size(self, source: str, *, dark: bool, max_width: int) -> QSize | None:
        """絵の論理サイズ。高さの予約（highlighter）が見る。"""
        found = self.pixmap(source, dark=dark, max_width=max_width)
        if found is None:
            return None
        ratio = found.devicePixelRatio()
        return QSize(round(found.width() / ratio), round(found.height() / ratio))

    def done(self, source: str, *, dark: bool) -> bool:
        """描画（または失敗）が確定しているか。テストの待ち合わせに使う。"""
        return (source, dark) in self._results

    # ------------------------------------------------------------------ 描画

    def _request(self, key: tuple[str, bool]) -> None:
        if key == self._current or key in self._queue:
            return
        self._queue.append(key)
        self._pump()

    def _pump(self) -> None:
        if self._current is not None or not self._queue:
            return
        self._current = self._queue.popleft()
        self._ensure_view()
        if not self._page_ready:
            return  # ページの読み込み完了（_on_title "ready"）から続く
        self._run_current()

    def _run_current(self) -> None:
        source, dark = self._current
        self._view.page().setBackgroundColor(QColor(self._background))
        self._view.page().runJavaScript(f"draw({json.dumps(source)}, {json.dumps(dark)})")

    def _ensure_view(self):
        if self._view is not None:
            return self._view
        # ここまで来て初めて Chromium が立ち上がる。図の無いノートしか
        # 開かない人にはこのコストを払わせない
        from PySide6.QtWebEngineWidgets import QWebEngineView

        view = QWebEngineView()
        view.resize(_VIEW_SIZE)
        view.titleChanged.connect(self._on_title)
        # **見えないまま描かせる。** show() しないと Chromium が描画せず、
        # grab() が無地になる（実測）。この属性で「表示扱いだが画面には
        # 出ない」状態になり、実アプリでも窓は現れない
        view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        view.show()
        view.setHtml(_PAGE, QUrl.fromLocalFile(str(_JS_PATH.parent) + "/"))
        self._view = view
        return view

    def _on_title(self, title: str) -> None:
        if title == "ready":
            self._page_ready = True
            if self._current is not None:
                self._run_current()  # 読み込み待ちだった 1 件を流す
            return
        parts = title.split()
        if not parts or parts[0] not in ("ok", "err") or self._current is None:
            return
        if parts[0] == "err":
            self._finish(None)
            return
        width, height = int(parts[2]), int(parts[3])
        # DOM 更新の一拍あとに撮る。すぐ撮ると前の絵が写る
        QTimer.singleShot(_GRAB_DELAY_MS, lambda: self._grab(width, height))

    def _grab(self, width: int, height: int) -> None:
        if self._view is None or self._current is None:
            return
        ratio = self._view.devicePixelRatio()
        shot = self._view.grab()
        pixmap = shot.copy(0, 0, round(width * ratio), round(height * ratio))
        pixmap.setDevicePixelRatio(ratio)
        self._finish(pixmap)

    def _finish(self, pixmap) -> None:
        if self._current is None:
            return
        self._results[self._current] = pixmap
        while len(self._results) > _CACHE_SIZE:
            self._results.popitem(last=False)
        self._current = None
        self.rendered.emit()
        self._pump()
