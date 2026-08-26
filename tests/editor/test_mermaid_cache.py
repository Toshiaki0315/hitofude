"""Mermaid 図の描画キャッシュ（I-1 / ADR-0021）。

QtWebEngine のオフスクリーン描画は非同期。`done()` で確定を待つ。
"""

import pytest

from hitofude.editor.mermaid_cache import MermaidCache

pytestmark = pytest.mark.gui

GRAPH = "graph TD\n  A[開始] --> B[終了]\n"


@pytest.fixture(scope="module")
def cache(qapp):
    return MermaidCache()


class TestRender:
    def test_図が絵になる(self, cache, qtbot) -> None:
        assert cache.pixmap(GRAPH, dark=False, max_width=600) is None  # まず依頼
        qtbot.waitUntil(lambda: cache.done(GRAPH, dark=False), timeout=30000)
        pixmap = cache.pixmap(GRAPH, dark=False, max_width=600)
        assert pixmap is not None
        assert pixmap.width() > 0 and pixmap.height() > 0

    def test_壊れた図は失敗を覚える(self, cache, qtbot) -> None:
        bad = "graph TD\n  A --> --> ;;\n"
        cache.pixmap(bad, dark=False, max_width=600)
        qtbot.waitUntil(lambda: cache.done(bad, dark=False), timeout=30000)
        assert cache.pixmap(bad, dark=False, max_width=600) is None
        assert cache.size(bad, dark=False, max_width=600) is None

    def test_二回目からは同じ絵(self, cache, qtbot) -> None:
        qtbot.waitUntil(lambda: cache.done(GRAPH, dark=False), timeout=30000)
        first = cache.pixmap(GRAPH, dark=False, max_width=6000)
        second = cache.pixmap(GRAPH, dark=False, max_width=6000)
        assert first is second

    def test_幅に収める(self, cache, qtbot) -> None:
        qtbot.waitUntil(lambda: cache.done(GRAPH, dark=False), timeout=30000)
        pixmap = cache.pixmap(GRAPH, dark=False, max_width=50)
        assert pixmap.width() / pixmap.devicePixelRatio() <= 50

    def test_描き上がると合図が飛ぶ(self, cache, qtbot) -> None:
        other = "graph LR\n  X --> Y\n"
        with qtbot.waitSignal(cache.rendered, timeout=30000):
            cache.pixmap(other, dark=False, max_width=600)


class TestGpuFlag:
    def test_ソフトウェア描画を強制する(self) -> None:
        """GPU 合成だと、画面に出していない view の grab() が真っ白になる
        （実機 cocoa で再現。ユーザー報告の「白い矩形」）。モジュールの
        import が --disable-gpu を確実に入れることを固定する。"""
        import importlib
        import os

        saved = os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        try:
            import hitofude.editor.mermaid_cache as module

            importlib.reload(module)
            assert "--disable-gpu" in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        finally:
            if saved is not None:
                os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = saved


class TestQuitBehavior:
    def test_隠しビューがアプリの終了を妨げない(self, cache, qtbot) -> None:
        """赤いバツでウィンドウを閉じてもアプリが Dock に残った（ユーザー報告）。

        描画用の隠し QWebEngineView がトップレベルウィンドウとして
        「開いたまま」になり、最後のウィンドウが閉じた扱いにならないため。
        WA_QuitOnClose を外して終了の勘定から除く。
        """
        from PySide6.QtCore import Qt

        view = cache._ensure_view()
        assert view.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose) is False


class TestWithoutWebEngine:
    """QtWebEngine が無い環境（ユーザー報告 2026-08-26。`.app` が起動しない）。

    Chromium は 500MB 級なので、同梱しない組み方があり得る。**無ければ
    図を諦めるだけ**で、アプリは動く。落ちてはいけない。
    """

    def test_図は諦めるが落ちない(self, qapp, qtbot, monkeypatch) -> None:
        from hitofude.editor import mermaid_cache as module

        def missing():
            raise ModuleNotFoundError("No module named 'PySide6.QtWebEngineWidgets'")

        monkeypatch.setattr(module, "web_engine_view_class", missing)
        found = MermaidCache()
        assert found.pixmap(GRAPH, dark=False, max_width=600) is None
        # 失敗として確定する（何度も試さない）。確定は**次のイベントループ**
        qtbot.waitUntil(lambda: found.done(GRAPH, dark=False), timeout=2000)

    def test_失敗の合図はハイライトの最中に飛ばさない(self, qapp, qtbot, monkeypatch) -> None:
        """ユーザー報告 2026-08-27。軽量版で Mermaid のノートを開くと落ちた。

        `pixmap()` はハイライト（highlightBlock）の中から呼ばれる。失敗を
        **同期で** rendered へ流すと、受け手が rehighlightBlock を呼んで
        ハイライトに再入し、QTextLayout::formats() で segfault する
        （crash report で確認）。合図はイベントループ経由で飛ばす。
        """
        from hitofude.editor import mermaid_cache as module

        def missing():
            raise ModuleNotFoundError("No module named 'PySide6.QtWebEngineWidgets'")

        monkeypatch.setattr(module, "web_engine_view_class", missing)
        found = MermaidCache()
        fired: list[bool] = []
        found.rendered.connect(lambda: fired.append(True))
        found.pixmap(GRAPH, dark=False, max_width=600)
        assert fired == [], "pixmap() の呼び出しの中で rendered が同期発火している"
        qtbot.waitUntil(lambda: bool(fired), timeout=2000)
