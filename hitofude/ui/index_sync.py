"""重い処理を背景で回す部品（spec §6.6, §7.3）。

`MainWindow` から切り出した。処理そのものはウィンドウの都合を知らない。

- `IndexSyncTask` … vault の走査
- `StatsTask` … 文字数と行数の集計
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from hitofude.core.stats import count
from hitofude.storage.index_db import IndexDb
from hitofude.storage.vault import Vault

logger = logging.getLogger(__name__)


class SyncReporter(QObject):
    """ワーカーから Qt スレッドへ結果を渡すための口。"""

    finished = Signal(object)
    failed = Signal(object)


class IndexSyncTask(QRunnable):
    """vault の走査を背景で回す（spec §6.6, §7.3）。

    5,000 ノートの初回構築は約 10 秒かかる。同期で走らせると、その間
    ウィンドウが固まって操作できない。UI 側は前回の索引を読んだまま
    操作でき、走査が終わったら一覧を差し替える。

    **ワーカーは自分の `IndexDb` を開く。** sqlite3 の接続はスレッドを
    またげないため、UI 側の接続を使い回してはいけない。
    """

    def __init__(
        self, db_path: Path, vault: Vault, reporter: SyncReporter, *, full: bool = False
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._vault = vault
        self._reporter = reporter
        self._full = full
        """全部読み直すか（ユーザー要望）。**差分の 100 倍かかる**ので、
        ふだんは False。実測 5,000 本で 144ms 対 19 秒。"""

    def run(self) -> None:
        try:
            with IndexDb(self._db_path) as db:
                # **ファイルは消さない。** 消すと UI 側が持っている接続が
                # 消えた実体を読み続け、作り直したのに一覧が空になる（実測）
                result = db.rebuild_in_place(self._vault) if self._full else db.sync(self._vault)
        except Exception as error:
            logger.exception("索引の同期に失敗した")
            self._reporter.failed.emit(error)
            return
        self._reporter.finished.emit(result)


class StatsReporter(QObject):
    """数え終わりを Qt スレッドへ渡す口。"""

    counted = Signal(int, object)
    """`(合図の番号, Stats)`。番号は**古い結果を捨てる**ために付ける。"""


class StatsTask(QRunnable):
    """文字数と行数を背景で数える（ユーザー要望）。

    長い本文では時間がかかる（実測: 5 万文字で 70ms、忙しいときは 285ms）。
    打つのをやめて 0.4 秒後に走るので入力の邪魔にはならないが、その一瞬だけ
    画面が止まる。**数えるのは表示のためだけ**なので、待たせる理由がない。

    **本文は Qt スレッドで写し取ってから渡す。** ワーカーからウィジェットに
    触ると落ちる。ここへ来るのはただの文字列。
    """

    def __init__(self, text: str, token: int, reporter: StatsReporter) -> None:
        super().__init__()
        self._text = text
        self._token = token
        self._reporter = reporter

    def run(self) -> None:
        try:
            result = count(self._text)
        except Exception:
            logger.exception("文字数を数えられなかった")
            return
        self._reporter.counted.emit(self._token, result)


class AssistantReporter(QObject):
    """生成の途中経過を Qt スレッドへ渡す口（L-1 / ADR-0025）。"""

    chunk = Signal(str)
    finished = Signal()
    failed = Signal(str)


class AssistantTask(QRunnable):
    """ローカルLLM に読ませる（L-1 / ADR-0025）。

    **打鍵の経路に入れない**（§6.6）。最初の 1 文字まで実測 5.4 秒、
    答え 1 本で 11 秒かかる（M4 / gemma3:4b）ので、Qt スレッドで待つと
    その間ずっと固まる。

    **ここへ来るのはただの文字列。** ワーカーからウィジェットには触らない
    （`StatsTask` と同じ約束）。
    """

    def __init__(self, client, prompt: str, reporter: AssistantReporter, should_stop) -> None:
        super().__init__()
        self._client = client
        self._prompt = prompt
        self._reporter = reporter
        self._should_stop = should_stop

    def run(self) -> None:
        try:
            self._client.generate(
                self._prompt,
                on_chunk=self._reporter.chunk.emit,
                should_stop=self._should_stop,
            )
        except Exception as error:  # NotRunning も、途中で落ちた場合も
            logger.info("ローカルLLM に読ませられなかった: %s", error)
            self._reporter.failed.emit(str(error))
            return
        self._reporter.finished.emit()
