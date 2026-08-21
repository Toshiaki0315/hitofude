"""一覧の行にフォルダ名を添える（K-2 / ユーザー要望）。

サイドバーでフォルダを選べるようになっても、**「すべて」で並んでいる
ときにどれがどのフォルダのものか分からない**（ユーザー報告：`仕事/` に
置いたノートが題名だけで並び、Finder の見え方と対応が取れなかった）。

置き場所は行の右上、日付の隣。**題名を削らない**位置に出す。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from hitofude.storage.index_db import NoteRow
from hitofude.theme import LIGHT
from hitofude.ui.note_list import NoteItemDelegate, NoteListModel, NoteRole, folder_label

pytestmark = pytest.mark.gui


def row(path: str) -> NoteRow:
    return NoteRow(
        id=path,
        path=Path(path),
        title="会議メモ",
        preview="本文",
        modified_at="",
        mtime_ns=0,
        size_bytes=0,
        pinned=False,
    )


class TestLabel:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("仕事/会議.md", "仕事"),
            ("仕事/2026/会議.md", "仕事/2026"),
            ("会議.md", ""),
        ],
    )
    def test_置き場所を出す(self, path: str, expected: str) -> None:
        assert folder_label(Path(path)) == expected

    def test_保管フォルダ直下は何も出さない(self) -> None:
        """**大多数はここにある。** 全行に `/` が並ぶと目印にならない。"""
        assert folder_label(Path("会議.md")) == ""


class TestRole:
    def test_モデルから引ける(self) -> None:
        model = NoteListModel()
        model.set_rows([row("仕事/会議.md")])
        assert model.data(model.index(0), NoteRole.FOLDER) == "仕事"

    def test_直下なら空(self) -> None:
        model = NoteListModel()
        model.set_rows([row("会議.md")])
        assert model.data(model.index(0), NoteRole.FOLDER) == ""


class TestPaint:
    """描いた絵で確かめる。役割を持たせただけで描いていなければ意味がない。"""

    def painted(self, path: str) -> QImage:
        # QFontMetrics は QApplication が無いと abort する（`qapp` を要求）
        model = NoteListModel()
        model.set_rows([row(path)])
        delegate = NoteItemDelegate(LIGHT)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 280, 70)
        image = QImage(280, 70, QImage.Format.Format_ARGB32)
        image.fill(QColor(LIGHT.background))
        painter = QPainter(image)
        delegate.paint(painter, option, model.index(0))
        painter.end()
        return image

    def test_フォルダがあると描き足される(self, qapp) -> None:
        assert self.painted("仕事/会議.md") != self.painted("会議.md")

    def test_直下なら何も足さない(self, qapp) -> None:
        assert self.painted("会議.md") == self.painted("メモ.md")


class TestHiddenFolders:
    """内部ディレクトリを置き場所ラベルに出さない（コードレビュー指摘）。"""

    def test_ゴミ箱の行にtrashを出さない(self) -> None:
        from pathlib import Path

        from hitofude.ui.note_list import folder_label

        assert folder_label(Path(".trash/捨てたメモ.md")) == ""

    def test_隠しフォルダ一般を出さない(self) -> None:
        from pathlib import Path

        from hitofude.ui.note_list import folder_label

        assert folder_label(Path(".obsidian/メモ.md")) == ""

    def test_普通のフォルダは今まで通り(self) -> None:
        from pathlib import Path

        from hitofude.ui.note_list import folder_label

        assert folder_label(Path("仕事/2026/メモ.md")) == "仕事/2026"


class TestCreateInFolder:
    """フォルダで絞っている間の新規作成はそのフォルダの中へ（ユーザー要望）。

    直下に作ると、絞り込み中の一覧に現れもせず「押したのに何も起きない」
    ように見える。日報フォルダに毎日書いていく、が素直にできるように。
    """

    def select_folder(self, window, name="日報"):
        from hitofude.core.document import Note
        from hitofude.ui.sidebar import Filter, FilterKind

        path = window.vault.root / name / "既存.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 既存\n", encoding="utf-8")
        window.vault_index.upsert_note(Note.read(path), window.vault.root)
        window.set_filter(Filter(FilterKind.FOLDER, folder=name))

    def test_新規ノートはフォルダの中にできる(self, window) -> None:
        self.select_folder(window)
        window.new_note()
        assert window.current_note is not None
        assert window.current_note.path.parent == window.vault.root / "日報"

    def test_絞っていなければ直下(self, window) -> None:
        window.new_note()
        assert window.current_note.path.parent == window.vault.root

    def test_テンプレートから新規もフォルダの中(self, window) -> None:
        self.select_folder(window)
        template = window.vault.templates()[0]
        created = window.create_from_template(template)
        assert created is not None
        assert created.path.parent == window.vault.root / "日報"

    def test_今日のノートは今まで通り直下(self, window) -> None:
        """日次は「同じ日 = 同じノート」が軸で、置き場は §7.1 どおり直下。"""
        self.select_folder(window)
        note = window.open_daily_note()
        assert note is not None
        assert note.path.parent == window.vault.root
