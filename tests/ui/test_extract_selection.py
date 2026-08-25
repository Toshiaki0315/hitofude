"""選択範囲をノートにする（M-1 / 仮身化）。

BTRON の仮身化を Markdown に写したもの。切り分けの判断（題名・本文・
リンク）は `core/extract.py` にあり、ここが見るのは**配線**——どこに作るか、
本文がどう置き換わるか、Undo が何段になるか。

**Undo が 1 段であることが山場。** 選択を消してから挿すと 2 段になり、
`Cmd+Z` 1 回で戻らない。Phase 2 からの約束（R5）。
"""

import pytest
from PySide6.QtCore import Qt

from hitofude.core.document import UNTITLED

pytestmark = pytest.mark.gui

BODY = """# 会議メモ

来週の話をした。

# 買い物リスト

- 卵
- 牛乳
"""


@pytest.fixture
def opened(window):
    """本文の入ったノートを 1 つ開いた状態。"""
    note = window._vault.create("会議メモ", BODY)
    window.refresh()
    window.open_and_select(note.path)
    return window


def select(window, text: str) -> None:
    """本文の中の `text` を選ぶ。"""
    document = window.editor.document()
    found = document.find(text)
    assert not found.isNull(), f"{text!r} が本文に無い"
    # 見つかった語から、そこを含む段落の終わりまでを選ぶ
    cursor = window.editor.textCursor()
    cursor.setPosition(found.selectionStart())
    cursor.setPosition(len(window.editor.toPlainText()), cursor.MoveMode.KeepAnchor)
    window.editor.setTextCursor(cursor)


class TestNothingSelected:
    def test_選んでいなければ何も起きない(self, opened) -> None:
        before = opened.editor.toPlainText()
        assert opened.extract_selection() is None
        assert opened.editor.toPlainText() == before

    def test_空白だけ選んでも何も起きない(self, opened) -> None:
        """空のノートを作らない（取り込みと同じ約束）。"""
        text = opened.editor.toPlainText()
        start = text.index("来週") - 2  # 見出しと本文の間の空行
        assert not text[start : start + 2].strip(), "空白を選べていない"
        cursor = opened.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + 2, cursor.MoveMode.KeepAnchor)
        opened.editor.setTextCursor(cursor)
        assert opened.extract_selection() is None

    def test_変換中は動かない(self, opened) -> None:
        """R6。プリエディットは本文に入っていないので、切り出すと文が壊れる。"""
        select(opened, "# 買い物リスト")
        opened.editor._composing = True
        try:
            assert opened.extract_selection() is None
        finally:
            opened.editor._composing = False

    def test_選んでいなければメニューは灰色(self, opened) -> None:
        action = opened.menu_actions["選択範囲をノートにする"]
        opened.sync_edit_actions()
        assert not action.isEnabled()

    def test_選べば押せる(self, opened) -> None:
        select(opened, "# 買い物リスト")
        opened.sync_edit_actions()
        assert opened.menu_actions["選択範囲をノートにする"].isEnabled()


class TestExtract:
    def test_新しいノートができる(self, opened) -> None:
        select(opened, "# 買い物リスト")
        path = opened.extract_selection()
        assert path is not None
        assert path.exists()

    def test_選んだ文が新しいノートに入る(self, opened) -> None:
        select(opened, "# 買い物リスト")
        path = opened.extract_selection()
        text = path.read_text(encoding="utf-8")
        assert "- 卵" in text
        assert "- 牛乳" in text

    def test_跡にリンクが残る(self, opened) -> None:
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        found = opened.editor.toPlainText()
        assert "[[買い物リスト]]" in found
        assert "- 卵" not in found

    def test_選んでいない文は残る(self, opened) -> None:
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert "来週の話をした。" in opened.editor.toPlainText()

    def test_切り出した先は開かない(self, opened) -> None:
        """**書いている流れを切らない。** 執筆の途中に呼ぶ操作なので。"""
        before = opened.current_note.path
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert opened.current_note.path == before

    def test_知らせる(self, opened) -> None:
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert "買い物リスト" in opened.notice()


class TestUndo:
    def test_取り消し_1_回で戻る(self, opened) -> None:
        """**山場**（R5 / Phase 2 の完了条件）。2 段になると本文が半端に戻る。"""
        before = opened.editor.toPlainText()
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert opened.editor.toPlainText() != before
        opened.editor.undo()
        assert opened.editor.toPlainText() == before


class TestShortcut:
    """**ユーザーが辿る経路そのものを通す**（`test_appearance.py` と同じ作法）。

    `Cmd+Shift+X` に割り当てたときは、エディタが打ち消し線で先に受けていて
    **メニューの表示だけが嘘**だった（実測）。キーは押して確かめる。

    **窓を表示しないとメニューのショートカットは発火しない**（`QAction` の
    既定は `WindowShortcut` で、活きていない窓には届かない）。実測で
    `fired: []` になったので、`test_appearance.py` と同じく `show()` する。
    """

    @pytest.fixture
    def shown(self, opened, activate):
        return activate(opened)

    def test_キーを押すと切り出される(self, shown, qtbot) -> None:
        opened = shown
        select(opened, "# 買い物リスト")
        qtbot.keyClick(
            opened.editor,
            Qt.Key.Key_K,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        found = opened.editor.toPlainText()
        assert "[[買い物リスト]]" in found
        assert "- 卵" not in found

    def test_打ち消し線は今まで通り(self, shown, qtbot) -> None:
        """**奪っていないこと**を見る（`Cmd+Shift+X` は打ち消し線のまま）。"""
        opened = shown
        select(opened, "# 買い物リスト")
        qtbot.keyClick(
            opened.editor,
            Qt.Key.Key_X,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        found = opened.editor.toPlainText()
        assert "~~" in found
        assert "[[" not in found


class TestWhereItGoes:
    def test_元のノートと同じフォルダに作る(self, window) -> None:
        """`[[まだ無いノート]]` と同じ規則（ユーザー決定 2026-08-23）。"""
        folder = window._vault.root / "仕事"
        folder.mkdir()
        note = window._vault.create("会議メモ", BODY, folder="仕事")
        window.refresh()
        window.open_and_select(note.path)
        select(window, "# 買い物リスト")
        path = window.extract_selection()
        assert path.parent == folder

    def test_一覧で別のフォルダを選んでいても元の隣(self, window) -> None:
        """**書いた場所の隣に生やす。** 絞り込みで結果が変わらない。"""
        from hitofude.ui.sidebar import Filter, FilterKind

        folder = window._vault.root / "仕事"
        folder.mkdir()
        (window._vault.root / "私用").mkdir()
        note = window._vault.create("会議メモ", BODY, folder="仕事")
        window.refresh()
        window.open_and_select(note.path)
        window.set_filter(Filter(FilterKind.FOLDER, folder="私用"))
        select(window, "# 買い物リスト")
        assert window.extract_selection().parent == folder


class TestIndexed:
    def test_索引に入る(self, opened) -> None:
        """入らないと、バックリンクにも検索にも出ない。"""
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert "買い物リスト" in opened._db.titles()

    def test_元のノートからのリンクが引ける(self, opened) -> None:
        """切り出した先で「どこから来たか」が分かる（E-6 の帯）。"""
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert [row.title for row in opened._db.backlinks("買い物リスト")] == ["会議メモ"]

    def test_リンクを押すと切り出した先へ飛ぶ(self, opened) -> None:
        """**不変条件の通し確認。** 新しく作られてしまったら題名がずれている。"""
        select(opened, "# 買い物リスト")
        path = opened.extract_selection()
        assert opened.activate_note("買い物リスト") == path


class TestDuplicateTitles:
    def test_同じ題名は避ける(self, opened) -> None:
        first = opened._vault.create("買い物リスト", "# 買い物リスト\n\n先に作ったほう")
        opened._db.upsert_note(first, opened._vault.root)  # refresh は走査しない
        opened.refresh()
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        assert "[[買い物リスト 2]]" in opened.editor.toPlainText()

    def test_避けた先にちゃんと飛ぶ(self, opened) -> None:
        first = opened._vault.create("買い物リスト", "# 買い物リスト\n\n先に作ったほう")
        opened._db.upsert_note(first, opened._vault.root)  # refresh は走査しない
        opened.refresh()
        select(opened, "# 買い物リスト")
        path = opened.extract_selection()
        assert opened.activate_note("買い物リスト 2") == path


class TestTrash:
    def test_ゴミ箱の中で切り出しても直下に作る(self, window) -> None:
        """**捨てた場所にノートを生やさない**（`_link_folder` と同じ）。"""
        note = window._vault.create("会議メモ", BODY)
        window.refresh()
        trashed = window._vault.trash(note.path)
        window.refresh()
        window.open_note(trashed)
        select(window, "# 買い物リスト")
        path = window.extract_selection()
        assert path.parent == window._vault.root


class TestFallbackTitle:
    def test_題名にできる文字が無ければ無題(self, opened) -> None:
        cursor = opened.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("\n\n[[|]]\n")
        found = opened.editor.document().find("[[|]]")
        cursor.setPosition(found.selectionStart())
        cursor.setPosition(found.selectionEnd(), cursor.MoveMode.KeepAnchor)
        opened.editor.setTextCursor(cursor)
        path = opened.extract_selection()
        assert path is not None
        assert f"[[{UNTITLED}]]" in opened.editor.toPlainText()


class TestSourceIsTruth:
    def test_保存されるのは画面の文字(self, opened) -> None:
        """R1。切り出した後の本文がそのままファイルに入る。"""
        select(opened, "# 買い物リスト")
        opened.extract_selection()
        opened.flush()
        saved = opened.current_note.path.read_text(encoding="utf-8")
        assert "[[買い物リスト]]" in saved
        assert "- 卵" not in saved
