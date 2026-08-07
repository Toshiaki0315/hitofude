"""メインウィンドウのテスト（タスク 0-B-3 / spec §5.1）。

Phase 0 では「起動して表示される」ところまで。3 ペイン構成は Phase 5（5-1）。
"""

import pytest
from pytestqt.qtbot import QtBot

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_ウィンドウが生成され表示できる(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()


def test_ウィンドウタイトルがアプリ名である(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Hitofude"


def test_最小サイズが3ペインを置ける幅を確保している(qtbot: QtBot) -> None:
    """spec §5.1: サイドバー 180px + ノートリスト 280px + エディタ。"""
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.minimumWidth() >= 180 + 280
