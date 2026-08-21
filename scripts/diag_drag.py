"""ドラッグ＆ドロップが始まらない件の切り分け（一時的な調査用）。

ふつうに起動したうえで、ドラッグの道すじだけを実況する。

    uv run python scripts/diag_drag.py

**先に Hitofude を終了してから**実行すること（同じ vault は二重に開けない）。
起動したら、動かせないノートをフォルダへドラッグして、端末に出た行を
そのまま貼ってほしい。出る順番はこうなる。

    [1] つまんだ    … Qt がドラッグを始めた（`startDrag`）
    [2] 中身を作る  … 運ぶパスを詰めた（`mimeData`）
    [3] 入ってきた  … サイドバーに届いた（`dragEnterEvent`）
    [4] 上にいる    … フォルダの上を通った（`dragMoveEvent`）
    [5] 落ちた      … 離した（`dropEvent`）

どこで止まるかで原因が分かれる。**[1] すら出なければ** Qt がドラッグを
始めていない。[2] で例外が出ていれば、そこで落ちている（Qt は中身を
受け取れず、ドラッグごと消える）。[3] が出なければサイドバーまで
届いていない。

**設定は書き換えない**（保管フォルダは今の設定のまま開く）。
"""

import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QMessageBox

from hitofude import APP_NAME
from hitofude.app import acquire_vault_lock, create_application
from hitofude.config import Config
from hitofude.storage.vault import Vault
from hitofude.ui.main_window import MainWindow
from hitofude.ui.note_list import NOTE_MIME, NoteListModel, NoteListView
from hitofude.ui.sidebar import Sidebar


def say(text: str) -> None:
    print(text, flush=True)


def install_probes() -> None:
    """本物のメソッドを包んで実況する。中身は変えない。"""

    original_start = NoteListView.startDrag

    def start_drag(self, actions):
        say(f"[1] つまんだ: 選択={len(self.selectedIndexes())} 行 actions={actions}")
        try:
            return original_start(self, actions)
        except Exception:
            say("[1] つまむところで例外:\n" + traceback.format_exc())
            raise

    NoteListView.startDrag = start_drag

    original_mime = NoteListModel.mimeData

    def mime_data(self, indexes):
        found = list(indexes)
        say(f"[2] 中身を作る: 渡された index={len(found)}")
        try:
            mime = original_mime(self, found)
        except Exception:
            # ここで例外が出ると Qt は中身を受け取れず、ドラッグごと消える
            say("[2] 中身を作るところで例外:\n" + traceback.format_exc())
            raise
        payload = bytes(mime.data(NOTE_MIME)).decode("utf-8", "replace")
        say(f"[2] 中身: formats={mime.formats()} payload={payload!r}")
        return mime

    NoteListModel.mimeData = mime_data

    for step, name in ((3, "dragEnterEvent"), (4, "dragMoveEvent"), (5, "dropEvent")):
        original = getattr(Sidebar, name)

        def wrapper(self, event, *, _original=original, _step=step, _name=name):
            point = event.position().toPoint()
            folder = self._drop_folder(point)
            try:
                result = _original(self, event)
            except Exception:
                say(f"[{_step}] {_name} で例外:\n" + traceback.format_exc())
                raise
            say(
                f"[{_step}] {_name}: 位置={point.x()},{point.y()} "
                f"受け先={folder!r} 受けた={event.isAccepted()}"
            )
            return result

        setattr(Sidebar, name, wrapper)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    install_probes()

    app = create_application(sys.argv[:1])
    config = Config()
    say(f"保管フォルダ: {config.vault_path}")

    lock = acquire_vault_lock(Vault(config.vault_path).managed_dir)
    if lock is None:
        QMessageBox.information(
            None, APP_NAME, "先に Hitofude を終了してから、もう一度実行してください。"
        )
        return 0
    try:
        window = MainWindow(config)
        window.show()
        say("準備できた。動かせないノートをフォルダへドラッグしてみてほしい。")
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
