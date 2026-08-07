"""QApplication のセットアップとテーマ適用（spec §5.3）。"""

import sys
from typing import cast

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from hitofude import APP_NAME, ORG_DOMAIN, ORG_NAME, __version__
from hitofude.theme import ThemeColors, ThemeMode, colors_for

__all__ = [
    "APP_NAME",
    "ORG_DOMAIN",
    "ORG_NAME",
    "ThemeWatcher",
    "apply_theme",
    "create_application",
    "system_is_dark",
]


def system_is_dark() -> bool:
    """OS がダークモードかどうか。

    macOS のダークモード切り替えは `styleHints().colorSchemeChanged` で検知できる
    （Phase 2 で接続する）。ここでは現在値だけを読む。
    """
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply_theme(app: QApplication, theme: ThemeColors) -> None:
    """配色を QPalette へ流し込む。"""
    background = QColor(theme.background)
    foreground = QColor(theme.foreground)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.WindowText, foreground)
    palette.setColor(QPalette.ColorRole.Base, background)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.code_background))
    palette.setColor(QPalette.ColorRole.Text, foreground)
    palette.setColor(QPalette.ColorRole.ToolTipBase, background)
    palette.setColor(QPalette.ColorRole.ToolTipText, foreground)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.muted_foreground))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.selection_background))
    palette.setColor(QPalette.ColorRole.HighlightedText, foreground)
    palette.setColor(QPalette.ColorRole.Link, QColor(theme.accent))
    app.setPalette(palette)


def create_application(argv: list[str] | None = None) -> QApplication:
    """QApplication を用意する。

    QApplication は 1 プロセスに 1 つしか存在できないため、既にあれば再利用する
    （pytest-qt が先に生成しているケースがこれに当たる）。
    """
    existing = QApplication.instance()
    app = cast(QApplication, existing) if existing is not None else QApplication(argv or sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    app.setApplicationVersion(__version__)

    apply_theme(app, colors_for(ThemeMode.SYSTEM, system_is_dark=system_is_dark()))
    return app


class ThemeWatcher(QObject):
    """現在の配色を保持し、変わったときに通知する（spec §5.3）。

    `ThemeMode.SYSTEM` のときだけ OS のダークモード切り替えに追従する。
    ユーザーが明示的にライト/ダークを選んでいたら、OS が変わっても動かさない。

    配色の決定自体は GUI 非依存の `theme.colors_for()` が行い、ここは
    Qt のシグナルと繋ぐだけに留める。
    """

    changed = Signal(object)
    """新しい `ThemeColors` を載せて飛ぶ。"""

    def __init__(self, mode: ThemeMode = ThemeMode.SYSTEM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._colors = colors_for(mode, system_is_dark=system_is_dark())
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_qt_scheme_changed)

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    def set_mode(self, mode: ThemeMode) -> None:
        self._mode = mode
        self._update(colors_for(mode, system_is_dark=system_is_dark()))

    def _on_qt_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        self._on_system_scheme_changed(is_dark=scheme == Qt.ColorScheme.Dark)

    def _on_system_scheme_changed(self, *, is_dark: bool) -> None:
        self._update(colors_for(self._mode, system_is_dark=is_dark))

    def _update(self, colors: ThemeColors) -> None:
        # 同じ配色なら通知しない。受け手は rehighlight() するので、
        # 無駄な通知がそのまま全体再ハイライトになる（R7）。
        if colors is self._colors:
            return
        self._colors = colors
        self.changed.emit(colors)
