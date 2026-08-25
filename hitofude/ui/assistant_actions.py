"""ローカルLLM まわりの束（L-1〜L-3 / ADR-0025）。

`MainWindow` から切り出した協調オブジェクトで、**挙動は変えない**
（note_actions / save_controller / history_actions と同じ「友達」の作り）。
読ませる・止める・降ろす・関連を並べる・質問に材料を選ぶ、をここに集める。

**状態は window 側に残す。** `_llm`（読ませる相手）・`_assistant`（ペイン）・
`_assistant_run`（回の番号）はテストと closeEvent が直接見るため、
こちらは振る舞いだけを持つ。
"""

import logging
from pathlib import Path

from PySide6.QtCore import QThreadPool

from hitofude.core import frontmatter, keywords, ocr, related, searchquery
from hitofude.core import llm as llm_module
from hitofude.core.document import note_key
from hitofude.core.wikilink import normalize
from hitofude.storage.index_db import NoteRow
from hitofude.ui.index_sync import AssistantReporter, AssistantTask

logger = logging.getLogger(__name__)


class AssistantActions:
    """ローカルLLM の使い方。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window

    # ------------------------------------------------------------- 相手

    def llm_from_config(self):
        window = self._window
        return llm_module.LocalLLM(
            model=window._config.llm_model,
            port=window._config.llm_port,
            context=window._config.llm_context,
            timeout=window._config.llm_timeout_minutes * 60,
            keep_alive=window._config.llm_keep_alive_minutes,
        )

    def reload_llm(self) -> None:
        """設定を読み直して相手を作り直す。

        **設定画面で変えたのに古い相手のまま**、を防ぐ。作り直しは安く、
        走っている生成は自分の相手を握ったまま終わる。
        """
        window = self._window
        window._llm = self.llm_from_config()
        if not window._assistant.isHidden():
            window._assistant.set_available(window._llm.available())

    def ocr_engine(self):
        """画像を文字にする読み手（ADR-0027）。設定で切り替える。

        **既定は macOS**（速くて正確）。ローカルLLM は大きなモデルを積める
        人向け。どちらも無ければ「使えない」と答える（呼ぶ側が知らせる）。
        """
        window = self._window
        if window._config.ocr_engine is ocr.Engine.LLM:
            return ocr.LlmEngine(client=window._llm)
        return ocr.MacEngine(tool=ocr.tool_path())

    # ------------------------------------------------------------- 開閉

    def show_assistant(self, showing: bool) -> None:
        window = self._window
        was_visible = not window._assistant.isHidden()
        # スプリッタ経由で出し入れする（幅の退避・復元込み。アウトラインと同じ）
        window._splitter.set_pane_visible(window._splitter.indexOf(window._assistant), showing)
        window._config.assistant_visible = showing
        if showing:
            # **押してから断らない。** 開いた時点で動いているか見る
            window._assistant.set_available(window._llm.available())
        elif was_visible:
            # **閉じるのは「もう使わない」の合図**（ユーザー要望 2026-08-24）。
            # 出したままのモデルは 8.0GB を抱える。開いていなかったとき
            # （起動時の復元）は通信しない
            self.release_model()

    def unload_model(self) -> bool:
        """モデルをメモリから降ろす（ユーザー要望 2026-08-24）。降ろせたら True。

        答えたあともモデルは載ったままで、12b でも `llama-server` が
        8.0GB を抱える（実測）。設定の「モデルを残す時間」で自動でも
        降りるが、**今すぐ空けたいときの道**をメニューにも置く。
        """
        window = self._window
        if window._assistant.is_running():
            window.notify("答えを待っている間は降ろせません")
            return False
        if not getattr(window._llm, "is_loaded", lambda: False)():
            window.notify("モデルは読み込まれていません")
            return False
        if not window._llm.unload():
            window.notify("モデルを降ろせませんでした")
            return False
        window.notify("モデルを降ろしました")
        return True

    def release_model(self) -> None:
        """黙って降ろす（閉じたとき・終わるとき）。

        **答えの途中では降ろさない。** 走っている生成を壊す。
        載っていなければ何もしない（無駄な通信をしない）。
        """
        window = self._window
        if window._assistant.is_running():
            return
        release = getattr(window._llm, "unload", None)
        if release is None or not getattr(window._llm, "is_loaded", lambda: False)():
            return
        release()

    # ------------------------------------------------------------- 生成

    def ask_assistant(self, task: llm_module.Task) -> None:
        """今開いているノートを読ませる（L-1）。

        **渡すのは今のノートの本文だけ。** 本文は書き換えない（R1）ので、
        答えはペインにしか出ない。生成は別スレッド（§6.6）。
        """
        window = self._window
        if window._note is None or window._assistant.is_running():
            return
        prompt = llm_module.build_prompt(task, window._editor.toPlainText())
        if prompt is None:
            window._assistant.fail("本文が空です。")
            return

        self.start(prompt)

    def start(self, prompt: str, *, keep_notes: bool = False) -> None:
        """読ませて、届いたぶんから出す。**打鍵の経路に入れない**（§6.6）。"""
        window = self._window
        window._assistant_run += 1
        run = window._assistant_run
        window._assistant.begin(keep_notes=keep_notes)
        # **読み込み中はそう言う**（ユーザー報告 2026-08-24）。26b で最初の
        # 1 行まで 6 分半かかる（実測）。何も言わないと壊れたように見える
        # `is_loaded` を持たない相手（試験の偽物・古い実装）は「載っている」
        # 扱いにする。案内が出ないだけで、動きは変わらない
        if not getattr(window._llm, "is_loaded", lambda: True)():
            window._assistant.set_status(
                f"「{window._llm.model}」を読み込んでいます…（初回は数分かかります）"
            )
        # **親を付けず、こちらで参照を持つ**（索引の SyncReporter と同じ
        # 作法）。窓の子にすると、ワーカーが返す前に窓ごと壊れて
        # "Signal source has been deleted" で落ちる。逆に参照を捨てると
        # 知らせが届く前に消える。1 回ぶんだけ持てばよいので、次の回で
        # 置き換わる（前の回の繋ぎ先も一緒に落ちる）
        reporter = AssistantReporter()
        window._assistant_reporter = reporter
        # **遅れて届いた前の回の言葉を出さない。** 閉じたあとにも触らない
        reporter.chunk.connect(lambda chunk: self._if_current(run, window._assistant.append, chunk))
        reporter.finished.connect(lambda: self._if_current(run, window._assistant.finish))
        reporter.failed.connect(lambda reason: self._if_current(run, self._on_failed, reason))
        QThreadPool.globalInstance().start(
            AssistantTask(window._llm, prompt, reporter, lambda: window._assistant_run != run)
        )

    def _if_current(self, run: int, handler, *args) -> None:
        """その回がまだ今の回なら渡す。**古い回と閉じたあとは捨てる。**"""
        window = self._window
        if run == window._assistant_run and not window._closing:
            handler(*args)

    def stop_assistant(self) -> None:
        """待つのをやめる。**書きかけは残す**（そこまでは読める）。

        番号を進めるだけで止まる（走っている回は自分の番号と見比べている）。
        """
        window = self._window
        window._assistant_run += 1
        window._assistant.cancel()

    def _on_failed(self, reason: str) -> None:
        """うまくいかなかった理由を**日本語で**出す。

        生の英語（Connection refused など）は出さないが、**何が起きたかで
        言うことは変える**。時間切れを「動いているか確かめてください」と
        案内すると、動いているのに動いていないと言われて辿り着けない
        （ユーザー報告 2026-08-24）。
        """
        window = self._window
        if reason == llm_module.TimedOut.__name__:
            minutes = window._config.llm_timeout_minutes
            window._assistant.fail(
                f"{minutes} 分待っても答えが返りませんでした。"
                "大きいモデルは読み込みだけで数分かかります"
                "（設定の「アシスタント」で待ち時間を延ばせます）。"
            )
        else:
            window._assistant.fail("Ollama に繋がりませんでした。動いているか確かめてください。")
        window._assistant.set_available(window._llm.available())

    # ------------------------------------------------------------- 関連と質問

    def show_related(self, *_args) -> None:
        """今のノートに関係するノートを並べる（L-3）。

        **モデルは通さない。** 関係の根拠は索引の中にある（同じタグ・
        `[[…]]` の指し合い・題名の言及）。選ばせると、なぜ関係するのか
        確かめられないうえ待たされ、Ollama を入れていない人には何も出ない。
        """
        window = self._window
        if window._note is None:
            return
        rows = window._db.notes()
        relative = window._note.path.relative_to(window._vault.root)
        found = related.rank(self._related_signals(rows), exclude=str(relative))

        titles = {str(row.path): row.title for row in rows}
        window._assistant.set_related(
            [
                (Path(item.key), titles.get(item.key) or Path(item.key).stem, item.reasons)
                for item in found
            ]
        )

    def _related_signals(self, rows: list[NoteRow]) -> list[related.Signal]:
        """索引から根拠を集める（L-3）。**理由の文言もここで決める。**"""
        window = self._window
        note = window._note
        if note is None:
            return []
        note_id = note_key(note, window._vault.root)
        found: list[related.Signal] = []

        # 手で結んだものがいちばん強い（`[[…]]`）
        for row in window._db.backlinks(note.title):
            found.append(related.Signal(str(row.path), "このノートを指している", related.LINK))

        by_title = {normalize(row.title): row for row in rows}
        for target in window._db.links_of(note_id):
            row = by_title.get(normalize(target))
            if row is not None:
                found.append(
                    related.Signal(str(row.path), f"[[{target}]] で指している", related.LINK)
                )

        for tag in window._db.tags_of(note_id):
            for row in window._db.notes_sharing_tags([tag]):
                found.append(related.Signal(str(row.path), f"同じタグ #{tag}", related.SHARED_TAG))

        # 題名が本文に出てくる（手で結んでいなくても言及は関係の印）
        if note.title:
            for hit in window._db.search(note.title, limit=related.DEFAULT_LIMIT):
                found.append(related.Signal(str(hit.path), "題名が本文に出てくる", related.TEXT))
        return found

    def ask_question(self, question: str) -> None:
        """vault 全体に質問する（L-2 / ADR-0025）。

        **材料はこちらが選ぶ。** 索引で候補を引き、その本文を渡す。
        モデルは探せないし、**出典を作文させない**ため、実際に渡した
        ノートだけを画面に並べる。

        当たりが 1 つも無ければ**読ませない**（材料の無い問いに答えさせると
        作り話が出る。GPU を回す意味もない）。
        """
        window = self._window
        if window._assistant.is_running():
            return
        hits = self._sources_for(question)
        if not hits:
            window._assistant.set_sources([])
            return

        # **出典は答えより先に出す。** 待っている間、何を見ているのか分かる
        window._assistant.set_sources([(hit.path, hit.title) for hit in hits])

        sources = llm_module.pack([(hit.title, self._read_for_llm(hit.path)) for hit in hits])
        prompt = llm_module.build_question_prompt(question, sources)
        if prompt is None:
            return
        self.start(prompt, keep_notes=True)

    def _sources_for(self, question: str) -> list:
        """質問に答える材料を索引から集める（L-2）。

        **質問をそのまま探さない。** 全文検索は打った通りの並びを探すので、
        「予算について何が決まった？」ではどのノートにも当たらない（実測で
        0 件だった）。`core/keywords` で語に切り、**1 語ずつ探して束ねる**。

        タグと日付の絞り込み（`#仕事` `after:`）は検索欄と同じ書き方が効く。
        """
        window = self._window
        parsed = searchquery.parse(question)
        found: list = []
        seen: set[str] = set()

        def collect(text: str) -> None:
            for hit in window._db.search(
                text,
                tags=parsed.tags,
                after=parsed.after,
                before=parsed.before,
                limit=llm_module.SOURCE_LIMIT,
            ):
                key = str(hit.path)
                if key not in seen:
                    seen.add(key)
                    found.append(hit)

        words = keywords.terms(parsed.text)
        for word in words:
            collect(word)
        if not words:
            # 語が取り出せない問い（記号だけ・ひらがなだけ）は打った通りに探す。
            # タグだけの絞り込み（`#仕事`）もここを通る
            collect(parsed.text)
        return found[: llm_module.SOURCE_LIMIT]

    def _read_for_llm(self, relative: Path) -> str:
        """材料として渡す本文。**front matter は外す**（画面に見えていない）。"""
        window = self._window
        try:
            text = (window._vault.root / relative).read_text(encoding="utf-8")
        except OSError:
            return ""
        return frontmatter.split(text).body.strip()
