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
