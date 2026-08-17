"""ノート一覧の上に置くヘッダ（ユーザー要望）。

新規ノートがメニューと `Cmd+N` からしか作れなかった。**画面の中にも入口を置く**。
`EditorPane` と同じ形で、一覧をヘッダごと包む。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt

from hitofude.config import Config
from hitofude.storage.index_db import NoteRow, SortOrder
from hitofude.theme import DARK, LIGHT
from hitofude.ui.note_list import NoteListView
from hitofude.ui.note_list_pane import NoteListPane

pytestmark = pytest.mark.gui


def sample_row() -> NoteRow:
    return NoteRow(
        id="x",
        path=Path("メモ.md"),
        title="メモ",
        preview="本文",
        modified_at="2026-08-10T10:00:00+09:00",
        mtime_ns=0,
        size_bytes=0,
        pinned=False,
    )


@pytest.fixture
def pane(qtbot) -> NoteListPane:
    widget = NoteListPane(theme=LIGHT)
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestStructure:
    def test_一覧を持っている(self, pane) -> None:
        assert isinstance(pane.note_list, NoteListView)

    def test_一覧が見えている(self, pane) -> None:
        assert pane.note_list.isVisible()

    def test_新規ボタンが見えている(self, pane) -> None:
        assert pane.new_button.isVisible()

    def test_ボタンに説明が付いている(self, pane) -> None:
        """記号だけでは何のボタンか分からない。"""
        assert "新規" in pane.new_button.toolTip()

    def test_ショートカットも案内する(self, pane) -> None:
        assert "Cmd+N" in pane.new_button.toolTip()

    def test_一覧より細くならない(self, pane) -> None:
        from hitofude.ui.panes import NOTE_LIST_MIN_WIDTH

        assert pane.minimumWidth() >= NOTE_LIST_MIN_WIDTH


class TestButton:
    def test_押すと知らせが飛ぶ(self, pane, qtbot) -> None:
        with qtbot.waitSignal(pane.new_note_requested, timeout=1000):
            qtbot.mouseClick(pane.new_button, Qt.MouseButton.LeftButton)

    def test_自分ではノートを作らない(self, pane, qtbot) -> None:
        """作るのは `MainWindow` の仕事。ここは入口を置くだけ。"""
        assert not hasattr(pane, "vault")


class TestTheme:
    def test_テーマを変えられる(self, pane) -> None:
        pane.set_theme(DARK)
        assert pane.note_list.isVisible()

    def test_ダークでも描画で落ちない(self, pane) -> None:
        from PySide6.QtGui import QColor, QImage

        pane.set_theme(DARK)
        pane.resize(280, 400)
        image = QImage(pane.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("black"))
        pane.render(image)


class TestInWindow:
    """`MainWindow` に組み込んだときの振る舞い。"""

    @pytest.fixture
    def window(self, qtbot, tmp_path: Path):
        from hitofude.ui.main_window import MainWindow

        settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "HitofudeNotes"
        marker = config.vault_path / ".hitofude" / "seeded"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("test", encoding="utf-8")

        widget = MainWindow(config)
        qtbot.addWidget(widget)
        widget.show()
        yield widget
        widget.close()

    def test_3ペインの2番目に入っている(self, window) -> None:
        assert window.centralWidget().widget(1) is window.note_list_pane

    def test_note_listは今まで通り取れる(self, window) -> None:
        assert window.note_list is window.note_list_pane.note_list

    def test_ボタンでノートが増える(self, window, qtbot) -> None:
        before = window.note_list.model().rowCount()
        qtbot.mouseClick(window.note_list_pane.new_button, Qt.MouseButton.LeftButton)
        assert window.note_list.model().rowCount() == before + 1

    def test_ボタンで作ったノートが開く(self, window, qtbot) -> None:
        qtbot.mouseClick(window.note_list_pane.new_button, Qt.MouseButton.LeftButton)
        assert window.current_note is not None
        assert window.current_note.title == "無題"

    def test_ボタンで作ると一覧でも選ばれる(self, window, qtbot) -> None:
        qtbot.mouseClick(window.note_list_pane.new_button, Qt.MouseButton.LeftButton)
        selected = window.note_list.current_path()
        assert selected == window.current_note.path.relative_to(window.vault.root)

    def test_Cmd_1などの表示切り替えは今まで通り(self, window) -> None:
        """隠す対象はヘッダごとのペイン。"""
        window.toggle_note_list()
        assert window.note_list_pane.isHidden()
        window.toggle_note_list()
        assert not window.note_list_pane.isHidden()

    def test_テーマ切り替えが届く(self, window) -> None:
        from hitofude.theme import ThemeMode

        window.theme_watcher.set_mode(ThemeMode.DARK)
        assert window.note_list.isVisible()


class TestSortMenu:
    """並び順の切り替え（C-3）。

    一覧の上に置く。**設定ダイアログに入れない。** 並び替えは「今そうしたい」
    操作で、環境設定のように一度決めて忘れるものではない。
    """

    def test_ボタンがある(self, pane) -> None:
        assert pane.sort_button is not None

    def test_3つの並びから選べる(self, pane) -> None:
        labels = [action.text() for action in pane.sort_button.menu().actions()]
        assert len(labels) == 3

    def test_今の並びに印が付く(self, pane) -> None:
        pane.set_sort_order(SortOrder.TITLE)
        checked = [a.text() for a in pane.sort_button.menu().actions() if a.isChecked()]
        assert len(checked) == 1

    def test_選ぶと知らせる(self, pane, qtbot) -> None:
        target = next(a for a in pane.sort_button.menu().actions() if a.data() is SortOrder.CREATED)
        with qtbot.waitSignal(pane.sort_order_changed, timeout=1000) as blocker:
            target.trigger()
        assert blocker.args[0] is SortOrder.CREATED

    def test_今の並びを答える(self, pane) -> None:
        pane.set_sort_order(SortOrder.CREATED)
        assert pane.sort_order() is SortOrder.CREATED

    def test_何のボタンか分かる(self, pane) -> None:
        assert pane.sort_button.toolTip()

    def test_記号と三角が重ならない(self, pane) -> None:
        """ユーザー報告。`⇅` の上にポップアップ用の三角が重なっていた。

        実測では記号が 13.5px なのにボタンが 28px しかなく、三角の場所が
        足りていなかった。
        """
        from PySide6.QtGui import QFontMetricsF

        from hitofude.ui.note_list_pane import SORT_GLYPH, SORT_INDICATOR_ROOM

        glyph = QFontMetricsF(pane.sort_button.font()).horizontalAdvance(SORT_GLYPH)
        assert pane.sort_button.width() >= glyph + SORT_INDICATOR_ROOM

    def test_三角の場所を確保している(self, pane) -> None:
        from hitofude.ui.note_list_pane import SORT_INDICATOR_ROOM

        assert SORT_INDICATOR_ROOM >= 12


class TestEmptyState:
    """空のときの案内（C-6 / ユーザー提案）。

    ノートが 0 件だと一覧が真っ白になる。初回起動の第一印象なので、
    次に何をすればよいかを置く。
    """

    def test_空なら案内が出る(self, pane) -> None:
        pane.note_list.set_rows([])
        assert pane.empty_notice_visible() is True

    def test_案内に作り方が書いてある(self, pane) -> None:
        pane.note_list.set_rows([])
        assert "＋" in pane.empty_notice_text()

    def test_1件でもあれば出さない(self, pane) -> None:
        pane.note_list.set_rows([sample_row()])
        assert pane.empty_notice_visible() is False

    def test_空に戻ればまた出る(self, pane) -> None:
        pane.note_list.set_rows([sample_row()])
        pane.note_list.set_rows([])
        assert pane.empty_notice_visible() is True

    def test_案内は一覧の背景の上に出る(self, pane) -> None:
        """**透けるのに任せない。** 上のバーの高さを変えたら、案内の下地が
        別の色（実測 #303032）で塗られてダークで浮いた。何色の上に出るかを
        決めておく。"""
        from hitofude.theme import DARK

        pane.set_theme(DARK)
        assert DARK.background.lower() in pane._empty.styleSheet().lower()

    def test_ゴミ箱が空のときも出る(self, pane) -> None:
        """絞り込んだ結果が 0 件でも、一覧が真っ白なのは同じ。"""
        pane.note_list.set_rows([])
        assert pane.empty_notice_visible() is True

    def test_文言を差し替えられる(self, pane) -> None:
        """**何を見ているかで案内は変わる。** ゴミ箱で「＋ で作れます」は
        噛み合わない（作ったノートはゴミ箱に入らない）。"""
        pane.set_empty_notice("ゴミ箱は空です。")
        assert pane.empty_notice_text() == "ゴミ箱は空です。"


class TestHeaderLook:
    """ヘッダの見た目（ユーザー要望の見直し）。

    実機を見ると `⇅` だけ枠付きで浮いていた。`set_theme` が `＋` にしか
    書式を当てていなかったため（**あとから足したボタンが漏れていた**）。

    **枠そのものは後に「付ける」へ変わった**（ユーザー要望）。本文側の
    ツールバーと同じ角丸の枠にする。ここで見るのは**2 つが揃うこと**で、
    それは枠の有無が変わっても要る性質。
    """

    def test_2つのボタンが同じ書式(self, pane) -> None:
        assert pane.sort_button.styleSheet() == pane.new_button.styleSheet()

    def test_本文側と同じ枠を描く(self, pane) -> None:
        from hitofude.ui.format_toolbar import BUTTON_RADIUS

        style = pane.sort_button.styleSheet()
        assert f"border-radius: {BUTTON_RADIUS}px" in style
        assert "border: none" not in style

    def test_テーマを変えても揃う(self, pane) -> None:
        from hitofude.theme import DARK

        pane.set_theme(DARK)
        assert pane.sort_button.styleSheet() == pane.new_button.styleSheet()
