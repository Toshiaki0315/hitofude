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


class TestNumberFields:
    """数字を打つ欄（ユーザー要望 2026-08-24）。

    **単位は欄の外に出す。** 接尾辞にすると矢印が単位の右に付いて数字から
    離れる（タブ幅で先に直した話と同じ）。
    **短くしない。** 桁が増えると数字が矢印にぶつかって読みにくい。
    """

    def boxes(self, dialog) -> dict:
        return {
            "文字サイズ": dialog._size,
            "タブ幅": dialog._tab_width,
            "ゴミ箱の保持": dialog._trash_days,
            "ポート": dialog.port_box,
            "応答待ち時間": dialog.timeout_box,
        }

    def with_unit(self, dialog) -> dict:
        """単位のラベルが隣に付く欄。ポートには単位が無い。"""
        return {name: box for name, box in self.boxes(dialog).items() if name != "ポート"}

    def test_単位を欄の中に入れない(self, dialog) -> None:
        for name, box in self.boxes(dialog).items():
            assert box.suffix() == "", f"「{name}」の単位が欄の中にある"

    def test_数字だけが入っている(self, dialog) -> None:
        assert dialog._size.text().replace(".", "").isdigit()
        assert dialog._trash_days.text().isdigit()

    def test_単位のラベルが隣にある(self, dialog) -> None:
        from PySide6.QtWidgets import QLabel

        labels = [w.text() for w in dialog.findChildren(QLabel)]
        assert "pt" in labels
        assert "日" in labels

    def test_窮屈にしない(self, dialog) -> None:
        """桁が増えても数字が矢印にぶつからない（保持日数は 4 桁まで入る）。"""
        for name, box in self.boxes(dialog).items():
            assert box.width() > box.sizeHint().width(), f"「{name}」の欄が短い"
        assert dialog.port_box.width() >= 100

    def test_単位のある欄は端を半分にする(self, dialog) -> None:
        """**単位が外に出ているぶん、欄は短くて足りる**（ユーザー要望
        2026-08-24）。数字の左に残る余りを半分に詰める。"""
        for name, box in self.with_unit(dialog).items():
            assert 78 <= box.width() < dialog.port_box.width(), f"「{name}」の幅"

    def test_横いっぱいには伸ばさない(self, dialog) -> None:
        """伸ばすと矢印が数字から遠くなる。"""
        for name, box in self.boxes(dialog).items():
            assert box.maximumWidth() < 200, f"「{name}」の欄が長い"

    def test_単位のある欄は同じ幅(self, dialog) -> None:
        """**同じ列で長さがばらつかない**（ユーザー指摘 2026-08-24）。"""
        widths = {box.width() for box in self.with_unit(dialog).values()}
        assert len(widths) == 1, f"幅がばらばら: {widths}"

    def test_単位のある欄は右に寄せる(self, dialog) -> None:
        """**数字を単位の隣に置く**（ユーザー要望 2026-08-24）。左に寄せると
        欄を長くしたぶん数字と単位のあいだが空き、別々のものに見える。"""
        from PySide6.QtCore import Qt

        for name, box in self.with_unit(dialog).items():
            assert box.alignment() & Qt.AlignmentFlag.AlignRight, f"「{name}」が右に寄っていない"

    def test_単位が無い欄は寄せない(self, dialog) -> None:
        """ポートには単位が無いので、寄せる相手がいない。"""
        from PySide6.QtCore import Qt

        assert not (dialog.port_box.alignment() & Qt.AlignmentFlag.AlignRight)


class TestLayout:
    """**詰まって見える**（ユーザー指摘 2026-08-16 / 2026-08-24）。

    1 度目は行間の狭さとパスの潰れ。2 度目の指摘では、行の間隔ではなく
    **9 行がのっぺり並ぶこと**が窮屈さの中身だったので、節に切って
    見出しと短い説明を付けた。
    """

    def pages(self, dialog) -> list:
        return [dialog.tabs.widget(i) for i in range(dialog.tabs.count())]

    def test_行間が詰まりすぎない(self, dialog) -> None:
        """**どのページのどの節も詰まっていない**（節に分かれた）。"""
        from PySide6.QtWidgets import QFormLayout

        from hitofude.ui.preferences import LABEL_GAP, ROW_SPACING

        forms = [form for page in self.pages(dialog) for form in page.findChildren(QFormLayout)]
        assert forms, "ページが無い"
        for form in forms:
            assert form.verticalSpacing() >= ROW_SPACING
            assert form.horizontalSpacing() >= LABEL_GAP

    def test_ページの内側にも余白がある(self, dialog) -> None:
        """タブの枠に文字が貼り付くと窮屈に見える。"""
        margins = dialog.tabs.widget(0).layout().contentsMargins()
        assert margins.left() >= 16

    def test_外側にも余白がある(self, dialog) -> None:
        margins = dialog.layout().contentsMargins()
        assert margins.left() >= 16
        assert margins.top() >= 16

    def test_どのページも節に分かれている(self, dialog) -> None:
        """**のっぺり並べない。** 見出しがあると探すときに目が止まる。"""
        for index in range(dialog.tabs.count()):
            assert len(dialog.sections(index)) >= 2

    def test_節には短い説明が付く(self, dialog) -> None:
        """見出しだけでは何の設定か分からない（参考にした画面もそうなっている）。"""
        for index in range(dialog.tabs.count()):
            for title, note in dialog.sections(index):
                assert note.strip(), f"「{title}」に説明が無い"

    def test_節と節のあいだが空く(self, dialog) -> None:
        """**行の間隔より節の間隔を広く取る。** そうしないと切れ目が見えない。"""
        from hitofude.ui.preferences import SECTION_GAP, SECTION_TITLE

        for index in range(dialog.tabs.count()):
            layout = dialog.tabs.widget(index).layout()
            gaps = 0
            for i in range(1, layout.count()):
                widget = layout.itemAt(i).widget()
                if widget is None or widget.objectName() != SECTION_TITLE:
                    continue
                before = layout.itemAt(i - 1)
                assert before.spacerItem() is not None, "見出しの前に間が無い"
                assert before.sizeHint().height() >= SECTION_GAP
                gaps += 1
            assert gaps >= 1, "節の切れ目が無い"

    def test_窓に広さがある(self, dialog) -> None:
        """**入力欄が横に潰れない広さ**（487px では保管フォルダが溢れていた）。"""
        assert dialog.minimumWidth() >= 560

    def test_入力欄の右端が揃う(self, dialog) -> None:
        """**幅がばらばらだと右端がぎざぎざになる**（参考画面は揃っている）。"""
        from hitofude.ui.preferences import FIELD_WIDTH

        for box in (dialog._font, dialog._mono, dialog._theme, dialog._content_width):
            assert box.minimumWidth() >= FIELD_WIDTH

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


class TestDialogCleanup:
    """exec() したダイアログを親の子リストに溜めない。

    QFontComboBox ×2（フォント列挙を持つ重いウィジェット）を抱えた
    ダイアログが、開くたびに MainWindow の子として残っていた。
    """

    def test_閉じたダイアログは破棄される(self, qtbot, tmp_path, monkeypatch) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.main_window import MainWindow
        from hitofude.ui.preferences import PreferencesDialog

        settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "Notes"
        window = MainWindow(config)
        qtbot.addWidget(window)

        monkeypatch.setattr(PreferencesDialog, "exec", lambda self: 0)
        window.open_preferences()
        window.open_preferences()

        # deleteLater は制御がイベントループへ戻ったときに効く
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert window.findChildren(PreferencesDialog) == []
        window.close()


class TestContentWidth:
    """本文の幅（I-3 / ADR-0018)。行間と同じ「名前から値」方式。"""

    def test_選択肢は3つ(self, dialog) -> None:
        from hitofude.config import ContentWidth

        values = [dialog._content_width.itemData(i) for i in range(dialog._content_width.count())]
        assert values == [ContentWidth.STANDARD, ContentWidth.WIDE, ContentWidth.FULL]

    def test_OKで設定に書かれる(self, dialog, config) -> None:
        from hitofude.config import ContentWidth

        dialog._content_width.setCurrentIndex(dialog._content_width.findData(ContentWidth.WIDE))
        assert dialog.apply() is True
        assert config.content_width is ContentWidth.WIDE

    def test_初期値は設定から(self, qtbot, config) -> None:
        from hitofude.config import ContentWidth
        from hitofude.ui.preferences import PreferencesDialog

        config.content_width = ContentWidth.FULL
        widget = PreferencesDialog(config)
        qtbot.addWidget(widget)
        assert widget._content_width.currentData() is ContentWidth.FULL

    def test_初期設定に戻すで標準へ(self, dialog) -> None:
        from hitofude.config import ContentWidth

        dialog._content_width.setCurrentIndex(dialog._content_width.findData(ContentWidth.FULL))
        dialog.reset_button.click()
        assert dialog._content_width.currentData() is ContentWidth.STANDARD


class TestLlmSection:
    """ローカルLLM の設定（ADR-0025 追記）。

    **送り先は出さない。** 変えられるのはポートまで（相手は `127.0.0.1`
    に固定）。ここを設定に出すと「うっかり外に出す」道ができる。
    """

    def dialog(self, qtbot, tmp_path, models=None):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        found = PreferencesDialog(config, models=models)
        qtbot.addWidget(found)
        return found, config

    def test_モデルを選べる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path, models=["gemma3:4b", "qwen3:8b"])
        dialog.model_box.setCurrentText("qwen3:8b")
        dialog.apply()
        assert config.llm_model == "qwen3:8b"

    def test_入っているモデルが候補に出る(self, qtbot, tmp_path) -> None:
        """**打たせない。** 名前を 1 文字間違えると動かない。"""
        dialog, _config = self.dialog(qtbot, tmp_path, models=["gemma3:4b", "qwen3:8b"])
        items = [dialog.model_box.itemText(i) for i in range(dialog.model_box.count())]
        assert items == ["gemma3:4b", "qwen3:8b"]

    def test_候補に無い名前も打てる(self, qtbot, tmp_path) -> None:
        """これから `ollama pull` するモデルを先に書いておける。"""
        dialog, config = self.dialog(qtbot, tmp_path, models=["gemma3:4b"])
        dialog.model_box.setCurrentText("phi4:14b")
        dialog.apply()
        assert config.llm_model == "phi4:14b"

    def test_Ollamaが無ければ今の値だけ(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path, models=[])
        items = [dialog.model_box.itemText(i) for i in range(dialog.model_box.count())]
        assert items == [_config.llm_model]

    def test_ポートを変えられる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.port_box.setValue(11500)
        dialog.apply()
        assert config.llm_port == 11500

    def test_送り先は出さない(self, qtbot, tmp_path) -> None:
        """**`127.0.0.1` 固定を画面でも明示する**（ADR-0025 の 3）。"""
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert "127.0.0.1" in dialog.llm_note_text()

    def test_文脈の長さを選べる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.context_box.setCurrentIndex(dialog.context_box.findData(16384))
        dialog.apply()
        assert config.llm_context == 16384

    def test_デフォルトに戻すで戻る(self, qtbot, tmp_path) -> None:
        from hitofude.core.llm import CONTEXT_TOKENS, DEFAULT_MODEL, DEFAULT_PORT

        dialog, config = self.dialog(qtbot, tmp_path, models=["gemma3:4b"])
        dialog.model_box.setCurrentText("qwen3:8b")
        dialog.port_box.setValue(11500)
        dialog.reset_to_defaults()
        dialog.apply()
        assert (config.llm_model, config.llm_port, config.llm_context) == (
            DEFAULT_MODEL,
            DEFAULT_PORT,
            CONTEXT_TOKENS,
        )


class TestTabs:
    """設定を 2 ページに分ける（ユーザー要望 2026-08-22）。

    **毛色が違うものを同じ列に並べない。** フォントや行間は「見え方」で、
    LLM の設定は「誰に読ませるか」。同じ縦一列に混ぜると、探すときに
    毎回全部を読むことになる。
    """

    def dialog(self, qtbot, tmp_path):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        found = PreferencesDialog(config)
        qtbot.addWidget(found)
        return found, config

    def labels(self, dialog) -> list[str]:
        return [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]

    def test_2ページある(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert self.labels(dialog) == ["一般", "アシスタント"]

    def test_最初に出るのは一般(self, qtbot, tmp_path) -> None:
        """**よく開くほうを先に。** LLM は一度決めたら触らない設定。"""
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.currentIndex() == 0

    def test_見え方は一般のページ(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.indexOf(dialog._font.parentWidget()) == 0

    def test_LLMは2ページ目(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.indexOf(dialog.model_box.parentWidget()) == 1

    def test_開いていないページも保存される(self, qtbot, tmp_path) -> None:
        """**見えていない欄も書き込む。** ページを開かないと保存されない、
        は驚く（前に打った値が消えたように見える）。"""
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.model_box.setCurrentText("qwen3:8b")
        dialog.tabs.setCurrentIndex(0)
        dialog.apply()
        assert config.llm_model == "qwen3:8b"

    def test_デフォルトに戻すは両方に効く(self, qtbot, tmp_path) -> None:
        from hitofude.config import DEFAULT_TAB_WIDTH
        from hitofude.core.llm import DEFAULT_MODEL

        dialog, config = self.dialog(qtbot, tmp_path)
        dialog._tab_width.setValue(8)
        dialog.model_box.setCurrentText("qwen3:8b")
        dialog.reset_to_defaults()
        dialog.apply()
        assert (config.tab_width, config.llm_model) == (DEFAULT_TAB_WIDTH, DEFAULT_MODEL)


class TestOcrSetting:
    """文字の読み取りの切り替え（ADR-0027）。"""

    def dialog(self, qtbot, tmp_path):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        found = PreferencesDialog(config)
        qtbot.addWidget(found)
        return found, config

    def test_選べる(self, qtbot, tmp_path) -> None:
        from hitofude.core.ocr import Engine

        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.ocr_box.setCurrentIndex(dialog.ocr_box.findData(Engine.LLM))
        dialog.apply()
        assert config.ocr_engine is Engine.LLM

    def test_アシスタントのページにある(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.indexOf(dialog.ocr_box.parentWidget()) == 1

    def test_どちらが既定か分かる(self, qtbot, tmp_path) -> None:
        """**選択肢の文言はユーザーが決めた**（2026-08-22）。速さの比較は
        設定画面では出さず、使い方のノートに書く。"""
        dialog, _config = self.dialog(qtbot, tmp_path)
        items = [dialog.ocr_box.itemText(i) for i in range(dialog.ocr_box.count())]
        assert items == ["macOS（デフォルト）", "ローカルLLM"]

    def test_デフォルトに戻すで戻る(self, qtbot, tmp_path) -> None:
        from hitofude.core.ocr import DEFAULT_ENGINE, Engine

        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.ocr_box.setCurrentIndex(dialog.ocr_box.findData(Engine.LLM))
        dialog.reset_to_defaults()
        dialog.apply()
        assert config.ocr_engine is DEFAULT_ENGINE


class TestLlmTimeoutSetting:
    """応答待ち時間を設定に出す（ユーザー要望 2026-08-24）。"""

    def dialog(self, qtbot, tmp_path):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        config.vault_path = tmp_path / "V"
        found = PreferencesDialog(config)
        qtbot.addWidget(found)
        return found, config

    def test_今の値が出る(self, qtbot, tmp_path) -> None:
        from hitofude.config import DEFAULT_LLM_TIMEOUT_MINUTES

        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.timeout_box.value() == DEFAULT_LLM_TIMEOUT_MINUTES

    def test_変えられる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.timeout_box.setValue(20)
        dialog.apply()
        assert config.llm_timeout_minutes == 20

    def test_初期設定に戻すで戻る(self, qtbot, tmp_path) -> None:
        from hitofude.config import DEFAULT_LLM_TIMEOUT_MINUTES

        dialog, _config = self.dialog(qtbot, tmp_path)
        dialog.timeout_box.setValue(30)
        dialog.reset_to_defaults()
        assert dialog.timeout_box.value() == DEFAULT_LLM_TIMEOUT_MINUTES


class TestHistoryInterval:
    """履歴を残す間隔（ユーザー要望 2026-08-24）。

    本文の保存は今のまま（打ち終わって 0.8 秒）。ここで決めるのは
    `.hitofude/history/` に版を残す間隔で、「なし」は `Cmd+S` を
    押したときだけ残す。
    """

    def dialog(self, qtbot, tmp_path):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        found = PreferencesDialog(config)
        qtbot.addWidget(found)
        return found, config

    def test_選択肢は5つ(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        box = dialog.history_box
        labels = [box.itemText(i) for i in range(box.count())]
        assert labels == ["なし", "15 分", "30 分", "60 分", "120 分"]

    def test_今の値が出る(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        assert dialog.history_box.currentData() == config.history_interval_minutes

    def test_変えると書き込まれる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.history_box.setCurrentIndex(dialog.history_box.findData(30))
        dialog.apply()
        assert config.history_interval_minutes == 30

    def test_なしも選べる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.history_box.setCurrentIndex(dialog.history_box.findData(0))
        dialog.apply()
        assert config.history_interval_minutes == 0

    def test_一般のページにある(self, qtbot, tmp_path) -> None:
        """ノートの置き場所と同じ毛色（どこに何を残すか）。"""
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.indexOf(dialog.history_box.parentWidget()) == 0

    def test_デフォルトに戻すで戻る(self, qtbot, tmp_path) -> None:
        from hitofude.storage.history import DEFAULT_INTERVAL_MINUTES

        dialog, _config = self.dialog(qtbot, tmp_path)
        dialog.history_box.setCurrentIndex(dialog.history_box.findData(120))
        dialog.reset_to_defaults()
        assert dialog.history_box.currentData() == DEFAULT_INTERVAL_MINUTES


class TestKeepAlive:
    """モデルを残す時間（ユーザー報告 2026-08-24）。

    答えたあとも `llama-server` が 8.0GB を抱える（実測）。どれだけ残すかを
    選べるようにする。既定は Ollama と同じ 5 分。
    """

    def dialog(self, qtbot, tmp_path):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        found = PreferencesDialog(config)
        qtbot.addWidget(found)
        return found, config

    def test_選択肢は4つ(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        box = dialog.keep_alive_box
        labels = [box.itemText(i) for i in range(box.count())]
        assert labels == ["答えたらすぐ降ろす", "1 分", "5 分", "30 分"]

    def test_今の値が出る(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        assert dialog.keep_alive_box.currentData() == config.llm_keep_alive_minutes

    def test_変えると書き込まれる(self, qtbot, tmp_path) -> None:
        dialog, config = self.dialog(qtbot, tmp_path)
        dialog.keep_alive_box.setCurrentIndex(dialog.keep_alive_box.findData(0))
        dialog.apply()
        assert config.llm_keep_alive_minutes == 0

    def test_アシスタントのページにある(self, qtbot, tmp_path) -> None:
        dialog, _config = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.indexOf(dialog.keep_alive_box.parentWidget()) == 1

    def test_デフォルトに戻すで戻る(self, qtbot, tmp_path) -> None:
        from hitofude.core.llm import KEEP_ALIVE_MINUTES

        dialog, _config = self.dialog(qtbot, tmp_path)
        dialog.keep_alive_box.setCurrentIndex(dialog.keep_alive_box.findData(30))
        dialog.reset_to_defaults()
        assert dialog.keep_alive_box.currentData() == KEEP_ALIVE_MINUTES


class TestHistoryUsage:
    """履歴の使用量を見せる（ADR-0023 の宿題）。

    版の履歴はディスクを食う（実測: 5 万字の記事 50 版で 6.3MB）。
    「見えないところで太らせない」と決めて `history.total_bytes()` を
    用意してあったのに、出す場所が無いままだった（レビュー 2026-08-25）。
    """

    def dialog(self, qtbot, tmp_path, *, versions: int = 0, size: int = 2048):
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        config.vault_path = tmp_path / "Notes"
        store = tmp_path / "Notes" / ".OboeGaki" / "history" / "01TEST"
        for index in range(versions):
            store.mkdir(parents=True, exist_ok=True)
            (store / f"2026-08-2{index}T10-00-00.md").write_bytes(b"x" * size)
        found = PreferencesDialog(config)
        qtbot.addWidget(found)
        return found

    def test_使用量が出る(self, qtbot, tmp_path) -> None:
        dialog = self.dialog(qtbot, tmp_path, versions=3, size=1024)
        assert dialog.history_usage_text() == "3KB"

    def test_無ければ0(self, qtbot, tmp_path) -> None:
        assert self.dialog(qtbot, tmp_path).history_usage_text() == "0KB"

    def test_一般のページにある(self, qtbot, tmp_path) -> None:
        """「履歴を残す間隔」の隣（同じ「ノートの置き場所」の節）。"""
        dialog = self.dialog(qtbot, tmp_path)
        assert dialog.tabs.indexOf(dialog.history_usage_label.parentWidget()) == 0


class TestFormatBytes:
    """量の見せ方。ADR-0023 の表記（69KB / 6.3MB）と揃える。"""

    @pytest.mark.parametrize(
        ("size", "shown"),
        [
            (0, "0KB"),
            (1, "1KB 未満"),
            (1023, "1KB 未満"),
            (1024, "1KB"),
            (70_656, "69KB"),
            (6_605_931, "6.3MB"),
            (2_147_483_648, "2.0GB"),
        ],
    )
    def test_読める形になる(self, size: int, shown: str) -> None:
        from hitofude.ui.preferences import format_bytes

        assert format_bytes(size) == shown
