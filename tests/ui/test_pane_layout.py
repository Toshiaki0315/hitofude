"""ペインの幅が潰れないことのテスト（ユーザー報告の回帰）。

`Cmd+1` でサイドバーを隠すと `QSplitter` はその幅を 0 にする。
`closeEvent` はそれをそのまま保存するため、次の起動でも 0 のまま復元される。
**表示されているのに幅 0 のペイン**ができ、`Cmd+1` を押しても最小幅までしか
戻らないので、実質的に二度と使えなくなっていた。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import DEFAULT_SPLITTER_SIZES, Config
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui

WIDTH = 1100


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")
    return config


def open_window(qtbot, config: Config) -> MainWindow:
    window = MainWindow(config)
    qtbot.addWidget(window)
    window.show()
    window.resize(WIDTH, 720)
    return window


class TestFreshStart:
    def test_初回は既定の幅で開く(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        sizes = window.centralWidget().sizes()
        assert sizes[0] == DEFAULT_SPLITTER_SIZES[0]
        assert sizes[1] == DEFAULT_SPLITTER_SIZES[1]

    def test_3つとも見えている(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        assert window.sidebar.isVisible()
        assert window.note_list.isVisible()
        assert window.editor_pane.isVisible()


class TestMinimumWidth:
    """潰れないよう最小幅を持たせる（spec §5.1 のサイドバー 180 / 一覧 280）。"""

    def test_サイドバーに最小幅がある(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        assert window.sidebar.minimumWidth() > 0

    def test_一覧に最小幅がある(self, qtbot, config) -> None:
        # 守る対象は splitter に入っているペイン（一覧は「新規」ボタンごと
        # `NoteListPane` に包まれている）
        window = open_window(qtbot, config)
        assert window.note_list_pane.minimumWidth() > window.sidebar.minimumWidth()

    def test_手で狭めても最小幅より細くならない(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.centralWidget().setSizes([1, 1, WIDTH - 2])
        sizes = window.centralWidget().sizes()
        assert sizes[0] >= window.sidebar.minimumWidth()
        assert sizes[1] >= window.note_list_pane.minimumWidth()


class TestRestoreFromCrushed:
    """報告された状態そのもの（保存値が `[0, 0, 1058]`）から立ち直る。"""

    def test_見えるペインは既定の幅へ戻る(self, qtbot, config) -> None:
        config.splitter_sizes = [0, 0, 1058]
        window = open_window(qtbot, config)
        # 最小幅で妥協せず、既定の幅まで戻す
        assert window.centralWidget().sizes()[:2] == DEFAULT_SPLITTER_SIZES[:2]

    def test_隠れているペインは0のまま(self, qtbot, config) -> None:
        """表示状態は尊重する。勝手に出してこない。"""
        config.splitter_sizes = [0, 280, 820]
        config.sidebar_visible = False
        window = open_window(qtbot, config)
        assert window.sidebar.isVisible() is False
        assert window.centralWidget().sizes()[0] == 0

    def test_隠れていても一覧は使える幅になる(self, qtbot, config) -> None:
        """報告された状態: サイドバーは隠れ、一覧は幅 0 で復元されていた。"""
        config.splitter_sizes = [0, 0, 1058]
        config.sidebar_visible = False
        window = open_window(qtbot, config)
        assert window.note_list.isVisible()
        assert window.centralWidget().sizes()[1] == DEFAULT_SPLITTER_SIZES[1]

    def test_手で決めた幅は保つ(self, qtbot, config) -> None:
        """勝手に既定へ戻さない。狭めたのはユーザーの意思。"""
        config.splitter_sizes = [150, 240, 710]
        window = open_window(qtbot, config)
        assert window.centralWidget().sizes()[:2] == [150, 240]


class TestToggle:
    def test_隠して戻すと使える幅になる(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.toggle_sidebar()
        assert window.sidebar.isVisible() is False

        window.toggle_sidebar()
        assert window.centralWidget().sizes()[0] >= window.sidebar.minimumWidth()

    def test_一覧も隠して戻せる(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.toggle_note_list()
        window.toggle_note_list()
        assert window.centralWidget().sizes()[1] >= window.note_list_pane.minimumWidth()

    def test_戻したあとエディタも残る(self, qtbot, config) -> None:
        """借りる先はエディタだが、潰してはいけない。"""
        window = open_window(qtbot, config)
        window.toggle_sidebar()
        window.toggle_note_list()
        window.toggle_sidebar()
        window.toggle_note_list()
        assert window.centralWidget().sizes()[2] > 0
        assert window.editor.isVisible()

    def test_隠したまま閉じて開き直しても戻せる(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.toggle_sidebar()
        window.close()

        again = open_window(qtbot, config)
        assert again.sidebar.isVisible() is False
        again.toggle_sidebar()
        assert again.centralWidget().sizes()[0] >= again.sidebar.minimumWidth()

    def test_2回隠して戻しても幅が減っていかない(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        for _ in range(3):
            window.toggle_sidebar()
            window.toggle_sidebar()
        assert window.centralWidget().sizes()[0] >= DEFAULT_SPLITTER_SIZES[0]


class TestSaveOnClose:
    """終了時に「隠す」が勝手に保存されないこと（ユーザー報告の原因）。

    `isVisible()` は**ウィンドウ自体が隠れていると子も False** を返す。
    アプリを `Cmd+H` で隠してから終了すると、出していたペインまで
    「隠す」で保存され、次の起動で真っ白な窓になっていた。
    """

    def test_普通に閉じれば表示のまま保存される(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.close()
        assert config.sidebar_visible is True
        assert config.note_list_visible is True

    def test_ウィンドウを隠してから閉じても表示のまま(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.hide()
        window.close()
        assert config.sidebar_visible is True
        assert config.note_list_visible is True

    def test_最小化してから閉じても表示のまま(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.showMinimized()
        window.close()
        assert config.sidebar_visible is True

    def test_自分で隠したペインはちゃんと隠すで保存される(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.toggle_sidebar()
        window.close()
        assert config.sidebar_visible is False
        assert config.note_list_visible is True

    def test_隠したペインの幅を0で保存しない(self, qtbot, config) -> None:
        """0 で保存すると、次に出したとき元の幅へ戻せない。"""
        window = open_window(qtbot, config)
        window.centralWidget().setSizes([220, 300, 578])
        window.toggle_sidebar()
        window.close()
        assert config.splitter_sizes[0] == 220

    def test_見えているペインの幅は今の値で保存する(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.centralWidget().setSizes([220, 300, 578])
        window.close()
        assert config.splitter_sizes[:2] == [220, 300]

    def test_隠して閉じて開き直しても幅が残る(self, qtbot, config) -> None:
        window = open_window(qtbot, config)
        window.centralWidget().setSizes([220, 300, 578])
        window.toggle_sidebar()
        window.close()

        again = open_window(qtbot, config)
        again.toggle_sidebar()
        assert again.centralWidget().sizes()[0] == 220
