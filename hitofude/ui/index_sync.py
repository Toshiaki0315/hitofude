"""索引の走査を背景で回す部品（spec §6.6, §7.3）。

`MainWindow` から切り出した。走査そのものはウィンドウの都合を知らない。
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

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

    def __init__(self, db_path: Path, vault: Vault, reporter: SyncReporter) -> None:
        super().__init__()
        self._db_path = db_path
        self._vault = vault
        self._reporter = reporter

    def run(self) -> None:
        try:
            with IndexDb(self._db_path) as db:
                result = db.sync(self._vault)
        except Exception as error:
            logger.exception("索引の同期に失敗した")
            self._reporter.failed.emit(error)
            return
        self._reporter.finished.emit(result)
