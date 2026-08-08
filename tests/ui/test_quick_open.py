"""クイックオープンと全文検索のテスト（タスク 5-5, 5-6 / spec §5.4）。"""

from pathlib import Path

import pytest

from hitofude.ui.quick_open import (
    Palette,
    PaletteItem,
    _to_html,
    fuzzy_filter,
    fuzzy_score,
)

pytestmark = pytest.mark.gui


def item(title: str, subtitle: str = "") -> PaletteItem:
    return PaletteItem(title=title, subtitle=subtitle, path=Path(f"{title}.md"))


class TestFuzzyScore:
    def test_部分列なら一致する(self) -> None:
        assert fuzzy_score("会議", "会議メモ") is not None
        assert fuzzy_score("会モ", "会議メモ") is not None  # 飛び飛びでもよい

    def test_部分列でなければNone(self) -> None:
        assert fuzzy_score("存在しない", "会議メモ") is None

    def test_空のクエリは全部通る(self) -> None:
        assert fuzzy_score("", "何でも") == 0

    def test_大文字小文字を区別しない(self) -> None:
        assert fuzzy_score("qt", "QT のドキュメント") is not None

    def test_連続一致のほうが高い(self) -> None:
        contiguous = fuzzy_score("会議", "会議メモ")
        scattered = fuzzy_score("会モ", "会議メモ")
        assert contiguous > scattered

    def test_先頭一致のほうが高い(self) -> None:
        assert fuzzy_score("会議", "会議メモ") > fuzzy_score("会議", "今日の会議メモ")

    def test_区切りの直後は優遇される(self) -> None:
        after_boundary = fuzzy_score("メモ", "会議 メモ")
        inside = fuzzy_score("メモ", "会議xメモ")
        assert after_boundary > inside

    def test_短いほうが高い(self) -> None:
        assert fuzzy_score("会議", "会議") >= fuzzy_score("会議", "会議" + "あ" * 100)


class TestFuzzyFilter:
    def test_一致するものだけ残る(self) -> None:
        items = [item("会議メモ"), item("読書メモ"), item("買い物")]
        assert [i.title for i in fuzzy_filter("メモ", items)] == ["会議メモ", "読書メモ"]

    def test_良い一致が先に来る(self) -> None:
        items = [item("今日の会議のメモ"), item("会議メモ")]
        assert fuzzy_filter("会議メモ", items)[0].title == "会議メモ"

    def test_空のクエリは全部返す(self) -> None:
        items = [item("A"), item("B")]
        assert len(fuzzy_filter("", items)) == 2

    def test_同点なら元の並びを保つ(self) -> None:
        """索引は更新順に返すので、その並びが意味を持つ。"""
        items = [item("メモA"), item("メモB")]
        assert [i.title for i in fuzzy_filter("メモ", items)] == ["メモA", "メモB"]

    def test_件数を制限できる(self) -> None:
        items = [item(f"メモ{i}") for i in range(100)]
        assert len(fuzzy_filter("メモ", items, limit=10)) == 10


class TestSnippetHtml:
    def test_印を太字にする(self) -> None:
        from hitofude.storage.index_db import HIGHLIGHT_END, HIGHLIGHT_START

        got = _to_html(f"来期の{HIGHLIGHT_START}予算{HIGHLIGHT_END}について")
        assert got == "来期の<b>予算</b>について"

    def test_本文のHTMLはエスケープする(self) -> None:
        """書いた内容で表示が壊れないこと。"""
        assert _to_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_エスケープしてから印を置き換える(self) -> None:
        from hitofude.storage.index_db import HIGHLIGHT_END, HIGHLIGHT_START

        got = _to_html(f"{HIGHLIGHT_START}<b>{HIGHLIGHT_END}")
        assert got == "<b>&lt;b&gt;</b>"


class TestPalette:
    @pytest.fixture
    def palette(self, qtbot) -> Palette:
        widget = Palette(placeholder="テスト")
        qtbot.addWidget(widget)
        return widget

    def test_候補が無ければ空(self, palette) -> None:
        palette.open_with()
        assert palette.items == []

    def test_providerの結果を並べる(self, palette) -> None:
        palette.set_provider(lambda q: [item("会議メモ"), item("読書メモ")])
        palette.open_with()
        assert [i.title for i in palette.items] == ["会議メモ", "読書メモ"]

    def test_入力するとproviderが呼ばれる(self, palette) -> None:
        seen: list[str] = []

        def provider(query: str):
            seen.append(query)
            return []

        palette.set_provider(provider)
        palette.open_with()
        palette._input.setText("会議")
        assert "会議" in seen

    def test_最初の候補が選ばれている(self, palette) -> None:
        palette.set_provider(lambda q: [item("A"), item("B")])
        palette.open_with()
        assert palette.current_item().title == "A"

    def test_下キーで次の候補へ(self, palette) -> None:
        palette.set_provider(lambda q: [item("A"), item("B")])
        palette.open_with()
        palette.move_selection(1)
        assert palette.current_item().title == "B"

    def test_末尾から下キーで先頭へ戻る(self, palette) -> None:
        palette.set_provider(lambda q: [item("A"), item("B")])
        palette.open_with()
        palette.move_selection(1)
        palette.move_selection(1)
        assert palette.current_item().title == "A"

    def test_候補が無いときに移動しても落ちない(self, palette) -> None:
        palette.open_with()
        palette.move_selection(1)

    def test_決定するとパスが飛ぶ(self, palette, qtbot) -> None:
        palette.set_provider(lambda q: [item("会議メモ")])
        palette.open_with()
        with qtbot.waitSignal(palette.chosen, timeout=1000) as blocker:
            palette._accept_item()
        assert Path(blocker.args[0]).name == "会議メモ.md"

    def test_決定すると閉じる(self, palette) -> None:
        palette.set_provider(lambda q: [item("会議メモ")])
        palette.open_with()
        palette._accept_item()
        assert palette.isVisible() is False

    def test_描画しても落ちない(self, palette) -> None:
        from PySide6.QtGui import QColor, QImage

        palette.set_provider(lambda q: [item("会議メモ", "来期の予算について")])
        palette.open_with()
        palette.resize(560, 380)
        image = QImage(palette.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        palette.render(image)
