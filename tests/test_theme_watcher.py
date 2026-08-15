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


class TestModeChangeAlwaysNotifies:
    """モードが変われば、配色が同じでも通知する（ユーザー報告の続き）。

    受け手（`MainWindow._apply_palette`）は、この通知で **macOS への外観の
    申告を出し直す**。「ダーク → システムに合わせる」と戻したとき、OS も
    ダークなら配色は同じだが、**固定を解く必要がある**。配色が同じだからと
    黙っていると、固定されたまま残って OS の切り替えに追従しなくなる。
    """

    def test_配色が同じでもモードが変われば通知する(self, qapp, monkeypatch) -> None:
        import hitofude.app as app_module

        monkeypatch.setattr(app_module, "system_is_dark", lambda: True)
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.DARK)

        emitted: list = []
        watcher.changed.connect(emitted.append)
        watcher.set_mode(ThemeMode.SYSTEM)  # OS もダークなので配色は変わらない

        assert watcher.colors is DARK
        assert emitted == [DARK], "固定を解く合図が要る"

    def test_同じモードならやはり通知しない(self, qapp, monkeypatch) -> None:
        """R7: 無駄な rehighlight() は増やさない。"""
        import hitofude.app as app_module

        monkeypatch.setattr(app_module, "system_is_dark", lambda: True)
        watcher = ThemeWatcher()
        watcher.set_mode(ThemeMode.SYSTEM)

        emitted: list = []
        watcher.changed.connect(emitted.append)
        watcher.set_mode(ThemeMode.SYSTEM)
        assert emitted == []
