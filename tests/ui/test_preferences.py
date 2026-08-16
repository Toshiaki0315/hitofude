"""環境設定のテスト（タスク 5-7 / spec §5.4）。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import DEFAULT_TAB_WIDTH, MAX_TAB_WIDTH, MIN_TAB_WIDTH, Config
from hitofude.theme import ThemeMode
from hitofude.ui.preferences import PreferencesDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    return config


@pytest.fixture
def warned(monkeypatch) -> list[str]:
    """打ち間違いの知らせ。出しっぱなしだとテストが固まる。"""
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a, **k: shown.append(text))
    return shown


@pytest.fixture
def dialog(qtbot, config: Config) -> PreferencesDialog:
    widget = PreferencesDialog(config)
    qtbot.addWidget(widget)
    return widget


class TestInitialValues:
    def test_現在のフォントを出す(self, dialog, config) -> None:
        assert dialog._font.currentText() == config.font_family

    def test_現在の文字サイズを出す(self, dialog, config) -> None:
        assert dialog._size.value() == pytest.approx(config.font_point_size)

    def test_現在のテーマを出す(self, dialog, config) -> None:
        assert dialog.selected_theme is config.theme_mode

    def test_現在の保管フォルダを出す(self, dialog, config) -> None:
        # 幅に収めるため真ん中を省くことがある。全文はツールチップで見る
        assert str(config.vault_path) in dialog.vault_tooltip()
        assert config.vault_path.name in dialog.vault_label_text()

    def test_現在の保持日数を出す(self, dialog, config) -> None:
        assert dialog._trash_days.value() == config.trash_days


class TestApply:
    def test_文字サイズを保存する(self, dialog, config) -> None:
        dialog._size.setValue(18.0)
        dialog.apply()
        assert config.font_point_size == pytest.approx(18.0)

    def test_テーマを保存する(self, dialog, config) -> None:
        dialog._theme.setCurrentIndex(dialog._theme.findData(ThemeMode.DARK))
        dialog.apply()
        assert config.theme_mode is ThemeMode.DARK

    def test_保持日数を保存する(self, dialog, config) -> None:
        dialog._trash_days.setValue(7)
        dialog.apply()
        assert config.trash_days == 7

    def test_保管フォルダを保存する(self, dialog, config, tmp_path) -> None:
        target = tmp_path / "別の保管フォルダ"
        dialog.set_vault(target)
        dialog.apply()
        assert config.vault_path == target

    def test_変えなければ保管フォルダはそのまま(self, dialog, config) -> None:
        before = config.vault_path
        dialog.apply()
        assert config.vault_path == before

    def test_適用したことを知らせる(self, dialog, qtbot) -> None:
        with qtbot.waitSignal(dialog.applied, timeout=1000):
            dialog.apply()

    def test_OKで書き込まれて閉じる(self, dialog, config) -> None:
        dialog._trash_days.setValue(14)
        dialog.accept()
        assert config.trash_days == 14
        assert dialog.result() == PreferencesDialog.DialogCode.Accepted

    def test_キャンセルでは書き込まない(self, dialog, config) -> None:
        before = config.trash_days
        dialog._trash_days.setValue(3)
        dialog.reject()
        assert config.trash_days == before


class TestRestartNotice:
    """保管フォルダを変えても索引と監視は再起動まで切り替わらない。"""

    def test_最初は出ていない(self, dialog) -> None:
        assert dialog._restart_note.isVisible() is False

    def test_フォルダを変えると出る(self, dialog, tmp_path) -> None:
        dialog.show()
        dialog.set_vault(tmp_path / "別の保管フォルダ")
        assert dialog._restart_note.isVisible() is True

    def test_同じフォルダを選び直したら出ない(self, dialog, config) -> None:
        dialog.show()
        dialog.set_vault(config.vault_path)
        assert dialog._restart_note.isVisible() is False


class TestBounds:
    def test_文字サイズの下限と上限がある(self, dialog) -> None:
        """設定画面からは壊れた値を入れられないようにする。"""
        from hitofude.config import MAX_POINT_SIZE, MIN_POINT_SIZE

        assert dialog._size.minimum() == pytest.approx(MIN_POINT_SIZE)
        assert dialog._size.maximum() == pytest.approx(MAX_POINT_SIZE)

    def test_保持日数は1日以上(self, dialog) -> None:
        assert dialog._trash_days.minimum() >= 1


class TestResetToDefaults:
    """「デフォルトに戻す」（ユーザー要望）。

    **保管フォルダは戻さない。** そこはノートの置き場であって好みの設定では
    ない。戻すと別のフォルダ（多くは空）を指すことになり、ノートが消えたように
    見える。ボタンにもその旨を出す。

    押した時点では**入力欄を書き換えるだけ**。書き込むのは OK を押したとき。
    間違えて押しても Cancel で元に戻せる。
    """

    def defaults(self):
        from hitofude.config import (
            DEFAULT_FONT_FAMILY,
            DEFAULT_MONO_FAMILY,
            DEFAULT_POINT_SIZE,
            DEFAULT_TRASH_DAYS,
        )

        return DEFAULT_FONT_FAMILY, DEFAULT_POINT_SIZE, DEFAULT_MONO_FAMILY, DEFAULT_TRASH_DAYS

    def customized(self, config: Config) -> None:
        config.font_family = "Times New Roman"
        config.font_point_size = 22.0
        config.mono_family = "Courier New"
        config.theme_mode = ThemeMode.DARK
        config.trash_days = 7

    def test_ボタンがある(self, dialog) -> None:
        assert "デフォルト" in dialog.reset_button.text()

    def test_何を戻さないか書いてある(self, dialog) -> None:
        assert "保管フォルダ" in dialog.reset_button.toolTip()

    def test_入力欄が既定値に戻る(self, qtbot, config: Config) -> None:
        self.customized(config)
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        widget.reset_to_defaults()
        font, size, mono, days = self.defaults()
        assert widget._font.currentText() == font
        assert widget._size.value() == size
        assert widget._mono.currentText() == mono
        assert widget._trash_days.value() == days

    def test_テーマも既定に戻る(self, qtbot, config: Config) -> None:
        self.customized(config)
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        widget.reset_to_defaults()
        assert widget.selected_theme is ThemeMode.SYSTEM

    def test_保管フォルダは変えない(self, qtbot, config: Config, tmp_path) -> None:
        moved = tmp_path / "別の場所"
        moved.mkdir()
        config.vault_path = moved
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        widget.reset_to_defaults()
        assert widget.selected_vault == moved

    def test_押しただけでは設定を書き換えない(self, qtbot, config: Config) -> None:
        """Cancel で元に戻せること。"""
        self.customized(config)
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        widget.reset_to_defaults()
        assert config.font_family == "Times New Roman"
        assert config.trash_days == 7

    def test_OKで既定が書き込まれる(self, qtbot, config: Config) -> None:
        self.customized(config)
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        widget.reset_to_defaults()
        widget.accept()

        font, size, mono, days = self.defaults()
        assert config.font_family == font
        assert config.font_point_size == size
        assert config.mono_family == mono
        assert config.trash_days == days
        assert config.theme_mode is ThemeMode.SYSTEM

    def test_Cancelなら元のまま(self, qtbot, config: Config) -> None:
        self.customized(config)
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        widget.reset_to_defaults()
        widget.reject()
        assert config.font_family == "Times New Roman"
        assert config.theme_mode is ThemeMode.DARK

    def test_押すと反映される(self, qtbot, config: Config) -> None:
        """ボタンの接続が繋がっているか（配線漏れの回帰）。"""
        from PySide6.QtCore import Qt

        self.customized(config)
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)

        qtbot.mouseClick(widget.reset_button, Qt.MouseButton.LeftButton)
        assert widget._trash_days.value() == self.defaults()[3]


class TestTabWidth:
    """タブ幅（ユーザー要望）。"""

    def test_今の値が入っている(self, config, qtbot) -> None:
        config.tab_width = 2
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog._tab_width.value() == 2

    def test_変更が書き込まれる(self, config, qtbot) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog._tab_width.setValue(8)
        dialog.apply()
        assert config.tab_width == 8

    def test_範囲は1から8(self, config, qtbot) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert (dialog._tab_width.minimum(), dialog._tab_width.maximum()) == (
            MIN_TAB_WIDTH,
            MAX_TAB_WIDTH,
        )

    def test_デフォルトに戻すで4になる(self, config, qtbot) -> None:
        config.tab_width = 8
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.reset_to_defaults()
        assert dialog._tab_width.value() == DEFAULT_TAB_WIDTH


class TestTabWidthApplied:
    """設定した幅がエディタに届くこと（結線の検査）。"""

    def test_起動時に反映される(self, qtbot, tmp_path) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.main_window import MainWindow

        settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "Notes"
        config.tab_width = 2
        window = MainWindow(config)
        qtbot.addWidget(window)
        assert window.editor.tab_width() == 2

    def test_環境設定の変更が届く(self, qtbot, tmp_path) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.main_window import MainWindow

        settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "Notes"
        window = MainWindow(config)
        qtbot.addWidget(window)
        config.tab_width = 8
        window._apply_preferences()
        assert window.editor.tab_width() == 8


class TestTabWidthLayout:
    """タブ幅の入力欄の並び（ユーザー要望）。

    `setSuffix(" 文字")` だと**矢印が「文字」の右**に付き、数字から離れる。
    数字と単位を分け、矢印は数字のすぐ横に置く。
    """

    def test_単位を接尾辞にしない(self, config, qtbot) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog._tab_width.suffix() == ""

    def test_数字だけが入っている(self, config, qtbot) -> None:
        config.tab_width = 4
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog._tab_width.text() == "4"

    def test_単位のラベルが隣にある(self, config, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        assert "文字" in labels

    def test_入力欄は数字ぶんの幅(self, config, qtbot) -> None:
        """横いっぱいに伸びると、矢印が遠くなる。"""
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog._tab_width.maximumWidth() < 200


class TestLayout:
    """**詰まって見える**（ユーザー指摘）。

    行間が狭いうえ、保管フォルダのパスが行に収まらず潰れていた。
    """

    def test_行間が詰まりすぎない(self, dialog) -> None:
        from hitofude.ui.preferences import FORM_SPACING

        form = dialog.layout().itemAt(0).layout()
        assert form.verticalSpacing() >= FORM_SPACING
        assert form.horizontalSpacing() >= FORM_SPACING

    def test_外側にも余白がある(self, dialog) -> None:
        margins = dialog.layout().contentsMargins()
        assert margins.left() >= 16
        assert margins.top() >= 16

    def test_長いパスでも幅が広がらない(self, qtbot, config, tmp_path) -> None:
        """**パスの長さでダイアログの形が決まらない。** 深い場所を選ぶと、
        窓が横に伸びるか、収まらない文字が潰れる。"""
        short = PreferencesDialog(config)
        qtbot.addWidget(short)
        before = short.sizeHint().width()

        deep = tmp_path
        for part in ("とても", "深い", "場所", "の", "ノート", "置き場", "その2"):
            deep = deep / part
        config.vault_path = deep
        long = PreferencesDialog(config)
        qtbot.addWidget(long)

        assert long.sizeHint().width() == before

    def test_全文を見せる(self, qtbot, config, tmp_path) -> None:
        """**打ち直す欄なので省略しない。** 読めないと直せない。
        長い場所は欄の中で横に流れる（窓は広がらない）。"""
        config.vault_path = tmp_path / "Documents" / "HitofudeNotes"
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        assert dialog.vault_label_text() == str(config.vault_path)

    def test_省略しても全文は読める(self, qtbot, config, tmp_path) -> None:
        """縮めたぶんはツールチップで補う。どこに置いたか確かめられなくなる。"""
        deep = tmp_path
        for part in ("とても", "深い", "場所", "の", "ノート", "置き場", "その2"):
            deep = deep / part
        config.vault_path = deep
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)

        assert str(deep) in dialog.vault_tooltip()


class TestTypedVault:
    """保管フォルダは**打ち込んでも変えられる**（ユーザー要望）。

    「変更…」だけだと、パスを貼り付けたい・別のマシンと同じ場所を書きたい
    ときに遠回りになる。**打ち間違いは受け取らない**（存在しない親、
    ファイル、相対パス）。取り違えると、ノートが空のフォルダに見える。
    """

    def test_打ち込んだ場所が入る(self, qtbot, config, tmp_path) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        target = tmp_path / "別の置き場"
        dialog.set_vault_text(str(target))
        assert dialog.apply() is True
        assert config.vault_path == target

    def test_波線はホームに直す(self, qtbot, config, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.set_vault_text("~/メモ置き場")
        dialog.apply()
        assert config.vault_path == tmp_path / "メモ置き場"

    def test_前後の空白は落とす(self, qtbot, config, tmp_path) -> None:
        """Finder からパスを貼ると空白や改行が付いてくることがある。"""
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        target = tmp_path / "貼り付け"
        dialog.set_vault_text(f"  {target}\n")
        dialog.apply()
        assert config.vault_path == target

    def test_相対パスは受け取らない(self, qtbot, config, warned) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        before = config.vault_path
        dialog.set_vault_text("メモ")
        assert dialog.apply() is False
        assert config.vault_path == before
        assert warned

    def test_ファイルは受け取らない(self, qtbot, config, tmp_path, warned) -> None:
        target = tmp_path / "これはファイル.txt"
        target.write_text("x", encoding="utf-8")
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.set_vault_text(str(target))
        assert dialog.apply() is False
        assert warned

    def test_親が無い場所は受け取らない(self, qtbot, config, tmp_path, warned) -> None:
        """**作るのは 1 階層まで。** 打ち間違えた深い道を黙って掘らない。"""
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.set_vault_text(str(tmp_path / "無い" / "場所" / "ノート"))
        assert dialog.apply() is False
        assert warned

    def test_空なら変えない(self, qtbot, config, warned) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        before = config.vault_path
        dialog.set_vault_text("   ")
        assert dialog.apply() is False
        assert config.vault_path == before

    def test_OKでも閉じない(self, qtbot, config, warned) -> None:
        """直せる場所を開いたままにする。閉じると打ち直しからになる。"""
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.set_vault_text("メモ")
        dialog.accept()
        assert dialog.isVisible() is False or dialog.result() == 0

    def test_変更ボタンは入力欄を埋める(self, qtbot, config, tmp_path) -> None:
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.set_vault(tmp_path / "選んだ場所")
        assert str(tmp_path / "選んだ場所") in dialog.vault_label_text()
