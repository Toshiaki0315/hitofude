"""雛形を本文の途中に差し込む（U-6。ユーザー要望 2026-08-29）。

**新しい概念を増やさない。** 雛形は既にある（`templates/` の `.md`）——
「新しいノートを作る」だけでなく「いま書いている場所へ差し込む」にも
使えれば、短い定型（日付・署名・表の骨）はそれで足りる。

日付などの印（`{{date}}`）は**新規作成と同じ `template.expand`** が埋める。
別に書くと「新規では埋まるのに差し込みでは埋まらない」が起きる。
"""

import pytest
from PySide6.QtGui import QTextCursor

pytestmark = pytest.mark.gui


@pytest.fixture
def ready(window):
    window._vault.templates_dir.mkdir(parents=True, exist_ok=True)
    (window._vault.templates_dir / "あいさつ.md").write_text(
        "お世話になっております。\n{{cursor}}\n", encoding="utf-8"
    )
    note = window._vault.create("下書き", "# 下書き\n\n前の行\n")
    window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(note.path)
    window.editor.moveCursor(QTextCursor.MoveOperation.End)
    return window


class TestInsert:
    def test_本文に入る(self, ready) -> None:
        ready.insert_template("あいさつ")
        assert "お世話になっております。" in ready.editor.toPlainText()

    def test_開いているノートは変わらない(self, ready) -> None:
        """**新しいノートを作らない。** 差し込むだけ。"""
        before = ready.current_note.path
        ready.insert_template("あいさつ")
        assert ready.current_note.path == before

    def test_カーソルの位置に入る(self, ready) -> None:
        cursor = ready.editor.textCursor()
        cursor.setPosition(0)
        ready.editor.setTextCursor(cursor)
        ready.insert_template("あいさつ")
        assert ready.editor.toPlainText().startswith("お世話になっております。")

    def test_印が埋まる(self, ready) -> None:
        """`{{date}}` は**新規作成と同じ道**で埋める。"""
        (ready._vault.templates_dir / "日付.md").write_text("{{date}} の記録\n", encoding="utf-8")
        ready.insert_template("日付")
        assert "{{date}}" not in ready.editor.toPlainText()

    def test_カーソルは印の場所へ(self, ready) -> None:
        """`{{cursor}}` があればそこへ。続けて打てる。"""
        ready.insert_template("あいさつ")
        cursor = ready.editor.textCursor()
        text = ready.editor.toPlainText()
        assert text[: cursor.position()].endswith("お世話になっております。\n")

    def test_取り消しは1回(self, ready) -> None:
        """**1 回の編集**にする（R5 と同じ約束）。2 段に割れると戻しにくい。"""
        before = ready.editor.toPlainText()
        ready.insert_template("あいさつ")
        ready.editor.undo()
        assert ready.editor.toPlainText() == before


class TestSameAsCreate:
    """**新規作成と同じ支度をする**（レビュー指摘 2026-08-31）。

    `create_from_template` は front matter を外し、表の桁を揃えてから
    本文にする。差し込みが `expand` しか通らないと、生の YAML が本文の
    途中に入り、表はずれたまま出る。
    """

    def test_front_matterを持ち込まない(self, ready) -> None:
        (ready._vault.templates_dir / "台帳.md").write_text(
            "---\nid: ABC\n---\n台帳の本文\n", encoding="utf-8"
        )
        ready.insert_template("台帳")
        text = ready.editor.toPlainText()
        assert "台帳の本文" in text
        assert "id: ABC" not in text

    def test_表の桁を揃える(self, ready) -> None:
        """**新規作成と同じ形で入る。** 整形の中身はそちらのテストが見ている。"""
        source = ready._vault.templates_dir / "表.md"
        source.write_text("| 項目 | 値 |\n|---|---|\n| 長い項目名 | 1 |\n", encoding="utf-8")
        created = ready._vault.create_from_template(source).note

        ready.insert_template("表")
        inserted = [line for line in ready.editor.toPlainText().split("\n") if "|" in line]
        expected = [line for line in created.text.split("\n") if "|" in line]
        assert inserted == expected

    def test_絵文字があってもカーソルは印の場所へ(self, ready) -> None:
        """位置の単位を跨ぐ（レビュー指摘 2026-08-31）。

        `expand` が数えるのは Python の文字数、`setPosition` は UTF-16。
        絵文字（非 BMP）が `{{cursor}}` より前にあると 1 文字ぶんずれる。
        """
        (ready._vault.templates_dir / "祝.md").write_text(
            "🎉 おめでとう\n{{cursor}}あと\n", encoding="utf-8"
        )
        cursor = ready.editor.textCursor()
        cursor.setPosition(0)
        ready.editor.setTextCursor(cursor)
        ready.insert_template("祝")
        cursor = ready.editor.textCursor()
        document = ready.editor.document()
        cursor.setPosition(cursor.position(), QTextCursor.MoveMode.MoveAnchor)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
            2,
        )
        assert cursor.selectedText() == "あと"
        assert document is ready.editor.document()


class TestQuiet:
    def test_無い雛形なら何もしない(self, ready) -> None:
        before = ready.editor.toPlainText()
        assert ready.insert_template("無い雛形") is False
        assert ready.editor.toPlainText() == before

    def test_開いていなければ何もしない(self, window) -> None:
        window._note = None
        assert window.insert_template("あいさつ") is False


class TestEntry:
    """入口。**選べる道が無ければ機能が無いのと同じ。**"""

    def test_編集メニューにある(self, ready) -> None:
        from hitofude.ui.commands import commands

        labels = [c.label for c in commands(ready.menuBar())]
        assert "テンプレートを差し込む…" in labels

    def test_パレットで選べる(self, ready) -> None:
        palette = ready.choose_template_to_insert()
        try:
            assert palette is not None
            assert "あいさつ" in [item.title for item in palette.items]
        finally:
            palette.close()

    def test_選ぶと入る(self, ready) -> None:
        palette = ready.choose_template_to_insert()
        try:
            found = next(item for item in palette.items if item.title == "あいさつ")
            palette.chosen.emit(found)
            assert "お世話になっております。" in ready.editor.toPlainText()
        finally:
            palette.close()

    def test_雛形が無ければ知らせる(self, window) -> None:
        """**空のパレットを出さない**（文体チェックと同じ作法）。

        起動時に既定の雛形が置かれるので、消してから見る。
        """
        import shutil

        shutil.rmtree(window._vault.templates_dir, ignore_errors=True)
        note = window._vault.create("下書き", "# 下書き\n\n本文\n")
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_and_select(note.path)
        assert window.choose_template_to_insert() is None
        assert "テンプレート" in window.notice()


class TestWithSelection:
    """選んだ文字を置き換えて差し込む（レビュー指摘 2026-08-30）。

    `cursor.position()` は選択の**終わり**を指すので、置き換えたあとの
    カーソルが選んだ長さぶん後ろへずれていた（実測）。差し込みは選択の
    **始まり**から始まる。
    """

    def select(self, editor, needle: str) -> None:
        from PySide6.QtGui import QTextCursor

        document = editor.document()
        for number in range(document.blockCount()):
            block = document.findBlockByNumber(number)
            if needle in block.text():
                cursor = editor.textCursor()
                start = block.position() + block.text().index(needle)
                cursor.setPosition(start)
                cursor.setPosition(start + len(needle), QTextCursor.MoveMode.KeepAnchor)
                editor.setTextCursor(cursor)
                return
        raise AssertionError(f"{needle} が無い")

    def test_選択は置き換わる(self, ready) -> None:
        ready.editor.setPlainText("# 下書き\n\n消される文字\n")
        self.select(ready.editor, "消される文字")
        ready.insert_template("あいさつ")
        assert "消される文字" not in ready.editor.toPlainText()

    def test_カーソルが印の場所に来る(self, ready) -> None:
        """**これが本題。** 選んだ長さぶんずれていた。"""
        ready.editor.setPlainText("# 下書き\n\n消される文字\n")
        self.select(ready.editor, "消される文字")
        ready.insert_template("あいさつ")
        text = ready.editor.toPlainText()
        position = ready.editor.textCursor().position()
        assert text[:position].endswith("お世話になっております。\n")
