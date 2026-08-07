"""メインウィンドウ（spec §5.1）。

現状はエディタ 1 枚だけを載せている。サイドバー（タグツリー）と
ノートリストを加えた 3 ペインの `QSplitter` 構成はタスク 5-1 で入れる。
"""

from PySide6.QtWidgets import QMainWindow, QWidget

from hitofude import APP_NAME
from hitofude.app import ThemeWatcher
from hitofude.editor.editor_widget import MarkdownEditor
from hitofude.theme import ThemeColors

DEFAULT_SIZE = (1100, 720)
# サイドバー 180px + ノートリスト 280px + エディタの最低幅（spec §5.1）
MINIMUM_SIZE = (720, 480)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        self._theme_watcher = ThemeWatcher(parent=self)
        self._editor = MarkdownEditor(theme=self._theme_watcher.colors)
        self.setCentralWidget(self._editor)

        self._theme_watcher.changed.connect(self._on_theme_changed)

        # 起動直後にそのまま打ち始められるようにする
        self._editor.setFocus()

    @property
    def editor(self) -> MarkdownEditor:
        return self._editor

    @property
    def theme_watcher(self) -> ThemeWatcher:
        return self._theme_watcher

    def _on_theme_changed(self, colors: ThemeColors) -> None:
        self._editor.set_theme(colors)
