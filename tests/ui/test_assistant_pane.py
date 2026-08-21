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
