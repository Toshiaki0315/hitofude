"""メインウィンドウ（spec §5.1）。

Phase 0 では空のウィンドウ。3 ペインの `QSplitter` 構成はタスク 5-1 で入れる。
"""

from PySide6.QtWidgets import QMainWindow, QWidget

from hitofude import APP_NAME

DEFAULT_SIZE = (1100, 720)
# サイドバー 180px + ノートリスト 280px + エディタの最低幅（spec §5.1）
MINIMUM_SIZE = (720, 480)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)
