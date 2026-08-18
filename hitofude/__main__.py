"""エントリポイント。`python -m hitofude` で起動する。"""

import sys

from PySide6.QtWidgets import QMessageBox

from hitofude import APP_NAME
from hitofude.app import acquire_vault_lock, create_application
from hitofude.config import Config
from hitofude.storage.vault import Vault
from hitofude.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = create_application(argv)

    # 同じ vault の二重起動を止める（H-1 層 2 / spec §6.1）。
    # 2 窓で開くと watcher が互いの保存に反応し、競合ダイアログが行き来する
    config = Config()
    lock = acquire_vault_lock(Vault(config.vault_path).managed_dir)
    if lock is None:
        QMessageBox.information(
            None,
            APP_NAME,
            "このノートフォルダは既に別のウィンドウで開いています。\nそちらをお使いください。",
        )
        return 0

    try:
        window = MainWindow(config)
        window.show()
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
