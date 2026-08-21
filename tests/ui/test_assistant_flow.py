"""ノートを手元の LLM に読ませる（L-1 / ADR-0025）の配線。

**モデルは動かさない。** `LocalLLM` の口を差し替えて、頼む → 届く →
出る、の流れだけを見る。

ここで固定したいのは 4 つ。**渡すのは今開いているノートの本文だけ**、
**本文は書き換えない**（R1）、**Ollama が無ければ押せない**、
**生成は打鍵の経路に入れない**（別スレッド。§6.6）。
"""

import pytest

from hitofude.core.llm import Task
from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


class FakeLLM:
    """頼まれた中身を覚えて、決めた答えを返す。"""

    def __init__(self, chunks: list[str] | None = None, running: bool = True) -> None:
        self.chunks = chunks if chunks is not None else ["答え"]
        self.running = running
        self.prompts: list[str] = []

    def available(self) -> bool:
        return self.running

    def generate(self, prompt, *, on_chunk=None, should_stop=None) -> str:
        self.prompts.append(prompt)
        for chunk in self.chunks:
            if on_chunk is not None:
                on_chunk(chunk)
        return "".join(self.chunks)


def opened(window: MainWindow, title: str = "会議", body: str = "来週の予算について話した。"):
    note = window.vault.create(title, f"# {title}\n\n{body}\n")
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    window.open_and_select(note.path)
    return note


def run_assistant(window: MainWindow, task: Task = Task.SUMMARY) -> None:
    """頼んで、終わるまで待つ（背景スレッドを使う）。"""
    window.ask_assistant(task)
    deadline = 0
    while window.assistant_pane.is_running() and deadline < 200:
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        deadline += 1


class TestAsking:
    def test_答えがペインに出る(self, window) -> None:
        window.set_llm(FakeLLM(["会議の", "要約"]))
        opened(window)
        run_assistant(window)
        assert window.assistant_pane.text() == "会議の要約"

    def test_渡すのは今のノートの本文(self, window) -> None:
        llm = FakeLLM()
        window.set_llm(llm)
        opened(window, body="来週の予算について話した。")
        run_assistant(window)
        assert "来週の予算について話した。" in llm.prompts[0]

    def test_front_matterは渡さない(self, window) -> None:
        """**書く人に見えていないものを渡さない。**"""
        llm = FakeLLM()
        window.set_llm(llm)
        note = opened(window)
        run_assistant(window)
        assert note.id not in llm.prompts[0]

    def test_本文は書き換えない(self, window) -> None:
        """R1。答えはペインにしか出ない。"""
        window.set_llm(FakeLLM(["勝手に書かれたら困る"]))
        opened(window)
        before = window.editor.toPlainText()
        run_assistant(window)
        assert window.editor.toPlainText() == before

    def test_開いていなければ何もしない(self, window) -> None:
        llm = FakeLLM()
        window.set_llm(llm)
        window.ask_assistant(Task.SUMMARY)
        assert llm.prompts == []

    def test_レビューは指示が違う(self, window) -> None:
        llm = FakeLLM()
        window.set_llm(llm)
        opened(window)
        run_assistant(window, Task.SUMMARY)
        run_assistant(window, Task.REVIEW)
        assert llm.prompts[0] != llm.prompts[1]


class TestAvailability:
    def test_動いていなければ押せない(self, window) -> None:
        """**押してから断らない**（G-3 と同じ作法）。"""
        window.set_llm(FakeLLM(running=False))
        window.show_assistant(True)
        assert window.assistant_pane.summary_button.isEnabled() is False

    def test_動いていれば押せる(self, window) -> None:
        window.set_llm(FakeLLM())
        window.show_assistant(True)
        assert window.assistant_pane.summary_button.isEnabled() is True


class TestPane:
    def test_既定では出さない(self, window) -> None:
        """**画面を勝手に狭くしない**（アウトラインと同じ）。"""
        assert window.assistant_pane.isHidden()

    def test_開閉できる(self, window) -> None:
        window.toggle_assistant()
        assert not window.assistant_pane.isHidden()
        window.toggle_assistant()
        assert window.assistant_pane.isHidden()

    def test_出したことを覚える(self, window, config) -> None:
        window.toggle_assistant()
        assert config.assistant_visible is True

    def test_テーマに追従する(self, window) -> None:
        from hitofude.theme import DARK

        window._on_theme_changed(DARK)
        assert window.assistant_pane._theme.is_dark
