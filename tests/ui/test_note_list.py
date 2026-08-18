"""ノートリストのテスト（タスク 5-3 / spec §5.1, §6.6）。"""

from datetime import datetime, timedelta
from itertools import pairwise
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


class TestRowHeight:
    """行の高さは**すべて同じ**（ユーザー報告）。

    新しいノートを足したら、一覧の行が既存のノートに重なった。原因は
    `setUniformItemSizes(True)`（5,000 件でも高さ計算を 1 回で済ませる
    ための設定）と、**プレビューの行数で高さが変わる `sizeHint`** の
    食い違い。実測では、2 行のプレビューを持つ行が 34px しか割り当てられて
    いないのに 70px 描いていた。

    `uniform` を外すと正しく並ぶが**高くつく**（実測 5,000 件で 906ms /
    uniform なら 29ms）。一覧は保存のたびに引き直すので、こちらは選べない。
    そこで**高さのほうを固定する**。プレビューが 1 行のノートには空きが
    できるが、行が重なるよりはよい。
    """

    @pytest.fixture
    def view(self, qtbot) -> NoteListView:
        widget = NoteListView()
        qtbot.addWidget(widget)
        widget.resize(280, 600)
        widget.show()
        return widget

    def _hint(self, view, number: int) -> int:
        from PySide6.QtWidgets import QStyleOptionViewItem

        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.font = view.font()
        index = view.model().index(number)
        option.rect = view.visualRect(index)
        return view.itemDelegate().sizeHint(option, index).height()

    def _mixed(self) -> list:
        return [
            row("長いノート", preview="ようこそ。" + "あ" * 200),
            row("短いノート", preview="ひとこと"),
            row("空のノート", preview=""),
        ]

    def test_どの行も同じ高さ(self, view) -> None:
        view.set_rows(self._mixed())
        heights = {self._hint(view, number) for number in range(3)}
        assert len(heights) == 1, f"高さがばらついている: {heights}"

    def test_行が重ならない(self, view, qtbot) -> None:
        """これが実際に起きた不具合。"""
        view.resize(280, 700)
        view.show()
        view.set_rows(self._mixed())
        view.doItemsLayout()

        rects = [view.visualRect(view.model().index(number)) for number in range(3)]
        for previous, current in pairwise(rects):
            assert current.top() >= previous.bottom(), "行が重なっている"

    def test_描くのに要る高さが収まっている(self, view) -> None:
        """割り当てより大きく描くと、その差がそのまま重なりになる。"""
        from hitofude.ui.note_list import PREVIEW_MAX_LINES, preview_height

        view.set_rows(self._mixed())
        needed = preview_height(view.font(), "ようこそ。" + "あ" * 200, 280)
        assert needed <= self._hint(view, 0)
        assert PREVIEW_MAX_LINES == 2

    def test_高さを1回で済ませる設定は保つ(self, view) -> None:
        """**外すと 5,000 件で 906ms**（実測）。一覧は保存のたびに引き直す。"""
        assert view.uniformItemSizes() is True


def drop_event(paths: list[Path], *, kind: str = "drop"):
    """ローカルファイルのドロップイベントを組み立てる。

    **QMimeData も一緒に返す。** イベントは mime を所有しないので、
    参照を持たずに返すと GC で解放され、Qt が触った瞬間に segfault する
    （conftest の `png_bytes` と同じ罠。実際に落ちた）。
    """
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    if kind == "enter":
        event = QDragEnterEvent(
            QPointF(10, 10).toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    else:
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    return event, mime


class TestDropMarkdown:
    """一覧へ .md をドラッグ＆ドロップしてノートを追加する（ユーザー要望 2026-08-18）。

    一覧は取り込むファイルを知らせるだけ。vault へのコピーは MainWindow
    側（NoteActions）の仕事。
    """

    @pytest.fixture
    def view(self, qtbot) -> NoteListView:
        widget = NoteListView()
        qtbot.addWidget(widget)
        return widget

    def test_mdファイルのドロップを受け入れる(self, view, tmp_path) -> None:
        source = tmp_path / "持ち込み.md"
        source.write_text("# 持ち込み\n", encoding="utf-8")
        event, _keepalive = drop_event([source], kind="enter")
        view.dragEnterEvent(event)
        assert event.isAccepted()

    def test_ドロップでシグナルが出る(self, view, qtbot, tmp_path) -> None:
        first = tmp_path / "一つ目.md"
        first.write_text("# 一つ目\n", encoding="utf-8")
        second = tmp_path / "二つ目.md"
        second.write_text("# 二つ目\n", encoding="utf-8")

        event, _keepalive = drop_event([first, second])
        with qtbot.waitSignal(view.files_dropped, timeout=1000) as blocker:
            view.dropEvent(event)
        assert blocker.args[0] == [first, second]

    def test_md以外は受け入れない(self, view, tmp_path) -> None:
        image = tmp_path / "画像.png"
        image.write_bytes(b"x")
        event, _keepalive = drop_event([image], kind="enter")
        view.dragEnterEvent(event)
        assert not event.isAccepted()

    def test_混在なら_mdだけを知らせる(self, view, qtbot, tmp_path) -> None:
        note = tmp_path / "ノート.md"
        note.write_text("# ノート\n", encoding="utf-8")
        image = tmp_path / "画像.png"
        image.write_bytes(b"x")

        event, _keepalive = drop_event([image, note])
        with qtbot.waitSignal(view.files_dropped, timeout=1000) as blocker:
            view.dropEvent(event)
        assert blocker.args[0] == [note]
