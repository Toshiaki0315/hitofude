"""ドラッグ＆ドロップでノートをフォルダへ移す（ユーザー要望）。

一覧の行をつまんで、サイドバーのフォルダへ落とす。移動の実体は
K-3（`Vault.move_note`）と同じで、入口が増えるだけ。

**QMimeData は自分で持っておく。** イベントは所有しないので、
参照を落とすと GC されてプロセスごと落ちる（過去に踏んだ）。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent

from hitofude.storage.index_db import ROOT_FOLDER
from hitofude.ui.main_window import MainWindow
from hitofude.ui.note_list import NOTE_MIME
from hitofude.ui.sidebar import Filter, FilterKind

pytestmark = pytest.mark.gui


def note_mime(relative: str) -> QMimeData:
    mime = QMimeData()
    mime.setData(NOTE_MIME, relative.encode("utf-8"))
    return mime


def drop_at(widget, mime: QMimeData, point: QPoint):
    """(イベント, mime) を返す。mime の参照を呼び側で持つため。"""
    event = QDropEvent(
        point,
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return event, mime


class TestListProvidesDrag:
    """一覧の行がドラッグの元になる。"""

    def seeded(self, window: MainWindow) -> Path:
        note = window.vault.create("動かす", "# 動かす\n\n本文\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        return note.path

    def test_行がドラッグできる(self, window) -> None:
        self.seeded(window)
        model = window._note_list.model()
        flags = model.flags(model.index(0, 0))
        assert flags & Qt.ItemFlag.ItemIsDragEnabled

    def test_ノートの場所を渡す(self, window) -> None:
        self.seeded(window)
        model = window._note_list.model()
        mime = model.mimeData([model.index(0, 0)])
        assert mime.hasFormat(NOTE_MIME)
        assert bytes(mime.data(NOTE_MIME)).decode("utf-8") == "動かす.md"


class TestSidebarAcceptsDrop:
    """フォルダの上でだけ受ける。"""

    def prepared(self, window: MainWindow):
        window.vault.create_folder("日報")
        note = window.vault.create("動かす", "# 動かす\n\n本文\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window._sidebar.expandAll()
        return note.path

    def point_of(self, window, target: Filter) -> QPoint:
        index = window._sidebar._find(target)
        assert index is not None, f"{target} が見つからない"
        return window._sidebar.visualRect(index).center()

    def test_フォルダの上では受ける(self, window) -> None:
        self.prepared(window)
        mime = note_mime("動かす.md")
        point = self.point_of(window, Filter(FilterKind.FOLDER, folder="日報"))
        event = QDragMoveEvent(
            point,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window._sidebar.dragMoveEvent(event)
        assert event.isAccepted()

    def test_タグの上では受けない(self, window) -> None:
        self.prepared(window)
        note = window.vault.create("タグ付き", "# タグ付き\n\n#仕事\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window._sidebar.expandAll()

        mime = note_mime("動かす.md")
        point = self.point_of(window, Filter(FilterKind.TAG, tag="仕事"))
        event = QDragMoveEvent(
            point,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window._sidebar.dragMoveEvent(event)
        assert not event.isAccepted()

    def test_ノート以外は受けない(self, window) -> None:
        self.prepared(window)
        mime = QMimeData()
        mime.setText("ただの文字")
        point = self.point_of(window, Filter(FilterKind.FOLDER, folder="日報"))
        event = QDragEnterEvent(
            point,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window._sidebar.dragEnterEvent(event)
        assert not event.isAccepted()


class TestDropMoves:
    """落とすと実際に移る。"""

    def prepared(self, window: MainWindow):
        window.vault.create_folder("日報")
        note = window.vault.create("動かす", "# 動かす\n\n本文\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window._sidebar.expandAll()
        return note.path

    def point_of(self, window, target: Filter) -> QPoint:
        index = window._sidebar._find(target)
        assert index is not None
        return window._sidebar.visualRect(index).center()

    def test_フォルダへ落とすと移る(self, window) -> None:
        path = self.prepared(window)
        event, _mime = drop_at(  # _mime は GC 避けの参照
            window._sidebar,
            note_mime("動かす.md"),
            self.point_of(window, Filter(FilterKind.FOLDER, folder="日報")),
        )
        window._sidebar.dropEvent(event)
        assert not path.exists()
        assert (window.vault.root / "日報" / "動かす.md").exists()
        rows = {str(row.path) for row in window.vault_index.notes()}
        assert "日報/動かす.md" in rows
        assert "移動しました" in window.notice()

    def test_直下へ落とすと戻る(self, window) -> None:
        self.prepared(window)
        source = window.vault.root / "日報" / "戻す.md"
        source.write_text("# 戻す\n", encoding="utf-8")
        from hitofude.core.document import Note

        window.vault_index.upsert_note(Note.read(source), window.vault.root)
        window.refresh()
        window._sidebar.expandAll()

        event, _mime = drop_at(  # _mime は GC 避けの参照
            window._sidebar,
            note_mime("日報/戻す.md"),
            self.point_of(window, Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)),
        )
        window._sidebar.dropEvent(event)
        assert (window.vault.root / "戻す.md").exists()

    def test_同じフォルダへ落としても壊れない(self, window) -> None:
        path = self.prepared(window)
        event, _mime = drop_at(  # _mime は GC 避けの参照
            window._sidebar,
            note_mime("動かす.md"),
            self.point_of(window, Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)),
        )
        window._sidebar.dropEvent(event)
        assert path.exists()


class TestDropHighlight:
    """落とす先が見えるようにする（ユーザー要望 2026-08-21）。

    受けるか受けないかは矢印の形でしか分からず、**どのフォルダに入るかは
    落とすまで分からなかった**。行が数ピクセルしか離れていないので、
    ひとつ上のフォルダへ入ってしまう。Finder と同じく、**入る先の行を
    塗る**。
    """

    def prepared(self, window: MainWindow) -> QPoint:
        window.vault.create_folder("日報")
        window.vault.create_folder("仕事")
        note = window.vault.create("動かす", "# 動かす\n\n本文\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window._sidebar.expandAll()
        return self.point_of(window, Filter(FilterKind.FOLDER, folder="日報"))

    def point_of(self, window, target: Filter) -> QPoint:
        index = window._sidebar._find(target)
        assert index is not None, f"{target} が見つからない"
        return window._sidebar.visualRect(index).center()

    def move_over(self, window, point: QPoint, mime: QMimeData) -> None:
        event = QDragMoveEvent(
            point,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window._sidebar.dragMoveEvent(event)

    def test_乗せた行が分かる(self, window) -> None:
        point = self.prepared(window)
        mime = note_mime("動かす.md")
        self.move_over(window, point, mime)
        assert window._sidebar.drop_target() == Filter(FilterKind.FOLDER, folder="日報")

    def test_行が塗られる(self, window) -> None:
        """`drop_target()` を覚えただけでは見えない。**目に見えるのが要件**。"""
        point = self.prepared(window)
        mime = note_mime("動かす.md")
        self.move_over(window, point, mime)
        index = window._sidebar._find(Filter(FilterKind.FOLDER, folder="日報"))
        item = window._sidebar.model().itemFromIndex(index)
        assert item.background().style() != Qt.BrushStyle.NoBrush

    def test_隣へ動かすと前の行は戻る(self, window) -> None:
        point = self.prepared(window)
        mime = note_mime("動かす.md")
        self.move_over(window, point, mime)
        self.move_over(
            window, self.point_of(window, Filter(FilterKind.FOLDER, folder="仕事")), mime
        )

        assert window._sidebar.drop_target() == Filter(FilterKind.FOLDER, folder="仕事")
        previous = window._sidebar.model().itemFromIndex(
            window._sidebar._find(Filter(FilterKind.FOLDER, folder="日報"))
        )
        assert previous.background().style() == Qt.BrushStyle.NoBrush

    def test_受けない行の上では塗らない(self, window) -> None:
        self.prepared(window)
        note = window.vault.create("タグ付き", "# タグ付き\n\n#仕事\n")
        window.vault_index.upsert_note(note, window.vault.root)
        window.refresh()
        window._sidebar.expandAll()
        mime = note_mime("動かす.md")
        self.move_over(window, self.point_of(window, Filter(FilterKind.TAG, tag="仕事")), mime)
        assert window._sidebar.drop_target() is None

    def test_離れると消える(self, window) -> None:
        """**落とさずに戻したときに塗りが残らない。** 残ると、次に開いた
        ときまで「そこへ入る」と言い続ける。"""
        point = self.prepared(window)
        mime = note_mime("動かす.md")
        self.move_over(window, point, mime)
        window._sidebar.dragLeaveEvent(QDragLeaveEvent())
        assert window._sidebar.drop_target() is None

    def test_落としたら消える(self, window) -> None:
        point = self.prepared(window)
        event, _mime = drop_at(window._sidebar, note_mime("動かす.md"), point)
        window._sidebar.dropEvent(event)
        assert window._sidebar.drop_target() is None
