"""行間の設定（ユーザー要望）。

サイドバーと一覧の行間を、環境設定から**意味で選ぶ**。

**px の数値では出さない。** 行間の効き方は文字サイズと連れ立って変わるので、
生の数値を出すと「文字を大きくしたら詰まって見えるから、また px を直す」に
なる。3 つの名前で選べば、中で字送りから計算できる。
"""

import pytest
from PySide6.QtGui import QFontMetrics

from hitofude.config import LineSpacing
from hitofude.ui.main_window import MainWindow
from hitofude.ui.preferences import PreferencesDialog
from hitofude.ui.sidebar import padding_for

pytestmark = pytest.mark.gui


def sidebar_height(window: MainWindow) -> int:
    model = window.sidebar.model()
    return model.item(0).sizeHint().height()


class TestConfig:
    def test_既定はふつう(self, config) -> None:
        assert config.line_spacing is LineSpacing.NORMAL

    def test_選んだものが残る(self, config) -> None:
        config.line_spacing = LineSpacing.RELAXED
        assert config.line_spacing is LineSpacing.RELAXED

    def test_壊れた値は既定へ戻す(self, config) -> None:
        """設定ファイルは手で編集されうる。変な値で起動できなくならない。"""
        config.settings.setValue("layout/line_spacing", "ばーん")
        assert config.line_spacing is LineSpacing.NORMAL

    def test_ふつうは今までと同じ(self) -> None:
        """**既存の見た目を変えない。** 設定を足したこと自体で
        今まで使っている人の画面が動いてはいけない。"""
        assert padding_for(LineSpacing.NORMAL) == 5


class TestApply:
    def test_ゆったりにすると行が高くなる(self, window) -> None:
        before = sidebar_height(window)
        window.config.line_spacing = LineSpacing.RELAXED
        window._apply_preferences()
        assert sidebar_height(window) > before

    def test_詰めると行が低くなる(self, window) -> None:
        before = sidebar_height(window)
        window.config.line_spacing = LineSpacing.TIGHT
        window._apply_preferences()
        assert sidebar_height(window) < before

    def test_字送りから決める(self, window) -> None:
        """`height()` ではなく `lineSpacing()`。日本語で詰まらないため。"""
        window.config.line_spacing = LineSpacing.RELAXED
        window._apply_preferences()
        metrics = QFontMetrics(window.sidebar.font())
        expected = metrics.lineSpacing() + padding_for(LineSpacing.RELAXED) * 2
        assert sidebar_height(window) == expected

    def test_一覧の行にも効く(self, window) -> None:
        from PySide6.QtWidgets import QStyleOptionViewItem

        def hint() -> int:
            option = QStyleOptionViewItem()
            option.font = window.note_list.font()
            option.rect = window.note_list.viewport().rect()
            index = window.note_list.model().index(0)
            return window.note_list.itemDelegate().sizeHint(option, index).height()

        before = hint()
        window.config.line_spacing = LineSpacing.RELAXED
        window._apply_preferences()
        assert hint() > before

    def test_タグを引き直しても保たれる(self, window) -> None:
        """索引が更新されるとサイドバーは組み直される。そこで戻っては困る。"""
        window.config.line_spacing = LineSpacing.RELAXED
        window._apply_preferences()
        expected = sidebar_height(window)
        window.refresh()
        assert sidebar_height(window) == expected


class TestDialog:
    def test_行間の欄がある(self, qtbot, config) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog.line_spacing is LineSpacing.NORMAL

    def test_名前で選ばせる(self, qtbot, config) -> None:
        """px の数値は出さない（文字サイズと連れ立って効き方が変わる）。"""
        from hitofude.ui.preferences import SPACING_LABELS

        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        labels = [dialog._spacing.itemText(i) for i in range(dialog._spacing.count())]
        assert labels == list(SPACING_LABELS.values())
        assert not any(any(c.isdigit() for c in label) for label in labels)

    def test_選ぶと保存される(self, qtbot, config) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog._spacing.setCurrentIndex(dialog._spacing.findData(LineSpacing.TIGHT))
        dialog.apply()
        assert config.line_spacing is LineSpacing.TIGHT

    def test_既定へ戻すでふつうに戻る(self, qtbot, config) -> None:
        config.line_spacing = LineSpacing.TIGHT
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.reset_to_defaults()
        assert dialog.line_spacing is LineSpacing.NORMAL
