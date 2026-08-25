"""ノートをローカルLLM に読ませる（L-1 / ADR-0025）の配線。

**モデルは動かさない。** `LocalLLM` の口を差し替えて、頼む → 届く →
出る、の流れだけを見る。

ここで固定したいのは 4 つ。**渡すのは今開いているノートの本文だけ**、
**本文は書き換えない**（R1）、**Ollama が無ければ押せない**、
**生成は打鍵の経路に入れない**（別スレッド。§6.6）。
"""

import pytest

from hitofude.core.document import Note
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


class TestRelatedFlow:
    """関連ノート（L-3）。**索引から出す**ので LLM は動かさない。"""

    def seeded(self, window: MainWindow):
        for relative, text in (
            ("今.md", "# 今\n\n#仕事 の話。[[会議メモ]] を見る。\n"),
            ("仕事/会議メモ.md", "# 会議メモ\n\n#仕事 の会議。\n"),
            ("私用/買い物.md", "# 買い物\n\n#私用 のメモ。\n"),
            ("指す.md", "# 指す\n\n[[今]] を指している。\n"),
        ):
            path = window.vault.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            window.vault_index.upsert_note(Note.read(path), window.vault.root)
        window.refresh()
        window.open_and_select(window.vault.root / "今.md")

    def titles(self, window: MainWindow) -> list[str]:
        return [label.split(" — ")[0] for label in window.assistant_pane.related_labels()]

    def test_同じタグと指し合うノートが出る(self, window) -> None:
        self.seeded(window)
        window.show_related()
        assert set(self.titles(window)) == {"会議メモ", "指す"}

    def test_自分は出ない(self, window) -> None:
        self.seeded(window)
        window.show_related()
        assert "今" not in self.titles(window)

    def test_関係の無いノートは出ない(self, window) -> None:
        self.seeded(window)
        window.show_related()
        assert "買い物" not in self.titles(window)

    def test_理由が付く(self, window) -> None:
        self.seeded(window)
        window.show_related()
        labels = {label.split(" — ")[0]: label for label in window.assistant_pane.related_labels()}
        assert "タグ" in labels["会議メモ"]

    def test_押すとそのノートが開く(self, window) -> None:
        self.seeded(window)
        window.show_related()
        window.assistant_pane.activate_related(0)
        assert window.current_note.title in {"会議メモ", "指す"}

    def test_LLMを動かさない(self, window) -> None:
        """**待たせない。** 索引を引くだけで、モデルには触らない。"""
        llm = FakeLLM()
        window.set_llm(llm)
        self.seeded(window)
        window.show_related()
        assert llm.prompts == []

    def test_開いていなければ何もしない(self, window) -> None:
        window.show_related()
        assert window.assistant_pane.related_labels() == []


class TestQuestionFlow:
    """vault 全体への質問（L-2）。

    **材料はこちらが選ぶ。** 索引で候補を引き、その本文を渡し、
    **実際に渡したノートを出典として並べる**（モデルに題名を作文させない）。
    """

    def seeded(self, window: MainWindow):
        for relative, text in (
            ("会議メモ.md", "# 会議メモ\n\n来週の予算について話した。増額の要望が出ている。\n"),
            ("買い物.md", "# 買い物\n\n牛乳とパンを買う。\n"),
            ("予算資料.md", "# 予算資料\n\n予算の前年比をまとめた。\n"),
        ):
            path = window.vault.root / relative
            path.write_text(text, encoding="utf-8")
            window.vault_index.upsert_note(Note.read(path), window.vault.root)
        window.refresh()

    def sources(self, window: MainWindow) -> set[str]:
        return set(window.assistant_pane.related_labels())

    def test_答えが出る(self, window) -> None:
        window.set_llm(FakeLLM(["予算の話は", "会議メモにあります"]))
        self.seeded(window)
        window.ask_question("予算")
        self.wait(window)
        assert window.assistant_pane.text() == "予算の話は会議メモにあります"

    def wait(self, window: MainWindow) -> None:
        from PySide6.QtWidgets import QApplication

        for _ in range(200):
            if not window.assistant_pane.is_running():
                return
            QApplication.processEvents()

    def test_当たったノートの本文を渡す(self, window) -> None:
        llm = FakeLLM()
        window.set_llm(llm)
        self.seeded(window)
        window.ask_question("予算")
        self.wait(window)
        assert "来週の予算について話した。" in llm.prompts[0]

    def test_関係の無いノートは渡さない(self, window) -> None:
        """**渡すほど当たるわけではない。** 文脈からあふれると黙って切れる。"""
        llm = FakeLLM()
        window.set_llm(llm)
        self.seeded(window)
        window.ask_question("予算")
        self.wait(window)
        assert "牛乳とパン" not in llm.prompts[0]

    def test_出典が並ぶ(self, window) -> None:
        window.set_llm(FakeLLM())
        self.seeded(window)
        window.ask_question("予算")
        self.wait(window)
        assert self.sources(window) == {"会議メモ", "予算資料"}

    def test_出典は答えの前に出る(self, window) -> None:
        """**何を見て答えるのかが先に分かる。** 待っている間の手がかりになる。"""
        window.set_llm(FakeLLM())
        self.seeded(window)
        window.ask_question("予算")
        assert self.sources(window)  # まだ答えは来ていない

    def test_当たらなければ読ませない(self, window) -> None:
        """**材料が無いのに GPU を回さない。** 作り話をさせないためでもある。"""
        llm = FakeLLM()
        window.set_llm(llm)
        self.seeded(window)
        window.ask_question("宇宙旅行")
        self.wait(window)
        assert llm.prompts == []
        assert "見つかりませんでした" in window.assistant_pane.status_text()

    def test_タグで絞れる(self, window) -> None:
        """`#タグ` の書き方は検索と同じ（`core/searchquery`）。"""
        path = window.vault.root / "仕事メモ.md"
        path.write_text("# 仕事メモ\n\n予算の件。 #仕事\n", encoding="utf-8")
        window.vault_index.upsert_note(Note.read(path), window.vault.root)
        window.refresh()
        self.seeded(window)
        window.set_llm(FakeLLM())
        window.ask_question("#仕事 予算")
        self.wait(window)
        assert self.sources(window) == {"仕事メモ"}

    def test_自然文の質問でも当たる(self, window) -> None:
        """**質問は検索語ではない。** そのまま探すと 0 件だった（実測）。
        語を取り出して 1 つずつ探す（`core/keywords`）。"""
        window.set_llm(FakeLLM())
        self.seeded(window)
        window.ask_question("予算について何が決まった？")
        self.wait(window)
        assert self.sources(window) == {"会議メモ", "予算資料"}

    def test_複数の語は両方から集める(self, window) -> None:
        window.set_llm(FakeLLM())
        self.seeded(window)
        window.ask_question("予算と買い物の話")
        self.wait(window)
        assert self.sources(window) >= {"会議メモ", "買い物"}

    def test_出典を押すと開く(self, window) -> None:
        window.set_llm(FakeLLM())
        self.seeded(window)
        window.ask_question("予算")
        self.wait(window)
        window.assistant_pane.activate_related(0)
        assert window.current_note.title in {"会議メモ", "予算資料"}


class TestSettings:
    """設定からモデル・ポート・渡す量を決める（ADR-0025 追記）。"""

    def test_設定のモデルを使う(self, window, config) -> None:
        config.llm_model = "qwen3:8b"
        window.reload_llm()
        assert window.llm.model == "qwen3:8b"

    def test_設定のポートを使う(self, window, config) -> None:
        config.llm_port = 11500
        window.reload_llm()
        assert window.llm.port == 11500

    def test_設定の渡す量を使う(self, window, config) -> None:
        config.llm_context = 16384
        window.reload_llm()
        assert window.llm.context == 16384

    def test_設定を変えたら作り直す(self, window, config) -> None:
        """**設定画面で変えたのに古い相手のまま**にしない。"""
        config.llm_model = "qwen3:8b"
        window._apply_preferences()
        assert window.llm.model == "qwen3:8b"

    def test_送り先は127001のまま(self, window, config) -> None:
        """ポートを変えても**相手の機械は変わらない**（ADR-0025 の 3）。"""
        from hitofude.core.llm import endpoint

        config.llm_port = 11500
        window.reload_llm()
        assert endpoint(window.llm.port) == "http://127.0.0.1:11500"


class SlowLLM:
    """`generate` の途中で止まる相手。**後から続きを流せる。**"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def available(self) -> bool:
        return True

    def generate(self, prompt, *, on_chunk=None, should_stop=None) -> str:
        self.calls.append((prompt, on_chunk, should_stop))
        return ""

    def resume(self, index: int, chunk: str) -> bool:
        """その回の続きを 1 つ流す。**止められていれば流さない**（本物と同じ）。"""
        _prompt, on_chunk, should_stop = self.calls[index]
        if should_stop is not None and should_stop():
            return False
        if on_chunk is not None:
            on_chunk(chunk)
        return True


class TestGenerationLifecycle:
    """走っている生成の後始末（コードレビュー指摘）。

    **前の答えが新しい答えに混ざらない。** 止めてから頼み直したとき、
    前の回がまだ喋っていると、2 つの答えが交ざって出る。
    """

    def prepared(self, window: MainWindow, llm) -> None:
        window.set_llm(llm)
        opened(window)

    def ask(self, window: MainWindow, llm, task: Task) -> None:
        """頼んで、**ワーカーが受け取るまで待つ**（別スレッドで走る）。"""
        from PySide6.QtWidgets import QApplication

        before = len(llm.calls)
        window.ask_assistant(task)
        for _ in range(200):
            if len(llm.calls) > before:
                return
            QApplication.processEvents()
        raise AssertionError("ワーカーが動かなかった")

    def test_止めた回は再開しない(self, window) -> None:
        llm = SlowLLM()
        self.prepared(window, llm)
        self.ask(window, llm, Task.SUMMARY)
        window.stop_assistant()
        assert llm.resume(0, "止めたのに続き") is False

    def test_頼み直すと前の回は止まる(self, window) -> None:
        """**同じ旗を使い回さない。** 新しい回が旗を下ろすと、前の回が
        「まだ走ってよい」と誤解して喋り出す（実際にそうなっていた）。"""
        llm = SlowLLM()
        self.prepared(window, llm)
        self.ask(window, llm, Task.SUMMARY)
        window.stop_assistant()
        self.ask(window, llm, Task.REVIEW)
        assert llm.resume(0, "前の回の続き") is False

    def test_前の回の言葉は出さない(self, window) -> None:
        llm = SlowLLM()
        self.prepared(window, llm)
        self.ask(window, llm, Task.SUMMARY)
        window.stop_assistant()
        self.ask(window, llm, Task.REVIEW)
        llm.resume(0, "古い答え")
        assert "古い答え" not in window.assistant_pane.text()

    def test_閉じるときに止める(self, window) -> None:
        """**閉じるのを待たせない。** 生成は最長 120 秒かかる。"""
        llm = SlowLLM()
        self.prepared(window, llm)
        self.ask(window, llm, Task.SUMMARY)
        window.close()
        assert llm.resume(0, "閉じたあとの続き") is False


class TestReporterLifetime:
    """**知らせ役に親を付けない**（回帰）。

    ウィンドウの子にすると、ワーカーが返す前に窓ごと壊れて
    "Signal source has been deleted" で落ちる。索引の SyncReporter は
    最初からそうしてあり（main_window の注記）、あとから足した
    アシスタント側だけ親付きだった。
    """

    def test_親を付けない(self, window) -> None:
        from hitofude.ui.index_sync import AssistantReporter

        made: list[AssistantReporter] = []
        original = AssistantReporter

        class Spy(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                made.append(self)

        # 生成の入口は assistant_actions に切り出された（2026-08-25）。
        # 差し替え先も名前解決が起きるモジュールに合わせる
        import hitofude.ui.assistant_actions as module

        module.AssistantReporter = Spy
        try:
            window.set_llm(FakeLLM())
            opened(window)
            run_assistant(window, Task.SUMMARY)
        finally:
            module.AssistantReporter = original

        assert made, "知らせ役が作られていない"
        assert made[0].parent() is None
        assert window._sync_reporter.parent() is None  # 索引側も同じ作法


class TestFailureMessages:
    """**何が起きたかで案内を変える**（ユーザー報告 2026-08-24）。

    大きいモデルは読み込みだけで数分かかる（実測: gemma4:26b で 391.9 秒）。
    待ちきれずに切ったのを「動いているか確かめてください」と出すと、
    動いているのに動いていないと言われて原因に辿り着けない。
    """

    class Failing:
        """決めた例外を投げる LLM。"""

        model = "gemma4:26b"

        def __init__(self, error: Exception) -> None:
            self._error = error

        def available(self) -> bool:
            return True

        def models(self) -> list[str]:
            return [self.model]

        def is_loaded(self) -> bool:
            return False

        def generate(self, prompt, *, on_chunk=None, should_stop=None):
            raise self._error

    def failed_text(self, window, error: Exception) -> str:
        window.set_llm(self.Failing(error))
        opened(window)
        run_assistant(window, Task.SUMMARY)
        return window.assistant_pane.status_text()

    def test_時間切れは待ち時間の話だと分かる(self, window) -> None:
        from hitofude.core.llm import TimedOut

        found = self.failed_text(window, TimedOut("timed out"))
        assert "時間" in found
        assert "繋がりません" not in found, "時間切れを「繋がらない」と案内している"

    def test_時間切れは設定の場所を教える(self, window) -> None:
        from hitofude.core.llm import TimedOut

        found = self.failed_text(window, TimedOut("timed out"))
        assert "設定" in found

    def test_繋がらないときは今まで通り(self, window) -> None:
        from hitofude.core.llm import NotRunning

        found = self.failed_text(window, NotRunning("Connection refused"))
        assert "繋がりません" in found


class TestLoadingNotice:
    """読み込み中は**そう言う**（6 分の沈黙を「壊れている」に見せない）。"""

    class Cold(FakeLLM):
        model = "gemma4:26b"

        def is_loaded(self) -> bool:
            return False

    class Warm(FakeLLM):
        model = "gemma3:12b"

        def is_loaded(self) -> bool:
            return True

    def test_載っていなければ読み込み中と出す(self, window) -> None:
        window.set_llm(self.Cold())
        opened(window)
        window.ask_assistant(Task.SUMMARY)
        assert "読み込" in window.assistant_pane.status_text()

    def test_載っていれば余計なことを言わない(self, window) -> None:
        window.set_llm(self.Warm())
        opened(window)
        window.ask_assistant(Task.SUMMARY)
        assert "読み込" not in window.assistant_pane.status_text()


class UnloadableLLM(FakeLLM):
    """降ろした回数を覚える。"""

    def __init__(self, loaded: bool = True) -> None:
        super().__init__()
        self.loaded = loaded
        self.unloads = 0

    def is_loaded(self) -> bool:
        return self.loaded

    def unload(self) -> bool:
        self.unloads += 1
        was = self.loaded
        self.loaded = False
        return was


class TestUnload:
    """モデルをメモリから降ろす（ユーザー報告 2026-08-24）。

    答えたあともモデルは載ったままで、12b でも `llama-server` が 8.0GB を
    抱える（実測）。**降ろす道を 3 つ用意する**——メニュー、アシスタントを
    閉じたとき、アプリを終了するとき。
    """

    def test_メニューから降ろせる(self, window) -> None:
        found = UnloadableLLM()
        window.set_llm(found)
        assert window.unload_model() is True
        assert found.unloads == 1

    def test_降ろしたことを知らせる(self, window) -> None:
        window.set_llm(UnloadableLLM())
        window.unload_model()
        assert "降ろしました" in window.notice()

    def test_載っていなければ何もしない(self, window) -> None:
        """**押しても無駄打ちにならない。** 何が起きたか言う。"""
        found = UnloadableLLM(loaded=False)
        window.set_llm(found)
        assert window.unload_model() is False
        assert found.unloads == 0
        assert window.notice()

    def test_答えを待っている間は降ろさない(self, window) -> None:
        found = UnloadableLLM()
        window.set_llm(found)
        opened(window)
        window.assistant_pane.begin()  # 走っている状態にする
        assert window.unload_model() is False
        assert found.unloads == 0

    def test_アシスタントを閉じたら降ろす(self, window) -> None:
        found = UnloadableLLM()
        window.set_llm(found)
        window.show_assistant(True)
        window.show_assistant(False)
        assert found.unloads == 1

    def test_閉じたままなら降ろしに行かない(self, window) -> None:
        """起動時の復元（隠したまま）で通信させない。"""
        found = UnloadableLLM()
        window.set_llm(found)
        window.show_assistant(False)
        window.show_assistant(False)
        assert found.unloads == 0

    def test_終了するときに降ろす(self, window) -> None:
        found = UnloadableLLM()
        window.set_llm(found)
        window.close()
        assert found.unloads == 1

    def test_メニューに項目がある(self, window) -> None:
        assert "モデルを降ろす" in window.menu_actions
