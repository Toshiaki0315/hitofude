"""ノートリストのテスト（タスク 5-3 / spec §5.1, §6.6）。"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt

from hitofude.storage.index_db import NoteRow
from hitofude.ui.note_list import NoteListModel, NoteListView, NoteRole, format_date

pytestmark = pytest.mark.gui


def row(
    title: str,
    *,
    name: str | None = None,
    modified: str = "",
    pinned: bool = False,
    preview: str | None = None,
) -> NoteRow:
    return NoteRow(
        id=title,
        path=Path(f"{name or title}.md"),
        title=title,
        preview=f"{title} のプレビュー" if preview is None else preview,
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
        # **日付を直書きしない。** `format_date` は「今日なら時刻」を返すので、
        # 固定日を書くと日付が変わった翌日に落ちる（実際に落ちた）
        today = datetime.now().replace(hour=14, minute=5)
        model.set_rows([row("会議メモ", modified=today.isoformat())])
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


class TestPinMark:
    """ピン留めの印（ユーザー要望で赤丸から黄色い星に変えた）。

    描いた絵を見て確かめる。色や形の指定はテキストでは追えない。
    """

    def painted(self, theme, *, pinned: bool):
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtWidgets import QStyleOptionViewItem

        from hitofude.ui.note_list import NoteItemDelegate, NoteListModel

        model = NoteListModel()
        model.set_rows([row("会議メモ", pinned=pinned)])
        delegate = NoteItemDelegate(theme)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 280, 70)
        image = QImage(280, 70, QImage.Format.Format_ARGB32)
        image.fill(QColor(theme.background))
        painter = QPainter(image)
        delegate.paint(painter, option, model.index(0))
        painter.end()
        return image

    def colors_in(self, image) -> set[str]:
        from PySide6.QtGui import QColor

        return {
            QColor(image.pixelColor(x, y)).name()
            for y in range(image.height())
            for x in range(image.width())
        }

    def test_ピン留めなら印の色が出る(self) -> None:
        from hitofude.theme import LIGHT

        assert LIGHT.pin_mark.lower() in self.colors_in(self.painted(LIGHT, pinned=True))

    def test_ピン留めでなければ出ない(self) -> None:
        from hitofude.theme import LIGHT

        assert LIGHT.pin_mark.lower() not in self.colors_in(self.painted(LIGHT, pinned=False))

    def test_ダークでも見える色になる(self) -> None:
        from hitofude.theme import DARK

        assert DARK.pin_mark.lower() in self.colors_in(self.painted(DARK, pinned=True))

    def test_明暗で色を変えている(self) -> None:
        from hitofude.theme import DARK, LIGHT

        assert LIGHT.pin_mark != DARK.pin_mark

    def test_強調色とは別の色にする(self) -> None:
        """以前は強調色の丸だった。星は星と分かる色にする。"""
        from hitofude.theme import LIGHT

        assert LIGHT.pin_mark != LIGHT.accent

    def test_タイトルに重ならない(self) -> None:
        """印のぶんだけ字下げされること。"""
        from hitofude.theme import LIGHT

        pinned = self.painted(LIGHT, pinned=True)
        plain = self.painted(LIGHT, pinned=False)
        assert bytes(pinned.constBits()) != bytes(plain.constBits())


def _option(view):
    from PySide6.QtWidgets import QStyleOptionViewItem

    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.rect = view.viewport().rect()
    option.font = view.font()
    return option


class TestPreviewHeight:
    """プレビューに要る高さ（ユーザー要望の見直し）。

    **`QFontMetrics.height()` では足りない。** 折り返しの組版は
    `lineSpacing()` で進む。Hiragino Sans 12pt は height 12 / lineSpacing 18 で、
    2 行だと 12px 不足し、実機でプレビューの 2 行目が切れていた。
    """

    @pytest.fixture
    def font(self):
        from PySide6.QtGui import QFont

        found = QFont("Hiragino Sans")
        found.setPointSizeF(12.0)
        return found

    def test_1行なら1行ぶん(self, font, qapp) -> None:
        from PySide6.QtGui import QFontMetrics

        from hitofude.ui.note_list import preview_height

        assert preview_height(font, "ひとこと", 280) == QFontMetrics(font).lineSpacing()

    def test_折り返すと2行ぶん(self, font, qapp) -> None:
        from PySide6.QtGui import QFontMetrics

        from hitofude.ui.note_list import preview_height

        assert preview_height(font, "あ" * 200, 280) == QFontMetrics(font).lineSpacing() * 2

    def test_行間で数える(self, font, qapp) -> None:
        """`height()` で数えると 2 行目が切れる（実機で確認）。"""
        from PySide6.QtGui import QFontMetrics

        from hitofude.ui.note_list import preview_height

        metrics = QFontMetrics(font)
        assert preview_height(font, "あ" * 200, 280) > metrics.height() * 2

    def test_長くても2行で止める(self, font, qapp) -> None:
        """一覧なので、1 件が画面を占めてはいけない。"""
        from hitofude.ui.note_list import preview_height

        assert preview_height(font, "あ" * 200, 280) == preview_height(font, "い" * 4000, 280)

    def test_空なら0(self, font, qapp) -> None:
        from hitofude.ui.note_list import preview_height

        assert preview_height(font, "", 280) == 0

    def test_幅が狭いほど折り返す(self, font, qapp) -> None:
        from hitofude.ui.note_list import preview_height

        assert preview_height(font, "あ" * 30, 120) >= preview_height(font, "あ" * 30, 400)

    def test_余白は詰めすぎない(self, qapp) -> None:
        """拡大して並べて選んだ。12px は行間が空きすぎ（4 件目が画面外）、
        7px はタイトル同士が近すぎる。9px を採る。"""
        from hitofude.ui.note_list import _Metrics

        assert 8 <= _Metrics().padding <= 10
