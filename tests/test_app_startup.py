"""起動の下ごしらえ（ユーザー報告 2026-08-26）。

`.app` に QtWebEngine を同梱しない組み方だと、`app.py` の**先読み import**
が ModuleNotFoundError を投げてアプリごと死んでいた（py2app の
"Launch error" ダイアログ）。図が出ないのは構わないが、起動しないのは困る。
"""

import pytest

from hitofude import app as app_module

pytestmark = pytest.mark.gui


class TestPreloadWebEngine:
    def test_あれば真(self, qapp) -> None:
        """開発環境には入っている（`uv sync` が入れる）。"""
        assert app_module.preload_web_engine() is True

    def test_無くても落ちない(self, qapp, monkeypatch) -> None:
        def missing(name: str):
            raise ModuleNotFoundError(f"No module named {name!r}")

        monkeypatch.setattr(app_module.importlib, "import_module", missing)
        assert app_module.preload_web_engine() is False


class TestLiteSwitch:
    """`make run-lite`（ユーザー要望 2026-08-27）。

    軽量版の動きをソースから試す。開発環境には QtWebEngine が入っている
    ので、環境変数 HITOFUDE_LITE で「無いふり」をする。
    """

    def test_立っていればWebEngineを読みに行かない(self, qapp, monkeypatch) -> None:
        monkeypatch.setenv("HITOFUDE_LITE", "1")

        def boom(name: str):
            raise AssertionError("軽量版の切替中は import してはいけない")

        monkeypatch.setattr(app_module.importlib, "import_module", boom)
        assert app_module.preload_web_engine() is False

    def test_図の描画も諦める(self, qapp, qtbot, monkeypatch) -> None:
        monkeypatch.setenv("HITOFUDE_LITE", "1")
        from hitofude.editor.mermaid_cache import MermaidCache

        cache = MermaidCache()
        graph = "graph TD\n  A --> B\n"
        assert cache.pixmap(graph, dark=False, max_width=600) is None
        qtbot.waitUntil(lambda: cache.done(graph, dark=False), timeout=2000)
        assert cache.pixmap(graph, dark=False, max_width=600) is None
