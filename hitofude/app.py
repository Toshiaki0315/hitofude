"""QApplication のセットアップとテーマ適用（spec §5.3）。"""

import sys
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from hitofude import APP_NAME, ORG_DOMAIN, ORG_NAME, __version__
from hitofude.theme import ThemeColors, ThemeMode, colors_for

__all__ = [
    "APP_NAME",
    "ORG_DOMAIN",
    "ORG_NAME",
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
