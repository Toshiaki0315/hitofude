"""設定の永続化のテスト（タスク 5-2 / spec §4, §5.3, §7.1）。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import DEFAULT_TAB_WIDTH, DEFAULT_VAULT_NAME, Config
from hitofude.storage.index_db import SortOrder
from hitofude.theme import ThemeMode

pytestmark = pytest.mark.gui


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    """実ユーザーの設定を汚さないよう、毎回 ini ファイルへ書く。"""
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    return Config(settings)


class TestVaultPath:
    def test_既定はDocuments配下(self, config) -> None:
        """spec §7.1: 既定は `~/Documents/HitofudeNotes`。"""
        assert config.vault_path == Path.home() / "Documents" / DEFAULT_VAULT_NAME

    def test_設定して読み直せる(self, config, tmp_path) -> None:
        config.vault_path = tmp_path / "別の場所"
        assert config.vault_path == tmp_path / "別の場所"

    def test_保存先に永続化される(self, config, tmp_path) -> None:
        config.vault_path = tmp_path / "保存先"
        reopened = Config(QSettings(config.settings.fileName(), QSettings.Format.IniFormat))
        assert reopened.vault_path == tmp_path / "保存先"

    def test_未設定かどうかを判定できる(self, config, tmp_path) -> None:
        """初回起動では vault を選ばせる必要がある。"""
        assert config.has_vault is False
        config.vault_path = tmp_path / "選んだ"
        assert config.has_vault is True


class TestTheme:
    def test_既定はシステム追従(self, config) -> None:
        assert config.theme_mode is ThemeMode.SYSTEM

    @pytest.mark.parametrize("mode", list(ThemeMode))
    def test_設定して読み直せる(self, config, mode: ThemeMode) -> None:
        config.theme_mode = mode
        assert config.theme_mode is mode

    def test_壊れた値なら既定に戻す(self, config) -> None:
        """設定ファイルを手で編集されても起動できなくなってはいけない。"""
        config.settings.setValue("theme/mode", "存在しないモード")
        assert config.theme_mode is ThemeMode.SYSTEM


class TestFont:
    def test_既定はヒラギノ15pt(self, config) -> None:
        """spec §5.2。"""
        assert config.font_family == "Hiragino Sans"
        assert config.font_point_size == pytest.approx(15.0)

    def test_設定して読み直せる(self, config) -> None:
        config.font_family = "Noto Sans JP"
        config.font_point_size = 17.5
        assert config.font_family == "Noto Sans JP"
        assert config.font_point_size == pytest.approx(17.5)

    def test_等幅フォントも持つ(self, config) -> None:
        """既定は実在するフォント。

        spec §5.2 は `SF Mono` を指定しているが、macOS はアプリに公開して
        いないため解決されず、Qt が警告を出して行の高さがばらつく。
        """
        from PySide6.QtGui import QFontDatabase

        assert config.mono_family in set(QFontDatabase.families())

    @pytest.mark.parametrize("size", [0, -3, 500])
    def test_極端な文字サイズは既定に戻す(self, config, size) -> None:
        config.settings.setValue("font/size", size)
        assert 8 <= config.font_point_size <= 72


class TestTrash:
    def test_既定は30日(self, config) -> None:
        """spec §7.6。"""
        assert config.trash_days == 30

    def test_設定して読み直せる(self, config) -> None:
        config.trash_days = 7
        assert config.trash_days == 7

    def test_負の値は既定に戻す(self, config) -> None:
        config.settings.setValue("trash/days", -1)
        assert config.trash_days == 30


class TestLayout:
    def test_ペイン幅の既定(self, config) -> None:
        """spec §5.1: サイドバー 180px、ノートリスト 280px。"""
        assert config.splitter_sizes[:2] == [180, 280]

    def test_ペイン幅を保存できる(self, config) -> None:
        config.splitter_sizes = [200, 300, 700]
        assert config.splitter_sizes == [200, 300, 700]

    def test_壊れた値なら既定に戻す(self, config) -> None:
        config.settings.setValue("layout/splitter", ["これは", "数値ではない"])
        assert config.splitter_sizes[:2] == [180, 280]

    def test_ペインの表示状態を保存できる(self, config) -> None:
        """spec §5.4: `Cmd+1` / `Cmd+2` のトグル。"""
        assert config.sidebar_visible is True
        config.sidebar_visible = False
        assert config.sidebar_visible is False

    def test_ウィンドウの位置とサイズを保存できる(self, config) -> None:
        assert config.window_geometry is None
        config.window_geometry = b"\x01\x02\x03"
        assert bytes(config.window_geometry) == b"\x01\x02\x03"


class TestLastNote:
    """最後に開いていたノート（起動時に開き直すため）。

    **vault からの相対パスで持つ。** 絶対パスで覚えると、保管フォルダを
    移したときに前の場所を指したままになる。
    """

    def test_既定はNone(self, config: Config) -> None:
        assert config.last_note is None

    def test_覚えられる(self, config: Config) -> None:
        config.last_note = Path("会議メモ.md")
        assert config.last_note == Path("会議メモ.md")

    def test_サブフォルダも扱える(self, config: Config) -> None:
        config.last_note = Path("2026/08/日報.md")
        assert config.last_note == Path("2026/08/日報.md")

    def test_日本語のファイル名でも壊れない(self, config: Config) -> None:
        config.last_note = Path("打ち合わせ 議事録.md")
        assert config.last_note == Path("打ち合わせ 議事録.md")

    def test_忘れさせられる(self, config: Config) -> None:
        config.last_note = Path("会議メモ.md")
        config.last_note = None
        assert config.last_note is None

    def test_空文字はNoneとして扱う(self, config: Config) -> None:
        config.settings.setValue("session/last_note", "")
        assert config.last_note is None

    def test_絶対パスは受け付けない(self, config: Config) -> None:
        """vault の外を指す値を持ち込ませない。"""
        config.last_note = Path("/etc/passwd")
        assert config.last_note is None

    def test_親をたどるパスも受け付けない(self, config: Config) -> None:
        config.last_note = Path("../../他人のノート.md")
        assert config.last_note is None

    def test_シンボリックリンクで外へ出る値は受け付けない(self, config: Config, tmp_path) -> None:
        """設定ファイルは手で編集できる。判定は `core/paths.py` に統一した。"""
        config.vault_path.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "外部"
        outside.mkdir(exist_ok=True)
        (config.vault_path / "抜け道").symlink_to(outside)

        config.settings.setValue("session/last_note", "抜け道/秘密.md")
        assert config.last_note is None


class TestTabWidth:
    """タブ幅（ユーザー要望）。

    Qt の既定は 80px 固定で、本文フォントだと 12 文字ぶんもあった（実測）。
    Markdown の世界では 4 文字が標準なので、そこを既定にする。
    """

    def test_既定は4文字(self, config) -> None:
        assert config.tab_width == DEFAULT_TAB_WIDTH == 4

    def test_変えられる(self, config) -> None:
        config.tab_width = 2
        assert config.tab_width == 2

    def test_小さすぎる値は既定に戻す(self, config) -> None:
        config.settings.setValue("editor/tab_width", 0)
        assert config.tab_width == DEFAULT_TAB_WIDTH

    def test_大きすぎる値は既定に戻す(self, config) -> None:
        config.settings.setValue("editor/tab_width", 999)
        assert config.tab_width == DEFAULT_TAB_WIDTH

    def test_壊れた値でも落ちない(self, config) -> None:
        config.settings.setValue("editor/tab_width", "あ")
        assert config.tab_width == DEFAULT_TAB_WIDTH


class TestSortOrder:
    """一覧の並び順（C-3）。"""

    def test_既定は更新順(self, config) -> None:
        assert config.sort_order is SortOrder.MODIFIED

    def test_変えられる(self, config) -> None:
        config.sort_order = SortOrder.TITLE
        assert config.sort_order is SortOrder.TITLE

    def test_壊れた値は既定に戻す(self, config) -> None:
        config.settings.setValue("list/sort_order", "なにか")
        assert config.sort_order is SortOrder.MODIFIED
