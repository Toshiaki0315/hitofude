"""ノートリストのテスト（タスク 5-3 / spec §5.1, §6.6）。"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from hitofude.storage.index_db import NoteRow
from hitofude.ui.note_list import NoteListModel, NoteListView, NoteRole, format_date

pytestmark = pytest.mark.gui


def row(
    title: str, *, name: str | None = None, modified: str = "", pinned: bool = False
) -> NoteRow:
    return NoteRow(
        id=title,
        path=Path(f"{name or title}.md"),
        title=title,
        preview=f"{title} のプレビュー",
        modified_at=modified,
        mtime_ns=0,
        size_bytes=0,
        pinned=pinned,
    )


class TestFormatDate:
    """spec §5.1 のノートリストは日付を短く出す。"""

    def test_今日は時刻(self) -> None:
        now = datetime.now().replace(hour=14, minute=5)
        assert format_date(now.isoformat()) == "14:05"

    def test_今年は月日(self) -> None:
        target = datetime.now().replace(month=3, day=7) - timedelta(days=40)
        got = format_date(target.isoformat())
        assert got == f"{target.month}/{target.day}"

    def test_去年以前は年から(self) -> None:
        target = datetime.now().replace(year=datetime.now().year - 2, month=8, day=7)
        assert format_date(target.isoformat()) == f"{target.year}/8/7"

    @pytest.mark.parametrize("value", ["", "壊れた日付", "2026-13-45"])
    def test_読めない値は空文字(self, value: str) -> None:
        """front matter は手で編集されうる。日付が壊れていても落ちない。"""
        assert format_date(value) == ""


class TestNoteListModel:
    @pytest.fixture
    def model(self, qapp) -> NoteListModel:
        return NoteListModel()

    def test_初期状態は空(self, model) -> None:
        assert model.rowCount() == 0

    def test_行を差し替えられる(self, model) -> None:
        model.set_rows([row("会議メモ"), row("読書メモ")])
        assert model.rowCount() == 2

    def test_タイトルを返す(self, model) -> None:
        model.set_rows([row("会議メモ")])
        index = model.index(0)
        assert model.data(index, NoteRole.TITLE) == "会議メモ"
        assert model.data(index, Qt.ItemDataRole.DisplayRole) == "会議メモ"

    def test_プレビューと日付を返す(self, model) -> None:
        model.set_rows([row("会議メモ", modified="2026-08-08T14:05:00+09:00")])
        index = model.index(0)
        assert "プレビュー" in model.data(index, NoteRole.PREVIEW)
        assert model.data(index, NoteRole.DATE) == "14:05"

    def test_パスを返す(self, model) -> None:
        model.set_rows([row("会議メモ")])
        assert model.data(model.index(0), NoteRole.PATH) == Path("会議メモ.md")

    def test_範囲外は無効(self, model) -> None:
        model.set_rows([row("会議メモ")])
        assert model.data(model.index(5), NoteRole.TITLE) is None

    def test_行からNoteRowを取れる(self, model) -> None:
        model.set_rows([row("会議メモ")])
        assert model.note_at(model.index(0)).title == "会議メモ"

    def test_パスから行を引ける(self, model) -> None:
        """外部変更でノートが更新されたとき、選択を維持するのに使う。"""
        model.set_rows([row("A"), row("B"), row("C")])
        assert model.index_of(Path("B.md")).row() == 1

    def test_無いパスは無効なインデックス(self, model) -> None:
        model.set_rows([row("A")])
        assert model.index_of(Path("存在しない.md")).isValid() is False

    def test_ピン留めが分かる(self, model) -> None:
        model.set_rows([row("重要", pinned=True)])
        assert model.data(model.index(0), NoteRole.PINNED) is True

    def test_差し替えても行数が合う(self, model) -> None:
        model.set_rows([row("A"), row("B")])
        model.set_rows([row("C")])
        assert model.rowCount() == 1
        assert model.data(model.index(0), NoteRole.TITLE) == "C"


class TestNoteListView:
    @pytest.fixture
    def view(self, qtbot) -> NoteListView:
        widget = NoteListView()
        qtbot.addWidget(widget)
        widget.resize(280, 600)
        widget.show()
        return widget

    def test_モデルとデリゲートが付いている(self, view) -> None:
        from hitofude.ui.note_list import NoteItemDelegate

        assert isinstance(view.model(), NoteListModel)
        assert isinstance(view.itemDelegate(), NoteItemDelegate)

    def test_行を表示できる(self, view) -> None:
        view.set_rows([row("会議メモ"), row("読書メモ")])
        assert view.model().rowCount() == 2

    def test_選択するとシグナルが出る(self, view, qtbot) -> None:
        view.set_rows([row("会議メモ"), row("読書メモ")])
        with qtbot.waitSignal(view.note_activated, timeout=1000) as blocker:
            view.setCurrentIndex(view.model().index(1))
        assert Path(blocker.args[0]).name == "読書メモ.md"

    def test_パスを指定して選択できる(self, view) -> None:
        view.set_rows([row("A"), row("B")])
        view.select_path(Path("B.md"))
        assert view.currentIndex().row() == 1

    def test_無いパスを指定しても壊れない(self, view) -> None:
        view.set_rows([row("A")])
        view.select_path(Path("存在しない.md"))

    def test_選択中のパスを取れる(self, view) -> None:
        view.set_rows([row("A"), row("B")])
        view.select_path(Path("B.md"))
        assert view.current_path() == Path("B.md")

    def test_空なら選択中のパスはNone(self, view) -> None:
        assert view.current_path() is None

    def test_描画しても落ちない(self, view) -> None:
        """デリゲートの paint は例外を投げても Qt が握り潰すことがある。"""
        from PySide6.QtGui import QColor, QImage

        view.set_rows([row("会議メモ", pinned=True), row("読書メモ")])
        image = QImage(view.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        view.render(image)
        assert image.constBits() is not None

    def test_行の高さは2行分のプレビューが入る(self, view) -> None:
        """spec §5.1: タイトル / 日付 / プレビュー 2 行。"""
        view.set_rows([row("会議メモ")])
        height = view.sizeHintForRow(0)
        assert height >= 60
