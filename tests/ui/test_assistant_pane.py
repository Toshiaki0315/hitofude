"""手元の LLM の答えを出すペイン（L-1 / ADR-0025）。

**ここはモデルを知らない。** 頼まれたことを合図で伝え、届いた文字を出す
だけ（`outline_pane` が vault を知らないのと同じ分担）。

見せ方の約束は 3 つ。**押してから断らない**（Ollama が無ければ押せない）、
**黙って待たせない**（届いたぶんから出す）、**本文は書き換えない**（R1。
出るのはここだけで、入れるのは押されたときだけ）。
"""

import pytest

from hitofude.core.llm import Task
from hitofude.ui.assistant_pane import AssistantPane

pytestmark = pytest.mark.gui


@pytest.fixture
def pane(qtbot) -> AssistantPane:
    widget = AssistantPane()
    qtbot.addWidget(widget)
    return widget


class TestAsking:
    def test_要約を頼める(self, pane, qtbot) -> None:
        with qtbot.waitSignal(pane.requested, timeout=1000) as blocker:
            pane.summary_button.click()
        assert blocker.args[0] == Task.SUMMARY

    def test_レビューを頼める(self, pane, qtbot) -> None:
        with qtbot.waitSignal(pane.requested, timeout=1000) as blocker:
            pane.review_button.click()
        assert blocker.args[0] == Task.REVIEW

    def test_走っている間は頼めない(self, pane) -> None:
        """**二重に走らせない。** GPU が 2 つぶん回り、答えも混ざる。"""
        pane.begin()
        assert pane.summary_button.isEnabled() is False
        assert pane.review_button.isEnabled() is False

    def test_終われば頼める(self, pane) -> None:
        pane.begin()
        pane.finish()
        assert pane.summary_button.isEnabled() is True


class TestStreaming:
    def test_届いたぶんから出る(self, pane) -> None:
        """最初の 1 文字まで実測 5.4 秒。書き終わりを待つと固まって見える。"""
        pane.begin()
        pane.append("会議の")
        pane.append("要約")
        assert pane.text() == "会議の要約"

    def test_頼み直すと前の答えは消える(self, pane) -> None:
        pane.begin()
        pane.append("古い答え")
        pane.begin()
        assert pane.text() == ""

    def test_待っている間はそう見える(self, pane) -> None:
        pane.begin()
        assert pane.status_text()
        pane.append("答え")
        assert pane.status_text() == ""

    def test_答えも横に流さない(self, pane) -> None:
        """折り返して読む。横棒が出ると 2 方向へ動かすことになる。"""
        from PySide6.QtCore import Qt

        assert pane.output.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    def test_読むだけ(self, pane) -> None:
        """**ここで直せない。** 直すなら本文で直す（履歴のダイアログと同じ）。"""
        assert pane.is_read_only() is True


class TestStopping:
    def test_走っている間は止められる(self, pane) -> None:
        pane.begin()
        assert pane.stop_button.isEnabled() is True

    def test_止まっていれば押せない(self, pane) -> None:
        assert pane.stop_button.isEnabled() is False

    def test_止めると知らせる(self, pane, qtbot) -> None:
        pane.begin()
        with qtbot.waitSignal(pane.stopped, timeout=1000):
            pane.stop_button.click()


class TestUnavailable:
    """Ollama が無いときは**押せない**（G-3 と同じ作法）。"""

    def test_使えなければ押せない(self, pane) -> None:
        pane.set_available(False)
        assert pane.summary_button.isEnabled() is False
        assert pane.review_button.isEnabled() is False

    def test_入れ方を案内する(self, pane) -> None:
        pane.set_available(False)
        assert "Ollama" in pane.status_text()

    def test_使えるようになれば押せる(self, pane) -> None:
        pane.set_available(False)
        pane.set_available(True)
        assert pane.summary_button.isEnabled() is True


class TestFailure:
    def test_失敗を伝える(self, pane) -> None:
        """**黙って何も出さない**のがいちばん分かりにくい。"""
        pane.begin()
        pane.fail("繋がりませんでした")
        assert "繋がりませんでした" in pane.status_text()

    def test_失敗しても次を頼める(self, pane) -> None:
        pane.begin()
        pane.fail("繋がりませんでした")
        assert pane.summary_button.isEnabled() is True


class TestRelated:
    """関連ノートは**モデルを通さない**（L-3）。

    根拠は索引の中にある（同じタグ・`[[…]]`・題名の語）ので、Ollama が
    無くても出る。**理由も一緒に出す**（出た理由が読めないと確かめようがない）。
    """

    def test_関連を頼める(self, pane, qtbot) -> None:
        with qtbot.waitSignal(pane.related_requested, timeout=1000):
            pane.related_button.click()

    def test_Ollamaが無くても押せる(self, pane) -> None:
        """索引を引くだけなので、モデルの有無に関係ない。"""
        pane.set_available(False)
        assert pane.related_button.isEnabled() is True

    def test_題名と理由が並ぶ(self, pane) -> None:
        from pathlib import Path

        pane.set_related([(Path("仕事/会議.md"), "会議", ("同じタグ #仕事",))])
        assert pane.related_labels() == ["会議 — 同じタグ #仕事"]

    def test_理由が複数なら繋ぐ(self, pane) -> None:
        from pathlib import Path

        pane.set_related([(Path("会議.md"), "会議", ("同じタグ #仕事", "このノートを指している"))])
        assert pane.related_labels() == ["会議 — 同じタグ #仕事 / このノートを指している"]

    def test_押すと知らせる(self, pane, qtbot) -> None:
        from pathlib import Path

        pane.set_related([(Path("仕事/会議.md"), "会議", ("同じタグ #仕事",))])
        with qtbot.waitSignal(pane.note_activated, timeout=1000) as blocker:
            pane.activate_related(0)
        assert blocker.args[0] == Path("仕事/会議.md")

    def test_狭くても全文が読める(self, pane) -> None:
        """**理由は長い。** 欄が狭いと切れるので、触れば全部読めるようにする。"""
        from pathlib import Path

        pane.set_related([(Path("会議.md"), "会議", ("同じタグ #仕事", "このノートを指している"))])
        assert pane.related_tooltips() == ["会議 — 同じタグ #仕事 / このノートを指している"]

    def test_横に流れない(self, pane) -> None:
        """横スクロールバーが出ると、読むのに 2 方向へ動かすことになる。"""
        from PySide6.QtCore import Qt

        assert (
            pane.related_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def test_件数に合わせて縮む(self, pane) -> None:
        """**1 件のために欄の半分を使わない**（答えの場所が狭くなる）。"""
        from pathlib import Path

        pane.set_related([(Path("1.md"), "1", ("同じタグ",))])
        one = pane.related_list.maximumHeight()
        pane.set_related([(Path(f"{n}.md"), str(n), ("同じタグ",)) for n in range(5)])
        assert one < pane.related_list.maximumHeight()

    def test_多すぎれば頭打ち(self, pane) -> None:
        """**並べるのは手がかり。** 欄いっぱいに伸びると答えが見えない。"""
        from pathlib import Path

        pane.set_related([(Path(f"{n}.md"), str(n), ("同じタグ",)) for n in range(6)])
        few = pane.related_list.maximumHeight()
        pane.set_related([(Path(f"{n}.md"), str(n), ("同じタグ",)) for n in range(30)])
        assert pane.related_list.maximumHeight() == few

    def test_無ければそう出す(self, pane) -> None:
        """**空欄で黙らない。** 探した結果 0 件なのか、押し忘れたのか分かる。"""
        pane.set_related([])
        assert "ありません" in pane.status_text()

    def test_頼み直すと消える(self, pane) -> None:
        from pathlib import Path

        pane.set_related([(Path("会議.md"), "会議", ("同じタグ #仕事",))])
        pane.begin()
        assert pane.related_labels() == []


class TestQuestion:
    """vault 全体への質問（L-2）。**出典はこちらが出す。**"""

    def test_質問を送れる(self, pane, qtbot) -> None:
        pane.question_box.setText("予算はどうなった？")
        with qtbot.waitSignal(pane.question_asked, timeout=1000) as blocker:
            pane.ask_button.click()
        assert blocker.args[0] == "予算はどうなった？"

    def test_Enterでも送れる(self, pane, qtbot) -> None:
        """**打って Enter** が自然（検索欄と同じ）。"""
        pane.question_box.setText("予算は？")
        with qtbot.waitSignal(pane.question_asked, timeout=1000):
            pane.question_box.returnPressed.emit()

    def test_空なら送らない(self, pane) -> None:
        """**空の質問で GPU を回さない。**"""
        seen: list[str] = []
        pane.question_asked.connect(seen.append)
        pane.question_box.setText("   ")
        pane.ask_button.click()
        assert seen == []

    def test_Ollamaが無ければ送れない(self, pane) -> None:
        pane.set_available(False)
        assert pane.ask_button.isEnabled() is False

    def test_出典が並ぶ(self, pane) -> None:
        from pathlib import Path

        pane.set_sources([(Path("仕事/会議.md"), "会議メモ")])
        assert pane.related_labels() == ["会議メモ"]

    def test_出典も押せば開く(self, pane, qtbot) -> None:
        from pathlib import Path

        pane.set_sources([(Path("仕事/会議.md"), "会議メモ")])
        with qtbot.waitSignal(pane.note_activated, timeout=1000) as blocker:
            pane.activate_related(0)
        assert blocker.args[0] == Path("仕事/会議.md")


class TestSourcesLook:
    """出典がそれと分かるように出す（ユーザー報告 2026-08-22）。

    **題名だけが 2 行並んでも、それが何なのか分からない。** 実機では
    同じ題名のノートが 2 本あり、区別も付かなかった。
    """

    def test_出典だと分かる見出しが出る(self, pane) -> None:
        from pathlib import Path

        pane.set_sources([(Path("会議.md"), "会議メモ")])
        assert "出典" in pane.status_text()

    def test_答えが流れても見出しは残る(self, pane) -> None:
        """**何を見て答えているか**は、読んでいる間ずっと要る。"""
        from pathlib import Path

        pane.set_sources([(Path("会議.md"), "会議メモ")])
        pane.begin(keep_notes=True)
        pane.append("答え")
        assert "出典" in pane.status_text()

    def test_同じ題名なら置き場所で見分ける(self, pane) -> None:
        """**どっちの「使い方」か分からない**（実機で 2 行並んだ）。"""
        from pathlib import Path

        pane.set_sources(
            [
                (Path("使い方.md"), "Hitofude の使い方"),
                (Path("古い/使い方.md"), "Hitofude の使い方"),
            ]
        )
        assert pane.related_labels() == [
            "Hitofude の使い方 — 使い方",
            "Hitofude の使い方 — 古い/使い方",
        ]

    def test_題名が違えば題名だけ(self, pane) -> None:
        """**要らない情報を足さない。** 見分けが付くなら題名で足りる。"""
        from pathlib import Path

        pane.set_sources([(Path("会議.md"), "会議メモ"), (Path("買い物.md"), "買い物")])
        assert pane.related_labels() == ["会議メモ", "買い物"]
