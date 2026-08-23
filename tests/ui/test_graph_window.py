"""リンクの図の窓（M-2 / 仮身ネットワーク）。

図の形と座標は `core/graph.py` が決める（R3）。ここが見るのは**配線**——
起点はどこか、深さを変えたら何が変わるか、点を押したら何が起きるか。

**図は読むためのもの。** 図の上でノートを作ったり繋ぎ替えたりはしない
（真実は `.md` の側にある。R1）。
"""

import pytest
from PySide6.QtCore import QPoint, Qt

from hitofude.core import graph

pytestmark = pytest.mark.gui


@pytest.fixture
def related(window):
    """続柄の付いたリンク（M-3）。「参考文献」と「元ネタ」の 2 種類。"""
    texts = {
        "会議メモ": "# 会議メモ\n\n- 参考文献: [[本]]\n- 元ネタ: [[日報]]\n",
        "本": "# 本\n\nBTRON の話\n",
        "日報": "# 日報\n\n書いた\n",
    }
    for title, text in texts.items():
        note = window._vault.create(title, text)
        window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(window._vault.root / "会議メモ.md")
    return window


class TestRelationFilter:
    """図を続柄で絞る（M-3 の使い道）。**BTRON の続柄はリンクに付く。**"""

    def test_続柄が選べる(self, related) -> None:
        dialog = related.build_graph_window()
        try:
            found = [dialog.relation_box.itemText(i) for i in range(dialog.relation_box.count())]
            assert found == ["すべての続柄", "元ネタ", "参考文献"]
        finally:
            dialog.close()

    def test_既定は絞らない(self, related) -> None:
        dialog = related.build_graph_window()
        try:
            assert dialog.relation() is None
            assert {node.title for node in dialog.graph().nodes} == {"会議メモ", "本", "日報"}
        finally:
            dialog.close()

    def test_選ぶとその関係だけになる(self, related) -> None:
        dialog = related.build_graph_window()
        try:
            dialog.set_relation("参考文献")
            assert {node.title for node in dialog.graph().nodes} == {"会議メモ", "本"}
        finally:
            dialog.close()

    def test_別の関係を選べば入れ替わる(self, related) -> None:
        dialog = related.build_graph_window()
        try:
            dialog.set_relation("元ネタ")
            assert {node.title for node in dialog.graph().nodes} == {"会議メモ", "日報"}
        finally:
            dialog.close()

    def test_すべてに戻せる(self, related) -> None:
        dialog = related.build_graph_window()
        try:
            dialog.set_relation("参考文献")
            dialog.set_relation(None)
            assert len(dialog.graph().nodes) == 3
        finally:
            dialog.close()

    def test_絞っても起点は残る(self, related) -> None:
        """**起点が消えると図が空になる。** 何を見ているか分からなくなる。"""
        dialog = related.build_graph_window()
        try:
            dialog.set_relation("元ネタ")
            assert dialog.graph().nodes[0].title == "会議メモ"
        finally:
            dialog.close()

    def test_続柄が無ければ選択肢も出さない(self, linked) -> None:
        """**要らないものを置かない。** 使っていない機能の枠が並ぶと邪魔。"""
        dialog = linked.build_graph_window()
        try:
            assert not dialog.relation_box.isVisibleTo(dialog)
        finally:
            dialog.close()

    def test_絞ったまま深さも変えられる(self, related) -> None:
        dialog = related.build_graph_window()
        try:
            dialog.set_relation("参考文献")
            dialog.set_depth(1)
            assert {node.title for node in dialog.graph().nodes} == {"会議メモ", "本"}
            assert dialog.relation() == "参考文献"
        finally:
            dialog.close()


@pytest.fixture
def linked(window):
    """会議メモ → 買い物リスト → 卵の店、日報 → 会議メモ の 4 本。"""
    texts = {
        "会議メモ": "# 会議メモ\n\n[[買い物リスト]] を見る\n",
        "買い物リスト": "# 買い物リスト\n\n[[卵の店]] と [[まだ無いノート]]\n",
        "卵の店": "# 卵の店\n\n駅前\n",
        "日報": "# 日報\n\n[[会議メモ]] を書いた\n",
    }
    for title, text in texts.items():
        note = window._vault.create(title, text)
        window._db.upsert_note(note, window._vault.root)
    window.refresh()
    window.open_and_select(window._vault.root / "会議メモ.md")
    return window


class TestOpen:
    def test_開ける(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            assert dialog is not None
        finally:
            dialog.close()

    def test_今のノートが起点(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            assert dialog.graph().nodes[0].title == "会議メモ"
            assert dialog.graph().nodes[0].depth == 0
        finally:
            dialog.close()

    def test_繋がっているノートが出る(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            titles = {node.title for node in dialog.graph().nodes}
            assert {"買い物リスト", "日報", "卵の店"} <= titles
        finally:
            dialog.close()

    def test_ノートを開いていなければ出さない(self, window) -> None:
        """**起点が無い図は描けない。** 何を見ているか分からない絵になる。"""
        assert window.build_graph_window() is None

    def test_メニューにある(self, linked) -> None:
        assert "リンクの図…" in linked.menu_actions


class TestDepth:
    def test_既定は_2_段(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            assert dialog.depth() == graph.DEFAULT_DEPTH
        finally:
            dialog.close()

    def test_浅くすると減る(self, linked) -> None:
        """記事の「何段階先まで表示するか指定できる」。**絞り方はこれしかない。**"""
        dialog = linked.build_graph_window()
        try:
            before = len(dialog.graph().nodes)
            dialog.set_depth(1)
            assert len(dialog.graph().nodes) < before
            assert "卵の店" not in {node.title for node in dialog.graph().nodes}
        finally:
            dialog.close()

    def test_深くすると増える(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            dialog.set_depth(1)
            few = len(dialog.graph().nodes)
            dialog.set_depth(3)
            assert len(dialog.graph().nodes) > few
        finally:
            dialog.close()

    def test_選んだ深さを覚える(self, linked) -> None:
        """毎回選び直させない（開閉のたびに戻ると使えない）。"""
        dialog = linked.build_graph_window()
        try:
            dialog.set_depth(1)
        finally:
            dialog.close()
        again = linked.build_graph_window()
        try:
            assert again.depth() == 1
        finally:
            again.close()


class TestPlaces:
    def test_点の数だけ場所がある(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            assert len(dialog.view.places) == len(dialog.graph().nodes)
        finally:
            dialog.close()

    def test_深さを変えたら場所も作り直す(self, linked) -> None:
        """**古い座標を使い回すと点がはみ出す**（数が合わない）。"""
        dialog = linked.build_graph_window()
        try:
            dialog.set_depth(1)
            assert len(dialog.view.places) == len(dialog.graph().nodes)
        finally:
            dialog.close()


class TestClick:
    def _center(self, dialog, title: str) -> QPoint:
        number = next(
            index for index, node in enumerate(dialog.graph().nodes) if node.title == title
        )
        return dialog.view.point_of(number)

    def test_点を押すとそのノートが開く(self, linked, qtbot) -> None:
        dialog = linked.build_graph_window()
        try:
            dialog.resize(600, 400)
            qtbot.mouseClick(
                dialog.view, Qt.MouseButton.LeftButton, pos=self._center(dialog, "買い物リスト")
            )
            assert linked.current_note.title == "買い物リスト"
        finally:
            dialog.close()

    def test_押したら窓は閉じる(self, linked, qtbot) -> None:
        """**飛んだら閉じる**（`Cmd+R` のパレットと同じ作法）。"""
        dialog = linked.build_graph_window()
        dialog.resize(600, 400)
        qtbot.mouseClick(
            dialog.view, Qt.MouseButton.LeftButton, pos=self._center(dialog, "買い物リスト")
        )
        assert not dialog.isVisible()

    def test_まだ無いノートの点では作らない(self, linked, qtbot) -> None:
        """**図の上でノートを作らない。** 真実は `.md` の側にある（R1）。"""
        dialog = linked.build_graph_window()
        try:
            dialog.resize(600, 400)
            before = set(linked._db.titles())
            qtbot.mouseClick(
                dialog.view,
                Qt.MouseButton.LeftButton,
                pos=self._center(dialog, "まだ無いノート"),
            )
            assert set(linked._db.titles()) == before
            assert "まだ無い" in linked.notice() or "まだ無い" in dialog.notice()
        finally:
            dialog.close()

    def test_何も無いところを押しても何も起きない(self, linked, qtbot) -> None:
        dialog = linked.build_graph_window()
        try:
            dialog.resize(600, 400)
            before = linked.current_note.title
            qtbot.mouseClick(dialog.view, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
            assert linked.current_note.title == before
        finally:
            dialog.close()


class TestDrawing:
    def test_起点は大きく描く(self, linked) -> None:
        """**色だけでは埋もれる。** 34 点の図を描いて見て分かった（実測）。"""
        from hitofude.ui.graph_window import NODE_RADIUS, START_RADIUS

        assert START_RADIUS > NODE_RADIUS

    def test_描いても落ちない(self, linked, qtbot) -> None:
        """`paintEvent` を実際に通す（中抜きの点・線・題名の全部を描く）。"""
        from PySide6.QtGui import QColor, QImage

        dialog = linked.build_graph_window()
        try:
            dialog.resize(600, 400)
            image = QImage(600, 400, QImage.Format.Format_RGB32)
            image.fill(QColor("white"))
            dialog.view.render(image)
            assert image.width() == 600
        finally:
            dialog.close()


class TestShortcut:
    """**`Cmd+Shift+X` の轍を踏まない。** キーは押して確かめる（M-1 の教訓）。"""

    def test_キーで開ける(self, linked, qtbot, activate) -> None:
        """**開いたところまで見る。** 窓は `exec()` で開くので、そのまま
        押すと入れ子の待ち行列に入って戻ってこない（実測で試験が止まった）。
        開いたら閉じるタイマを先に仕掛けておく。
        """
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        from hitofude.ui.graph_window import GraphWindow

        activate(linked)
        seen: list[str] = []

        def close_it() -> None:
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, GraphWindow) and widget.isVisible():
                    seen.append(widget.graph().nodes[0].title)
                    widget.reject()

        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(close_it)
        timer.start()
        try:
            qtbot.keyClick(
                linked.editor,
                Qt.Key.Key_R,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            )
        finally:
            timer.stop()
        assert seen == ["会議メモ"]


class TestDropped:
    def test_落としたら件数を出す(self, linked) -> None:
        """**黙って減らさない。** 減ったと分からないと図を信じてしまう。"""
        dialog = linked.build_graph_window()
        try:
            dialog.set_limit(2)
            assert "件" in dialog.notice()
        finally:
            dialog.close()

    def test_落としていなければ何も出さない(self, linked) -> None:
        dialog = linked.build_graph_window()
        try:
            assert dialog.notice() == ""
        finally:
            dialog.close()


class TestClose:
    def test_閉じるボタンがある(self, linked) -> None:
        """**記号だけでは気づかれない**（`Cmd+Shift+F` で 2 回報告があった）。"""
        dialog = linked.build_graph_window()
        try:
            assert dialog.close_button.text() == "閉じる"
        finally:
            dialog.close()

    def test_Esc_でも閉じる(self, linked, qtbot) -> None:
        dialog = linked.build_graph_window()
        dialog.show()
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible()
