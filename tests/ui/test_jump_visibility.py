"""飛んだ先が一覧に見えるようにする（ユーザー報告 2026-08-22）。

`[[ノート名]]` を `Cmd+クリック` すると本文は切り替わるのに、**フォルダで
絞っている間は一覧も左の選択もそのまま**だった。飛んだ先がその絞り込みに
入っていないので、選択しようにも行が無い。

「今どれを見ているか」が画面から読めないのは開くだけでは足りない、という
`open_and_select` の考え方（一覧の帯を合わせる）の続き。**見えないなら
絞り込みのほうを動かす。**

飛ぶ入口は 1 つではない（`[[…]]`・検索・バックリンク・戻る）ので、
直すのは `open_and_select` の側。
"""

from pathlib import Path

import pytest

from hitofude.core.document import Note
from hitofude.storage.index_db import ROOT_FOLDER
from hitofude.ui.main_window import MainWindow
from hitofude.ui.sidebar import ALL, PINNED, Filter, FilterKind

pytestmark = pytest.mark.gui


def put(window: MainWindow, relative: str, title: str) -> Path:
    path = window.vault.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n本文\n", encoding="utf-8")
    window.vault_index.upsert_note(Note.read(path), window.vault.root)
    window.refresh()
    return path


def listed(window: MainWindow) -> set[str]:
    model = window.note_list.model()
    return {model.note_at(model.index(row, 0)).title for row in range(model.rowCount())}


def selected(window: MainWindow) -> str | None:
    path = window.note_list.current_path()
    return None if path is None else path.name


class TestJumpOutOfFilter:
    def prepared(self, window: MainWindow) -> Path:
        put(window, "仕事/会議.md", "会議")
        target = put(window, "私用/買い物.md", "買い物")
        window.set_filter(Filter(FilterKind.FOLDER, folder="仕事"))
        return target

    def test_一覧が飛んだ先を含む(self, window) -> None:
        self.prepared(window)
        window.activate_note("買い物")
        assert "買い物" in listed(window)

    def test_一覧の選択も合う(self, window) -> None:
        self.prepared(window)
        window.activate_note("買い物")
        assert selected(window) == "買い物.md"

    def test_左の選択も動く(self, window) -> None:
        """**一覧だけ変わると、今どれで絞っているか分からなくなる**
        （`activate_tag` と同じ考え方）。"""
        self.prepared(window)
        window.activate_note("買い物")
        assert window.sidebar.current_filter() == Filter(FilterKind.FOLDER, folder="私用")

    def test_直下のノートへも飛べる(self, window) -> None:
        put(window, "仕事/会議.md", "会議")
        put(window, "覚え書き.md", "覚え書き")
        window.set_filter(Filter(FilterKind.FOLDER, folder="仕事"))
        window.activate_note("覚え書き")
        assert window.sidebar.current_filter() == Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)
        assert "覚え書き" in listed(window)


class TestKeepsFilter:
    """**見えているなら動かさない。** 絞り込みは操作した人のもの。"""

    def test_同じフォルダの中なら絞り込みは変えない(self, window) -> None:
        put(window, "仕事/会議.md", "会議")
        put(window, "仕事/予算.md", "予算")
        target = Filter(FilterKind.FOLDER, folder="仕事")
        window.set_filter(target)
        window.activate_note("予算")
        assert window.filter == target
        assert selected(window) == "予算.md"

    def test_すべてのままにする(self, window) -> None:
        put(window, "仕事/会議.md", "会議")
        window.set_filter(ALL)
        window.activate_note("会議")
        assert window.filter == ALL
        assert selected(window) == "会議.md"

    def test_お気に入りからは動く(self, window) -> None:
        """ピン留めしていないノートへ飛んだら、そこは見えない。"""
        put(window, "仕事/会議.md", "会議")
        window.set_filter(PINNED)
        window.activate_note("会議")
        assert "会議" in listed(window)


class TestOtherDoors:
    """飛ぶ入口はほかにもある。直したのは共通の口なので全部に効く。"""

    def test_バックリンクから飛んでも見える(self, window) -> None:
        put(window, "仕事/会議.md", "会議")
        target = put(window, "私用/買い物.md", "買い物")
        window.set_filter(Filter(FilterKind.FOLDER, folder="仕事"))
        window.open_and_select(target)
        assert "買い物" in listed(window)
        assert selected(window) == "買い物.md"

    def test_無いノートを作ったときは今まで通り(self, window) -> None:
        """作る道（`_open_created`）は元から面倒を見ている。"""
        put(window, "仕事/会議.md", "会議")
        window.set_filter(Filter(FilterKind.FOLDER, folder="仕事"))
        window.activate_note("まだ無い")
        assert selected(window) == "まだ無い.md"


class TestMoveShowsDestination:
    """「フォルダへ移動…」でも行き先を開く（ユーザー決定 2026-08-22）。

    ドラッグ＆ドロップは行き先を開くのに、メニューからだと元の絞り込みの
    ままで、**移したノートが画面から消えていた**。同じ操作の入口が 2 つ
    あるだけなので、後始末も揃える。
    """

    def prepared(self, window: MainWindow) -> Path:
        put(window, "仕事/会議.md", "会議")
        target = put(window, "仕事/予算.md", "予算")
        window.vault.create_folder("私用")
        window.refresh()
        window.set_filter(Filter(FilterKind.FOLDER, folder="仕事"))
        window.sidebar.select(Filter(FilterKind.FOLDER, folder="仕事"))
        return target

    def test_行き先で絞る(self, window) -> None:
        target = self.prepared(window)
        window.move_note_to(target, "私用")
        assert window.filter == Filter(FilterKind.FOLDER, folder="私用")

    def test_左の選択も行き先へ(self, window) -> None:
        target = self.prepared(window)
        window.move_note_to(target, "私用")
        assert window.sidebar.current_filter() == Filter(FilterKind.FOLDER, folder="私用")

    def test_移したノートが選ばれている(self, window) -> None:
        target = self.prepared(window)
        window.move_note_to(target, "私用")
        assert window.note_list.current_path() == Path("私用/予算.md")

    def test_直下へ戻すときも同じ(self, window) -> None:
        target = self.prepared(window)
        window.move_note_to(target, "")
        assert window.filter == Filter(FilterKind.FOLDER, folder=ROOT_FOLDER)

    def test_移せなければ何も動かさない(self, window) -> None:
        """**失敗して画面だけ動くのがいちばん分かりにくい。**"""
        self.prepared(window)
        window.move_note_to(window.vault.root / "無い.md", "私用")
        assert window.filter == Filter(FilterKind.FOLDER, folder="仕事")


class TestLinkCreatesBeside:
    """`[[まだ無いノート]]` は**書いたノートと同じフォルダ**に作る
    （ユーザー決定 2026-08-22）。

    今までは絞り込みに関係なく保管フォルダ直下だった。リンクは本文の中に
    あるので、**書いた場所の隣**に生えるのがいちばん素直で、絞り込みを
    どう変えても結果が変わらない。
    """

    def test_同じフォルダにできる(self, window) -> None:
        window.open_and_select(put(window, "仕事/会議.md", "会議"))
        window.activate_note("議事録")
        assert window.current_note.path == window.vault.root / "仕事" / "議事録.md"

    def test_絞り込みに引きずられない(self, window) -> None:
        """**書いた場所が基準。** 一覧をどこで絞っていても同じ結果になる。"""
        put(window, "私用/買い物.md", "買い物")
        window.open_and_select(put(window, "仕事/会議.md", "会議"))
        window.set_filter(Filter(FilterKind.FOLDER, folder="私用"))
        window.activate_note("議事録")
        assert window.current_note.path == window.vault.root / "仕事" / "議事録.md"

    def test_直下のノートからは直下(self, window) -> None:
        window.open_and_select(put(window, "覚え書き.md", "覚え書き"))
        window.activate_note("続き")
        assert window.current_note.path == window.vault.root / "続き.md"

    def test_開いていなければ直下(self, window) -> None:
        """パレットなど、本文の外から呼ばれることもある。"""
        window.activate_note("いきなり")
        assert window.current_note.path == window.vault.root / "いきなり.md"

    def test_ゴミ箱の中には作らない(self, window) -> None:
        """捨てたノートを開いたまま書いても、**ゴミ箱にノートを生やさない**。"""
        path = put(window, "仕事/捨てる.md", "捨てる")
        moved = window.vault.trash(path)
        window.open_note(moved)
        window.activate_note("新しい")
        assert window.current_note.path == window.vault.root / "新しい.md"

    def test_作った先が一覧に見える(self, window) -> None:
        window.open_and_select(put(window, "仕事/会議.md", "会議"))
        window.set_filter(ALL)
        window.activate_note("議事録")
        assert "議事録" in listed(window)
