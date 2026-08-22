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


@pytest.fixture
def window(window):
    window.show()
    return window


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

    def test_決定すると選んだ項目が飛ぶ(self, palette, qtbot) -> None:
        palette.set_provider(lambda q: [item("会議メモ")])
        palette.open_with()
        with qtbot.waitSignal(palette.chosen, timeout=1000) as blocker:
            palette._accept_item()
        # **項目そのものを渡す。** アウトライン（C-2）は行番号も要るので、
        # パスだけでは足りない
        assert blocker.args[0].path.name == "会議メモ.md"
        assert blocker.args[0].title == "会議メモ"

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


class TestOutline:
    """アウトライン（C-2）。見出しへ飛ぶ。

    ノート横断のクイックオープンと同じ道具（`Palette`）を使う。入口が
    増えても操作を覚え直さずに済む。
    """

    SOURCE = "# 大見出し\n\n本文\n\n## 中見出し\n\n本文\n\n### 小見出し\n"

    def test_見出しが並ぶ(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        assert [item.title for item in window._search._outline_items("")] == [
            "大見出し",
            "中見出し",
            "小見出し",
        ]

    def test_深さが分かる(self, window) -> None:
        """字下げで階層を見せる。"""
        window.editor.setPlainText(self.SOURCE)
        items = window._search._outline_items("")
        assert items[0].subtitle != items[2].subtitle

    def test_絞り込める(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        assert [item.title for item in window._search._outline_items("中")] == ["中見出し"]

    def test_選ぶとその行へ飛ぶ(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        window.jump_to_line(4)
        assert window.editor.textCursor().blockNumber() == 4

    def test_飛んだ先にカーソルが入る(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        window.jump_to_line(4)
        assert window.editor.hasFocus()

    def test_無い行番号でも落ちない(self, window) -> None:
        window.editor.setPlainText(self.SOURCE)
        window.jump_to_line(999)
        assert window.editor.toPlainText() == self.SOURCE

    def test_見出しが無ければ空(self, window) -> None:
        window.editor.setPlainText("ただの段落\n")
        assert window._search._outline_items("") == []

    def test_開ける(self, window, qtbot) -> None:
        window.editor.setPlainText(self.SOURCE)
        window.open_outline()
        assert window.findChild(Palette) is not None


class TestRowPadding:
    """選択の帯が中身に沿うこと（ユーザー報告）。

    テンプレートを選ぶパレットで、**水色が下へはみ出して**見えた。
    実測（幅 544px の一覧）:

        行0（副題が折り返す）: 割当 72px / 中身 46px → 下に 22px の余り
        行1（折り返さない）  : 割当 49px / 中身 41px → 下に  4px

    原因は `sizeHint` が **`option.rect` の幅が空のときに 480px を仮定**
    していたこと。実際の幅（544px）より狭いので副題が余分に折り返し、
    その高さぶんが行に確保されて、帯だけが下に伸びていた。
    """

    @pytest.fixture
    def palette(self, qtbot) -> Palette:
        widget = Palette(placeholder="テスト")
        qtbot.addWidget(widget)
        widget.set_provider(
            lambda q: [
                PaletteItem(
                    title="日報",
                    subtitle="{{date}} の日報。副題が折り返すくらいには長い説明の文字列",
                    path=Path("日報.md"),
                ),
                PaletteItem(title="日次", subtitle="{{date}}", path=Path("日次.md")),
            ]
        )
        widget.open_with()
        return widget

    def _content_height(self, palette, row: int) -> float:
        view = palette._results
        index = view.model().index(row, 0)
        document = view.itemDelegate()._document(index)
        document.setTextWidth(view.visualRect(index).width())
        return document.size().height()

    def test_上下の余白が同じ(self, palette) -> None:
        view = palette._results
        for row in range(view.model().rowCount()):
            index = view.model().index(row, 0)
            allocated = view.visualRect(index).height()
            slack = allocated - self._content_height(palette, row)
            assert slack == pytest.approx(8, abs=1), f"行 {row} の余白が偏っている: {slack}"

    def test_折り返す副題でも高さが合う(self, palette) -> None:
        """**幅を取り違えると、折り返しの数だけ帯が伸びる。**"""
        view = palette._results
        index = view.model().index(0, 0)
        assert view.visualRect(index).height() == pytest.approx(
            self._content_height(palette, 0) + 8, abs=1
        )


class TestSearchJump:
    """全文検索の結果から、その箇所へ飛ぶ（G-1）。

    **今まではノートの先頭が開いていた。** 抜粋を見て選んだのに `Cmd+F` で
    探し直しになる。飛ぶ仕組みは `Cmd+R`（アウトライン）が既に持っていた
    ので、足りなかったのは「どの行か」だけ。
    """

    def note(self, window, title: str, body: str):
        created = window.vault.create(title, f"# {title}\n\n{body}")
        window.vault_index.upsert_note(created, window.vault.root)
        window.refresh()
        return created.path

    def line_of_caret(self, window) -> int:
        return window.editor.textCursor().blockNumber()

    def choose(self, window, query: str):
        window.full_text_search()
        palette = window.findChild(Palette)
        palette.open_with(query)
        item = palette.items[0]
        palette.chosen.emit(item)
        return item

    def test_一致した行へ飛ぶ(self, window) -> None:
        body = "前置きです。\n" * 5 + "ここに予算の話があります。\n"
        self.note(window, "会議メモ", body)
        self.choose(window, "予算")

        text = window.editor.toPlainText().split("\n")
        assert "予算" in text[self.line_of_caret(window)]

    def test_マーカー越しでも飛ぶ(self, window) -> None:
        """索引は `**予算**について` を `予算について` として持っている。"""
        self.note(window, "設計メモ", "前置き。\n\n**予算**について決めた。\n")
        self.choose(window, "予算について")

        text = window.editor.toPlainText().split("\n")
        assert "予算" in text[self.line_of_caret(window)]

    def test_見つからなければ本文の先頭(self, window) -> None:
        """飛べないだけ。**開けないより開くほうがよい。**"""
        from hitofude.core import frontmatter

        self.note(window, "別のメモ", "本文です。\n")
        window.full_text_search()
        palette = window.findChild(Palette)
        palette.open_with("別の")
        palette.chosen.emit(PaletteItem(title="別のメモ", subtitle="", path=Path("別のメモ.md")))
        offset = frontmatter.body_offset(window.editor.toPlainText())
        assert window.editor.textCursor().position() == offset

    def test_クイックオープンは今まで通り先頭(self, window) -> None:
        """`Cmd+O` は場所を探しているのではない。"""
        from hitofude.core import frontmatter

        path = self.note(window, "会議メモ", "本文\n\n予算の話\n")
        window.open_note(path)
        window.quick_open()
        palette = window.findChild(Palette)
        palette.open_with("会議")
        palette.chosen.emit(palette.items[0])

        offset = frontmatter.body_offset(window.editor.toPlainText())
        assert window.editor.textCursor().position() == offset


class TestCloseButton:
    """閉じるボタン（ユーザー要望 2026-08-22）。

    **Esc を知らないと閉じられなかった。** 枠の無い窓なので、OS の閉じる
    ボタンも無い。押して閉じられる場所を用意する。
    """

    def palette(self, qtbot):
        from hitofude.ui.quick_open import Palette

        found = Palette(placeholder="本文を検索…")
        qtbot.addWidget(found)
        found.open_with("")
        return found

    def test_ボタンがある(self, qtbot) -> None:
        found = self.palette(qtbot)
        assert found.close_button.isVisible()

    def test_押すと閉じる(self, qtbot) -> None:
        found = self.palette(qtbot)
        found.close_button.click()
        assert not found.isVisible()

    def test_Escでも閉じる(self, qtbot) -> None:
        """**今まで通り。** 覚えている人の手を止めない。"""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        found = self.palette(qtbot)
        QTest.keyClick(found, Qt.Key.Key_Escape)
        assert not found.isVisible()

    def test_打つ手が止まらない(self, qtbot) -> None:
        """**フォーカスを奪わない。** 押す気が無い人には無いのと同じ。"""
        from PySide6.QtCore import Qt

        found = self.palette(qtbot)
        assert found.close_button.focusPolicy() == Qt.FocusPolicy.NoFocus
        # offscreen では窓が前面にならないので `hasFocus()` は使えない。
        # **窓の中でどこを打っているか**は focusWidget が持つ
        assert found.focusWidget() is found.input_box

    def test_入力欄と同じ行に置く(self, qtbot) -> None:
        """**縦を食わない。** 一覧が狭くなると候補が減る。"""
        found = self.palette(qtbot)
        assert found.close_button.y() < found.results_list.y()
