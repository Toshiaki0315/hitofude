"""一覧からのノート操作のテスト（ゴミ箱からの復元 / ピン留め）。

`Vault.restore()` は実装もテストも済んでいたのに **UI から一度も呼ばれて
いなかった**。ゴミ箱を開いても中身を眺めるだけで戻せず、30 日で消えていた。
「お気に入り」フィルタも同様に、絞り込みはできるのに**ピン留めする操作が
無く常に空**だった。ここはその行き止まりの回帰テスト。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import ALL, PINNED, TRASH

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    config = Config(settings)
    config.vault_path = tmp_path / "HitofudeNotes"
    marker = config.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")

    widget = MainWindow(config)
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def make_note(window: MainWindow, title: str, body: str = "本文\n") -> Path:
    # タイトルは本文の H1 から導かれる（document.title_of）。
    # ファイル名だけ付けても一覧には出ない
    note = window.vault.create(title, f"# {title}\n\n{body}")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    return note.path


def titles(window: MainWindow) -> list[str]:
    model = window.note_list.model()
    return [model.index(row).data() for row in range(model.rowCount())]


class TestRestore:
    def test_ゴミ箱から戻せる(self, window) -> None:
        path = make_note(window, "戻すノート")
        trashed = window.vault.trash(path)
        window.refresh()

        restored = window.restore_note(trashed)
        assert restored is not None
        assert restored.parent == window.vault.root
        assert restored.is_file()

    def test_戻すとゴミ箱から消える(self, window) -> None:
        path = make_note(window, "戻すノート")
        trashed = window.vault.trash(path)
        window.restore_note(trashed)
        assert not trashed.exists()

    def test_戻すと一覧に出る(self, window) -> None:
        """索引に入らないと一覧に出ない。ファイルを動かすだけでは足りない。"""
        path = make_note(window, "戻すノート")
        window.trash_note(path)
        assert "戻すノート" not in titles(window)

        window.restore_note(window.vault.trash_dir / "戻すノート.md")
        window.set_filter(ALL)
        assert "戻すノート" in titles(window)

    def test_本文が保たれる(self, window) -> None:
        path = make_note(window, "戻すノート", "# 見出し\n\n**大事な本文**\n")
        restored = window.restore_note(window.vault.trash(path))
        assert "**大事な本文**" in restored.read_text(encoding="utf-8")

    def test_同名が既にあっても上書きしない(self, window) -> None:
        path = make_note(window, "同じ名前", "古いほう\n")
        trashed = window.vault.trash(path)
        make_note(window, "同じ名前", "新しいほう\n")

        restored = window.restore_note(trashed)
        assert restored.name != "同じ名前.md"
        assert "新しいほう" in (window.vault.root / "同じ名前.md").read_text(encoding="utf-8")

    def test_無いファイルを戻してもNone(self, window) -> None:
        assert window.restore_note(window.vault.trash_dir / "居ない.md") is None


class TestPin:
    def test_ピン留めできる(self, window) -> None:
        path = make_note(window, "留めるノート")
        assert window.toggle_pin(path) is True

    def test_もう一度で外れる(self, window) -> None:
        path = make_note(window, "留めるノート")
        window.toggle_pin(path)
        assert window.toggle_pin(path) is False

    def test_お気に入りに出る(self, window) -> None:
        """索引まで届かないとフィルタが空のまま。"""
        path = make_note(window, "留めるノート")
        make_note(window, "留めないノート")

        window.toggle_pin(path)
        window.set_filter(PINNED)
        assert titles(window) == ["留めるノート"]

    def test_外すとお気に入りから消える(self, window) -> None:
        path = make_note(window, "留めるノート")
        window.toggle_pin(path)
        window.toggle_pin(path)
        window.set_filter(PINNED)
        assert titles(window) == []

    def test_本文を変えない(self, window) -> None:
        path = make_note(window, "留めるノート", "# 見出し\n\n**強調**\n")
        window.toggle_pin(path)
        assert "**強調**" in path.read_text(encoding="utf-8")

    def test_開いているノートでも中身が食い違わない(self, window) -> None:
        """ピン留めは front matter を書く。エディタが古い本文のままだと、
        次の保存でピン留めが黙って消える。"""
        path = make_note(window, "開いているノート")
        window.open_note(path)
        window.toggle_pin(path)

        assert window.editor.toPlainText() == path.read_text(encoding="utf-8")

    def test_開いているノートの未保存分を失わない(self, window) -> None:
        path = make_note(window, "開いているノート")
        window.open_note(path)
        window.editor.textCursor().insertText("打ちかけの文字")
        window.toggle_pin(path)

        # 保存で見出しが変わるとファイル名も変わるので、今のパスを見る
        saved = window.current_note.path
        assert "打ちかけの文字" in saved.read_text(encoding="utf-8")
        assert "打ちかけの文字" in window.editor.toPlainText()

    def test_保存で改名されてもピン留めできる(self, window) -> None:
        """`flush()` がファイル名を変えるので、古いパスを掴んだままにしない。"""
        path = make_note(window, "開いているノート")
        window.open_note(path)
        window.editor.textCursor().insertText("# 変わった見出し\n\n")

        assert window.toggle_pin(path) is True
        assert window.current_note.pinned is True

    def test_開いているノートでカーソルが飛ばない(self, window) -> None:
        path = make_note(window, "開いているノート", "一行目\n二行目\n三行目\n")
        window.open_note(path)
        cursor = window.editor.textCursor()
        cursor.setPosition(len(window.editor.toPlainText()) - 3)
        window.editor.setTextCursor(cursor)
        before = window.editor.textCursor().position()

        window.toggle_pin(path)
        assert window.editor.textCursor().position() == before

    def test_無いファイルなら何もしない(self, window) -> None:
        assert window.toggle_pin(window.vault.root / "居ない.md") is False


class TestContextMenu:
    """右クリックで出る項目。フィルタによって中身が変わる。"""

    def labels(self, window, path: Path) -> list[str]:
        menu = window.context_menu_for(path.relative_to(window.vault.root))
        try:
            return [action.text() for action in menu.actions() if action.text()]
        finally:
            menu.deleteLater()

    def test_ゴミ箱では元に戻すを出す(self, window) -> None:
        path = make_note(window, "ノート")
        trashed = window.vault.trash(path)
        window.set_filter(TRASH)
        assert "元に戻す" in self.labels(window, trashed)

    def test_ゴミ箱ではピン留めを出さない(self, window) -> None:
        path = make_note(window, "ノート")
        trashed = window.vault.trash(path)
        window.set_filter(TRASH)
        assert "ピン留め" not in self.labels(window, trashed)

    def test_通常はピン留めを出す(self, window) -> None:
        assert "ピン留め" in self.labels(window, make_note(window, "ノート"))

    def test_留めてあるなら外す表示になる(self, window) -> None:
        path = make_note(window, "ノート")
        window.toggle_pin(path)
        assert "ピン留めを外す" in self.labels(window, path)

    def test_ゴミ箱へ移動も出す(self, window) -> None:
        path = make_note(window, "ノート")
        assert "ゴミ箱へ移動" in self.labels(window, path)

    def test_右クリックが有効になっている(self, window) -> None:
        from PySide6.QtCore import Qt

        assert window.note_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


class TestPinnedIsProtected:
    """ピン留めしたノートはゴミ箱へ移せない。

    ピン留めは「これは残す」という意思表示なので、削除と噛み合わない。
    黙って無視すると押し間違いに気づけないため、理由を伝える。
    """

    def test_ゴミ箱へ移せない(self, window) -> None:
        path = make_note(window, "留めたノート")
        window.toggle_pin(path)

        assert window.trash_note(path) is False
        assert path.is_file()

    def test_一覧から消えない(self, window) -> None:
        path = make_note(window, "留めたノート")
        window.toggle_pin(path)
        window.trash_note(path)
        window.set_filter(ALL)
        assert "留めたノート" in titles(window)

    def test_開いているノートでも消えない(self, window) -> None:
        path = make_note(window, "留めたノート")
        window.toggle_pin(path)
        window.open_note(path)

        assert window.trash_current() is False
        assert window.current_note is not None
        assert window.editor.toPlainText() != ""

    def test_理由が伝わる(self, window) -> None:
        """黙って何も起きないと、壊れたのか効かないのか分からない。"""
        path = make_note(window, "留めたノート")
        window.toggle_pin(path)
        window.trash_note(path)
        assert "ピン留め" in window.statusBar().currentMessage()

    def test_ピン留めを外せば消せる(self, window) -> None:
        path = make_note(window, "留めたノート")
        window.toggle_pin(path)
        window.toggle_pin(path)

        assert window.trash_note(path) is True
        assert not path.exists()

    def test_留めていなければ今まで通り消せる(self, window) -> None:
        path = make_note(window, "ふつうのノート")
        assert window.trash_note(path) is True
        assert not path.exists()

    def test_留めていない現在のノートも消せる(self, window) -> None:
        path = make_note(window, "ふつうのノート")
        window.open_note(path)
        assert window.trash_current() is True
        assert window.current_note is None

    def test_右クリックのゴミ箱へ移動が無効になる(self, window) -> None:
        """項目ごと消すと理由が分からない。押せない状態で見せる。"""
        path = make_note(window, "留めたノート")
        window.toggle_pin(path)

        menu = window.context_menu_for(path.relative_to(window.vault.root))
        try:
            trash = next(a for a in menu.actions() if a.text() == "ゴミ箱へ移動")
            assert trash.isEnabled() is False
        finally:
            menu.deleteLater()

    def test_留めていなければ有効なまま(self, window) -> None:
        path = make_note(window, "ふつうのノート")
        menu = window.context_menu_for(path.relative_to(window.vault.root))
        try:
            trash = next(a for a in menu.actions() if a.text() == "ゴミ箱へ移動")
            assert trash.isEnabled() is True
        finally:
            menu.deleteLater()

    def test_ゴミ箱の中身には関係しない(self, window) -> None:
        """ゴミ箱にあるノートは既に削除済み。ここでピン留めは見ない。"""
        path = make_note(window, "ノート")
        trashed = window.vault.trash(path)
        window.set_filter(TRASH)
        labels = [
            a.text()
            for a in window.context_menu_for(trashed.relative_to(window.vault.root)).actions()
        ]
        # ピン留めの類は出さない。出せるのは「元に戻す」と「完全に削除…」（G-3）
        assert [label for label in labels if label] == ["元に戻す", "完全に削除…"]


class TestAttachmentWiring:
    """貼り付けた画像が vault に落ちて、書き出しにも出る（タスク A-2）。"""

    def png(self) -> bytes:
        from PySide6.QtCore import QBuffer, QByteArray
        from PySide6.QtGui import QColor, QImage

        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        storage = QByteArray()
        buffer = QBuffer(storage)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return bytes(storage)

    def test_エディタに受け口が繋がっている(self, window) -> None:
        assert window.save_attachment(self.png(), ".png") is not None

    def test_attachmentsに保存される(self, window) -> None:
        window.save_attachment(self.png(), ".png")
        saved = list(window.vault.attachments_dir.glob("*.png"))
        assert len(saved) == 1
        assert saved[0].read_bytes() == self.png()

    def test_返るのは相対リンク(self, window) -> None:
        link = window.save_attachment(self.png(), ".png")
        assert link.startswith("![](attachments/")
        assert str(window.vault.root) not in link

    def test_貼り付けから本文へ入る(self, window) -> None:
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QColor, QImage

        path = make_note(window, "画像を貼るノート")
        window.open_note(path)

        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        mime = QMimeData()
        mime.setImageData(image)
        window.editor.insertFromMimeData(mime)

        assert "![](attachments/" in window.editor.toPlainText()

    def test_保存したノートに残る(self, window) -> None:
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QColor, QImage

        path = make_note(window, "画像を貼るノート")
        window.open_note(path)
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        mime = QMimeData()
        mime.setImageData(image)
        window.editor.insertFromMimeData(mime)
        window.flush()

        assert "![](attachments/" in window.current_note.path.read_text(encoding="utf-8")

    def test_HTML書き出しに画像が埋まる(self, window, tmp_path: Path) -> None:
        path = make_note(window, "画像のノート")
        window.open_note(path)
        link = window.save_attachment(self.png(), ".png")
        window.editor.textCursor().insertText(f"\n{link}\n")
        window.flush()

        target = window._exports._write_html(tmp_path / "out.html", window.editor.toPlainText())
        assert "data:image/png;base64," in target.read_text(encoding="utf-8")

    def test_PDF書き出しでも落ちない(self, window, tmp_path: Path) -> None:
        path = make_note(window, "画像のノート")
        window.open_note(path)
        link = window.save_attachment(self.png(), ".png")
        window.editor.textCursor().insertText(f"\n{link}\n")

        target = window._exports._write_pdf(tmp_path / "out.pdf", window.editor.toPlainText())
        assert target.read_bytes().startswith(b"%PDF")

    def test_添付は一覧に出てこない(self, window) -> None:
        window.save_attachment(self.png(), ".png")
        window.refresh()
        assert all("attachments" not in t for t in titles(window) if t)


class TestRename:
    """タイトルの付け替え（タスク A-3 / ADR-0005）。

    ファイル名ではなく**本文の見出し**を書き換える。タイトルは本文から
    導かれるので、ファイル名だけ変えても一覧の表示が変わらず、
    真実が 2 つになる。ファイル名は保存時に見出しへ追従する。
    """

    def test_一覧の表示が変わる(self, window) -> None:
        path = make_note(window, "元の題")
        window.rename_note(path, "新しい題")
        window.set_filter(ALL)
        assert "新しい題" in titles(window)
        assert "元の題" not in titles(window)

    def test_本文の見出しが書き換わる(self, window) -> None:
        path = make_note(window, "元の題")
        window.rename_note(path, "新しい題")
        text = window.current_note.path.read_text(encoding="utf-8") if window.current_note else ""
        target = text or (window.vault.root / "新しい題.md").read_text(encoding="utf-8")
        assert "# 新しい題" in target

    def test_ファイル名も追従する(self, window) -> None:
        path = make_note(window, "元の題")
        renamed = window.rename_note(path, "新しい題")
        assert renamed.name == "新しい題.md"
        assert not path.exists()

    def test_本文は失われない(self, window) -> None:
        path = make_note(window, "元の題", "大事な本文\n")
        renamed = window.rename_note(path, "新しい題")
        assert "大事な本文" in renamed.read_text(encoding="utf-8")

    def test_開いているノートでも変えられる(self, window) -> None:
        path = make_note(window, "元の題")
        window.open_note(path)
        window.rename_note(path, "新しい題")
        assert window.current_note.title == "新しい題"
        assert "# 新しい題" in window.editor.toPlainText()

    def test_開いているノートならUndoで戻せる(self, window) -> None:
        """本文の編集なので、打ち間違えたら戻せるべき。"""
        path = make_note(window, "元の題")
        window.open_note(path)
        window.rename_note(path, "新しい題")
        window.editor.undo()
        assert "# 元の題" in window.editor.toPlainText()

    def test_見出しの無いノートには足す(self, window) -> None:
        path = window.vault.create("素のノート", "ただの段落です。\n")
        window.vault_index.upsert_note(path, window.vault.root)
        window.refresh()
        renamed = window.rename_note(path.path, "付けた題")
        text = renamed.read_text(encoding="utf-8")
        assert "# 付けた題" in text
        assert "ただの段落です。" in text

    def test_空の題は無視する(self, window) -> None:
        path = make_note(window, "元の題")
        assert window.rename_note(path, "   ") == path
        assert path.is_file()

    def test_使えない文字が入っていても壊れない(self, window) -> None:
        path = make_note(window, "元の題")
        renamed = window.rename_note(path, "a/b:c")
        assert renamed.is_file()
        assert "/" not in renamed.stem

    def test_見出しには打った通り入る(self, window) -> None:
        """ファイル名では使えない文字も、本文には書ける。"""
        path = make_note(window, "元の題")
        renamed = window.rename_note(path, "a/b:c")
        assert "# a/b:c" in renamed.read_text(encoding="utf-8")

    def test_front_matterが残る(self, window) -> None:
        path = make_note(window, "元の題")
        renamed = window.rename_note(path, "新しい題")
        assert renamed.read_text(encoding="utf-8").startswith("---\n")

    def test_右クリックに出る(self, window) -> None:
        path = make_note(window, "ノート")
        menu = window.context_menu_for(path.relative_to(window.vault.root))
        try:
            assert "名前を変更…" in [a.text() for a in menu.actions() if a.text()]
        finally:
            menu.deleteLater()

    def test_ゴミ箱では出さない(self, window) -> None:
        path = make_note(window, "ノート")
        trashed = window.vault.trash(path)
        window.set_filter(TRASH)
        labels = [
            a.text()
            for a in window.context_menu_for(trashed.relative_to(window.vault.root)).actions()
        ]
        assert "名前を変更…" not in labels


class TestPlaceManual:
    """ヘルプ →「使い方のノートを置き直す」。

    説明が増えても既に置いたノートは古いまま残るので、最新版を出す道を
    ひとつ用意する（`Vault.place_manual`）。
    """

    def test_置いて開く(self, window) -> None:
        window.place_manual()
        assert "使い方" in window.windowTitle()

    def test_一覧に出る(self, window) -> None:
        before = len(titles(window))
        window.place_manual()
        assert len(titles(window)) == before + 1

    def test_何度でも置ける(self, window) -> None:
        window.place_manual()
        first = window.current_note.path
        window.place_manual()
        assert window.current_note.path != first


class TestSortOrder:
    """並び順の切り替え（C-3）。一覧まで届くこと。"""

    def test_起動時に設定を読む(self, qtbot, tmp_path) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.storage.index_db import SortOrder
        from hitofude.ui.main_window import MainWindow

        settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.vault_path = tmp_path / "Notes"
        config.sort_order = SortOrder.TITLE
        window = MainWindow(config)
        qtbot.addWidget(window)
        assert window.note_list_pane.sort_order() is SortOrder.TITLE

    def test_選ぶと並びが変わる(self, window) -> None:
        from hitofude.storage.index_db import SortOrder

        for title in ("う", "い", "あ"):
            make_note(window, title)
        window.set_sort_order(SortOrder.TITLE)
        assert titles(window)[:3] == ["あ", "い", "う"]

    def test_選んだ並びを覚える(self, window) -> None:
        from hitofude.storage.index_db import SortOrder

        window.set_sort_order(SortOrder.CREATED)
        assert window._config.sort_order is SortOrder.CREATED

    def test_タグで絞っても効く(self, window) -> None:
        from hitofude.storage.index_db import SortOrder
        from hitofude.ui.sidebar import Filter, FilterKind

        for title in ("う", "い", "あ"):
            make_note(window, title, "本文\n\n#共通\n")
        window.set_sort_order(SortOrder.TITLE)
        window.set_filter(Filter(kind=FilterKind.TAG, tag="共通"))
        assert titles(window) == ["あ", "い", "う"]


class TestTagCompletion:
    """タグ補完が索引と繋がっていること（C-4）。"""

    def test_索引のタグが候補になる(self, window) -> None:
        make_note(window, "メモ", "本文\n\n#日報\n")
        assert "日報" in window._known_tags()

    def test_名前順に並ぶ(self, window) -> None:
        make_note(window, "メモ", "本文\n\n#日報 #あ行 #仕事\n")
        assert window._known_tags() == sorted(window._known_tags())

    def test_エディタに渡っている(self, window) -> None:
        make_note(window, "メモ", "本文\n\n#日報\n")
        window.editor.setPlainText("#日")
        window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
        window.editor.update_tag_completion()
        assert window.editor.tag_candidates() == ["日報"]


class TestActivation:
    """`Cmd+クリック` の受け側（D-1 / D-2）。

    **開くのは `MainWindow`。** エディタは「押された」ことだけを知らせる。
    """

    def test_タグで絞り込む(self, window) -> None:
        make_note(window, "日報のメモ", "本文\n\n#日報\n")
        make_note(window, "関係ないノート", "本文\n")
        window.activate_tag("日報")
        assert titles(window) == ["日報のメモ"]

    def test_サイドバーの選択も変わる(self, window) -> None:
        """一覧だけ変わってサイドバーが元のままだと、今の絞り込みが分からない。"""
        make_note(window, "メモ", "本文\n\n#日報\n")
        window.activate_tag("日報")
        assert window.sidebar.current_filter().tag == "日報"

    def test_知らないタグでも落ちない(self, window) -> None:
        window.activate_tag("存在しないタグ")
        assert titles(window) == []

    def test_リンクを開く(self, window, monkeypatch) -> None:
        opened = []
        monkeypatch.setattr(
            "hitofude.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url)
        )
        window.activate_link("https://example.com")
        assert [url.toString() for url in opened] == ["https://example.com"]

    def test_危ないスキームは開かない(self, window, monkeypatch) -> None:
        """判定は `core/activation.py` にあるが、受け口でも二重に確かめる。"""
        opened = []
        monkeypatch.setattr(
            "hitofude.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url)
        )
        window.activate_link("javascript:alert(1)")
        assert opened == []

    def test_エディタと繋がっている(self, window) -> None:
        """信号の受け手を数える API は使わない（PySide では扱いが違う）。
        実際に飛ばして結果を見る。"""
        make_note(window, "メモ", "本文\n\n#日報\n")
        window.editor.tag_activated.emit("日報")
        assert titles(window) == ["メモ"]


class TestPreviewAndCopy:
    """ブラウザで確認（E-2）と HTML をコピー（E-3）。"""

    def test_ブラウザで開く(self, window, monkeypatch) -> None:
        opened = []
        monkeypatch.setattr(
            "hitofude.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url)
        )
        window.open_note(make_note(window, "メモ", "本文\n"))
        window.preview_in_browser()
        assert len(opened) == 1
        assert opened[0].isLocalFile()

    def test_開く前に書き出す(self, window, monkeypatch) -> None:
        """開いたときに古い内容が出ないよう、押した時点の本文を書く。"""
        from pathlib import Path

        monkeypatch.setattr("hitofude.ui.main_window.QDesktopServices.openUrl", lambda url: None)
        window.open_note(make_note(window, "メモ", "本文\n"))
        window.editor.textCursor().insertText("追記した")
        window.preview_in_browser()
        import tempfile

        from hitofude.editor.exporter import PREVIEW_NAME

        target = Path(tempfile.gettempdir()) / PREVIEW_NAME
        assert "追記した" in target.read_text(encoding="utf-8")

    def test_ノートが無ければ何もしない(self, window, monkeypatch) -> None:
        opened = []
        monkeypatch.setattr(
            "hitofude.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url)
        )
        window.preview_in_browser()
        assert opened == []

    def test_HTMLをコピーする(self, window) -> None:
        from PySide6.QtWidgets import QApplication

        window.open_note(make_note(window, "メモ", "**強調**\n"))
        window.copy_as_html()
        assert "<strong>強調</strong>" in QApplication.clipboard().mimeData().html()

    def test_コピーはノートが無ければ何もしない(self, window) -> None:
        """**クリップボードを空にして確かめない。** `clear()` のあとの
        `mimeData()` は None を返すことがある（offscreen で踏んだ）。
        目印を置いて、消えていないことを見る。"""
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("目印")
        window.copy_as_html()
        assert QApplication.clipboard().text() == "目印"
