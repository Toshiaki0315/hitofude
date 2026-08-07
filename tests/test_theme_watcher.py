"""OS のダークモード追従のテスト（タスク 2-10 / spec §5.3）。"""

import pytest

from hitofude.app import ThemeWatcher
from hitofude.theme import DARK, LIGHT, ThemeMode

pytestmark = pytest.mark.gui


class TestThemeWatcher:
    def test_既定はシステム追従(self, qapp) -> None:
        watcher = ThemeWatcher()
        assert watcher.mode is ThemeMode.SYSTEM

    def test_モードを固定すると配色が決まる(self, qapp) -> None:
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.DARK)
        assert watcher.colors is DARK
        watcher.set_mode(ThemeMode.LIGHT)
        assert watcher.colors is LIGHT

    def test_変更時にシグナルを出す(self, qapp, qtbot) -> None:
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.LIGHT)
        with qtbot.waitSignal(watcher.changed, timeout=500) as blocker:
            watcher.set_mode(ThemeMode.DARK)
        assert blocker.args == [DARK]

    def test_同じモードなら通知しない(self, qapp) -> None:
        """無駄な rehighlight() を避ける（R7）。"""
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.LIGHT)
        emitted: list = []
        watcher.changed.connect(emitted.append)
        watcher.set_mode(ThemeMode.LIGHT)
        assert emitted == []

    def test_システム追従中はOSの切り替えに反応する(self, qapp) -> None:
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.SYSTEM)
        emitted: list = []
        watcher.changed.connect(emitted.append)

        watcher._on_system_scheme_changed(is_dark=True)
        assert watcher.colors is DARK
        assert emitted == [DARK]

        watcher._on_system_scheme_changed(is_dark=False)
        assert watcher.colors is LIGHT

    def test_固定モード中はOSの切り替えを無視する(self, qapp) -> None:
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.LIGHT)
        emitted: list = []
        watcher.changed.connect(emitted.append)

        watcher._on_system_scheme_changed(is_dark=True)
        assert watcher.colors is LIGHT
        assert emitted == []
