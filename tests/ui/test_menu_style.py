"""ポップアップメニューの見た目（ユーザー指摘 2026-08-24）。

**窮屈で角が立っている。** Qt が描く既定のメニューは、macOS のメニュー
（Finder やターミナルの右クリック）と並べると行が詰まり、角も丸くない。
押す前に読むものなので、OS のメニューと揃えて浮かないようにする。

配色は QPalette では足りない（余白と丸みは QSS でしか決められない）ので、
**メニューにだけ** QSS を当てる。本体の描画は変わらない（実測: 窓を
256 万画素比べて差 0）。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from hitofude.app import (
    MENU_ITEM_RADIUS,
    MENU_RADIUS,
    apply_theme,
    menu_style,
    style_menu,
)
from hitofude.theme import DARK, LIGHT

pytestmark = pytest.mark.gui


class TestStyleSheet:
    def test_角を丸める(self) -> None:
        assert f"border-radius: {MENU_RADIUS}px" in menu_style(LIGHT)

    def test_選んでいる行も丸める(self) -> None:
        """角の丸いメニューに角ばった帯は合わない。"""
        assert f"border-radius: {MENU_ITEM_RADIUS}px" in menu_style(LIGHT)

    def test_行に余白を取る(self) -> None:
        assert "QMenu::item" in menu_style(LIGHT)
        assert "padding" in menu_style(LIGHT)

    def test_テーマの色を使う(self) -> None:
        assert LIGHT.background in menu_style(LIGHT)
        assert DARK.background in menu_style(DARK)

    def test_区切り線もテーマの色(self) -> None:
        assert f"background-color: {DARK.rule}" in menu_style(DARK)


class TestApplied:
    """アプリが開くメニューに当たっているか。

    **`QApplication.setStyleSheet()` は使わない。** 描画は変わらないが、
    すべてのウィジェットが QSS 経由の描画に切り替わってとても高い
    （同じ試験が 5 秒 → 53 秒。実測）。開くところで 1 つずつ当てる。
    """

    def test_アプリ全体には置かない(self, qapp) -> None:
        apply_theme(qapp, LIGHT)
        assert "QMenu" not in qapp.styleSheet()

    def test_一覧の右クリック(self, window) -> None:
        note = window.vault.create("見本", "# 見本\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        menu = window._notes.context_menu_for(note.path.relative_to(window.vault.root))
        assert "border-radius" in menu.styleSheet()

    def test_歯車のメニュー(self, window) -> None:
        assert "border-radius" in window.menu_button.menu().styleSheet()

    def test_本文の右クリック(self, window) -> None:
        """中身は Qt が作るが、見た目はこちらで決める。"""
        menu = window.editor.build_context_menu()
        assert "border-radius" in menu.styleSheet()

    def test_今のテーマの色になる(self, window) -> None:
        from hitofude.theme import DARK

        window._apply_theme_now(DARK)
        menu = window.editor.build_context_menu()
        assert DARK.background in menu.styleSheet()


class TestRendering:
    """**本当に丸くなっているか**を絵で見る（文字列の検査だけでは足りない）。

    暗いテーマで見る。`QT_QPA_PLATFORM=offscreen` の `grab()` は alpha を
    持たない（`Format_RGB32`）ので、角が「抜けている」ことを透明度では
    確かめられない。**角が本体の色で塗られていない**ことで見る。
    実機（cocoa）では alpha=0 になることを別途確認した。
    """

    def menu(self, qapp) -> QMenu:
        menu = QMenu()
        style_menu(menu, DARK)
        for label in ("新しいフォルダ…", "Finder で開く", "名前を変更…"):
            menu.addAction(label)
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        menu.popup(qapp.primaryScreen().geometry().center())
        qapp.processEvents()
        return menu

    def test_四隅は本体の色で塗られていない(self, qapp) -> None:
        menu = self.menu(qapp)
        try:
            image = menu.grab().toImage()
            body = image.pixelColor(image.width() // 2, image.height() // 2)
            corners = (
                (0, 0),
                (image.width() - 1, 0),
                (0, image.height() - 1),
                (image.width() - 1, image.height() - 1),
            )
            for x, y in corners:
                assert image.pixelColor(x, y) != body, f"({x}, {y}) が角丸から出ている"
        finally:
            menu.hide()

    def test_中は暗いまま(self, qapp) -> None:
        """角だけが抜けている（全部が抜けているのではない）。

        色そのものは見ない。Qt は本体の上に薄い板を重ねることがある。
        """
        menu = self.menu(qapp)
        try:
            image = menu.grab().toImage()
            middle = image.pixelColor(image.width() // 2, image.height() // 2)
            assert middle.lightness() < 128, middle.name()
        finally:
            menu.hide()


class TestTooltip:
    """ツールチップは黒地に白（ユーザー要望 2026-08-24）。

    Claude Desktop に合わせた。**テーマでは変えない**——黒地に白は明暗
    どちらでも読めるし、本文と同じ色だと「浮いている小さな窓」に見えない。

    **スタイルシートは使わない。** 角丸と余白は QSS でしか書けないが、
    置ける場所がどこも壊れる（`app.apply_tooltip_colors` に実測を書いた）。
    """

    def colors(self, qapp):
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QToolTip

        from hitofude.app import apply_tooltip_colors

        apply_tooltip_colors()
        palette = QToolTip.palette()
        return (
            palette.color(QPalette.ColorRole.ToolTipBase).name().upper(),
            palette.color(QPalette.ColorRole.ToolTipText).name().upper(),
        )

    def test_黒地に白(self, qapp) -> None:
        from hitofude.app import TOOLTIP_BACKGROUND, TOOLTIP_FOREGROUND

        assert self.colors(qapp) == (TOOLTIP_BACKGROUND.upper(), TOOLTIP_FOREGROUND.upper())

    def test_テーマを変えても黒地のまま(self, qapp) -> None:
        """`apply_theme` はアプリのパレットを塗るが、`QToolTip` の指定が勝つ。"""
        from hitofude.app import TOOLTIP_BACKGROUND, apply_tooltip_colors

        apply_tooltip_colors()
        apply_theme(qapp, LIGHT)
        assert self.colors(qapp)[0] == TOOLTIP_BACKGROUND.upper()
        apply_theme(qapp, DARK)
        assert self.colors(qapp)[0] == TOOLTIP_BACKGROUND.upper()

    def test_スタイルシートには触らない(self, qapp, window) -> None:
        """**置ける場所がどこも壊れる**（アプリ全体は落ちる、窓はテーマの
        伝播が止まる）。触っていないことを固定する。"""
        from hitofude.app import apply_tooltip_colors

        apply_tooltip_colors()
        assert "QToolTip" not in qapp.styleSheet()
        assert "QToolTip" not in window.styleSheet()


class TestTooltipMargin:
    """ツールチップの内側に余白を作る（ユーザー要望 2026-08-24）。

    Qt の既定は 0 で、文字が縁に貼り付いて窮屈に見える。**スタイルの
    寸法値**（`PM_ToolTipLabelFrameWidth`）を差し替えて作る——スタイル
    シートは置ける場所がどこも壊れるため（`TestTooltip` の説明）。
    """

    def test_余白の寸法値を返す(self, qapp) -> None:
        from PySide6.QtWidgets import QStyle

        from hitofude.app import TOOLTIP_MARGIN, apply_tooltip_margin

        apply_tooltip_margin(qapp)
        assert (
            qapp.style().pixelMetric(QStyle.PixelMetric.PM_ToolTipLabelFrameWidth) == TOOLTIP_MARGIN
        )

    def test_他の寸法は元のまま(self, qapp) -> None:
        """**ツールチップ以外には触らない。** 元のスタイルへそのまま渡す。"""
        from PySide6.QtWidgets import QStyle

        from hitofude.app import _RoomyTooltipStyle, apply_tooltip_margin

        apply_tooltip_margin(qapp)
        wrapper = qapp.style()
        assert isinstance(wrapper, _RoomyTooltipStyle)
        base = wrapper.baseStyle()
        for metric in (
            QStyle.PixelMetric.PM_ButtonMargin,
            QStyle.PixelMetric.PM_MenuPanelWidth,
            QStyle.PixelMetric.PM_ScrollBarExtent,
            QStyle.PixelMetric.PM_SmallIconSize,
        ):
            assert wrapper.pixelMetric(metric) == base.pixelMetric(metric), metric

    def test_二度入れない(self, qapp) -> None:
        """包み直すと、寸法の問い合わせが Python を通る回数だけ増える。"""
        from hitofude.app import apply_tooltip_margin

        apply_tooltip_margin(qapp)
        first = qapp.style()
        apply_tooltip_margin(qapp)
        assert qapp.style() is first
