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


class TestTrashRowsWithFolders:
    """階層化したゴミ箱（K-5）の一覧。"""

    def test_フォルダの中で捨てたノートも一覧に出る(self, window) -> None:
        path = window.vault.root / "仕事" / "捨てる.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 捨てる\n", encoding="utf-8")
        window.vault.trash(path)
        titles = [row.title for row in window._notes.trash_rows()]
        assert "捨てる" in titles

    def test_行には元の場所が出る(self) -> None:
        from pathlib import Path

        from hitofude.ui.note_list import folder_label

        # .trash 自体は隠すが、その中の元の場所（戻る先）は役に立つ
        assert folder_label(Path(".trash/仕事/2026/メモ.md")) == "仕事/2026"
        assert folder_label(Path(".trash/メモ.md")) == ""


class TestRootSelection:
    """ルートを選んだときの一覧と新規作成（ユーザー要望）。"""

    def seed(self, window):
        from hitofude.core.document import Note

        for relative in ("直下.md", "仕事/中.md"):
            path = window.vault.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.stem}\n", encoding="utf-8")
            window.vault_index.upsert_note(Note.read(path), window.vault.root)
        window.refresh()

    def select_root(self, window):
        from hitofude.storage.index_db import ROOT_FOLDER
        from hitofude.ui.sidebar import Filter, FilterKind

        window.set_filter(Filter(FilterKind.FOLDER, folder=ROOT_FOLDER))

    def test_直下のノートだけが出る(self, window) -> None:
        self.seed(window)
        self.select_root(window)
        model = window._note_list.model()
        titles = {model.note_at(model.index(row, 0)).title for row in range(model.rowCount())}
        assert titles == {"直下"}

    def test_新規ノートは直下にできる(self, window) -> None:
        self.seed(window)
        self.select_root(window)
        window.new_note()
        assert window.current_note.path.parent == window.vault.root

    def test_移動先の一覧に記号は出さない(self, window, monkeypatch) -> None:
        """ルートの合図（"."）を選択肢の文字として見せない。
        直下は先頭の専用項目が担う。"""
        from hitofude.ui import note_actions as module

        self.seed(window)
        captured = {}

        def fake(parent, title, label, items, current=0, editable=True):
            captured["items"] = list(items)
            return ("", False)

        monkeypatch.setattr(module.QInputDialog, "getItem", staticmethod(fake))
        window.move_note_to_folder(window.vault.root / "直下.md")
        assert "." not in captured["items"]
        assert captured["items"][0] == module.ROOT_FOLDER_CHOICE


class TestImportIntoFolder:
    """読み込みも選んでいるフォルダへ（ユーザー要望 2026-08-23）。

    **新規作成と同じ作法。** 直下に作ると、絞り込み中の一覧に現れもせず
    「読み込んだのに出てこない」になる。
    """

    def select_folder(self, window, name="資料"):
        from hitofude.core.document import Note
        from hitofude.ui.sidebar import Filter, FilterKind

        path = window.vault.root / name / "既存.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 既存\n", encoding="utf-8")
        window.vault_index.upsert_note(Note.read(path), window.vault.root)
        window.set_filter(Filter(FilterKind.FOLDER, folder=name))

    def source(self, tmp_path):
        path = tmp_path / "外の資料.md"
        path.write_text("# 外の資料\n\n本文\n", encoding="utf-8")
        return path

    def test_ドロップしたmdはそのフォルダへ(self, window, tmp_path) -> None:
        self.select_folder(window)
        window.import_note_files([self.source(tmp_path)])
        assert (window.vault.root / "資料" / "外の資料.md").is_file()

    def test_絞っていなければ直下(self, window, tmp_path) -> None:
        window.import_note_files([self.source(tmp_path)])
        assert (window.vault.root / "外の資料.md").is_file()

    def test_読み込んだ資料もそのフォルダへ(self, window, tmp_path, monkeypatch) -> None:
        """「ファイル」→「読み込む…」（PDF・画像・PowerPoint）。"""
        from hitofude.ui import export_actions as module

        self.select_folder(window)
        pdf = tmp_path / "講演資料.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(
            module.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(pdf), ""))
        )
        monkeypatch.setattr(module.importer, "to_markdown", lambda *a, **k: "# 講演資料\n\n中身\n")
        window.import_document()
        assert window.wait_for_import(), "取り込みが終わらない"  # 背景スレッドに移った
        assert window.current_note is not None
        assert window.current_note.path.parent == window.vault.root / "資料"

    def test_ゴミ箱を選んでいるときは直下(self, window, tmp_path) -> None:
        """**ゴミ箱に読み込まない。** 捨てた場所に新しいものを置かない。"""
        from hitofude.ui.sidebar import TRASH

        window.set_filter(TRASH)
        window.import_note_files([self.source(tmp_path)])
        assert (window.vault.root / "外の資料.md").is_file()


class TestImportGuards:
    """取り込みの守り（コードレビュー指摘 2026-08-23）。

    どちらも**実際に起きることを確かめてから**直した。
    """

    def source(self, tmp_path):
        path = tmp_path / "外の資料.md"
        path.write_text("# 外の資料\n\n本文\n", encoding="utf-8")
        return path

    def select(self, window, name):
        from hitofude.ui.sidebar import Filter, FilterKind

        window.refresh()
        window.set_filter(Filter(FilterKind.FOLDER, folder=name))

    def test_予約フォルダを指すリンクには入れない(self, window, tmp_path) -> None:
        """**実測で `attachments/` にノートが入り、索引にも幽霊が出ていた。**"""
        link = window.vault.root / "資料"
        link.symlink_to(window.vault.attachments_dir)
        self.select(window, "資料")
        assert window.import_note_files([self.source(tmp_path)]) == []
        assert list(window.vault.attachments_dir.glob("*.md")) == []

    def test_断ったことを知らせる(self, window, tmp_path) -> None:
        link = window.vault.root / "資料"
        link.symlink_to(window.vault.attachments_dir)
        self.select(window, "資料")
        window.import_note_files([self.source(tmp_path)])
        assert "取り込め" in window.notice()

    def test_書けない場所でも落ちない(self, window, tmp_path) -> None:
        """**実測で PermissionError が UI まで出ていた**（Finder で消された
        フォルダを選んだままドロップした状態）。"""
        (window.vault.root / "資料").mkdir()
        self.select(window, "資料")
        (window.vault.root / "資料").rmdir()
        window.vault.root.chmod(0o500)
        try:
            assert window.import_note_files([self.source(tmp_path)]) == []
        finally:
            window.vault.root.chmod(0o755)

    def test_ふつうの取り込みは今まで通り(self, window, tmp_path) -> None:
        (window.vault.root / "資料").mkdir()
        self.select(window, "資料")
        assert window.import_note_files([self.source(tmp_path)])
        assert (window.vault.root / "資料" / "外の資料.md").is_file()
