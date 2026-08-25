"""自前のツールチップ（ユーザー要望 2026-08-24）。

Qt の `QToolTip` では角が丸くならない。窓を不透明に描くうえ、
出すたびにラベルを作り直して設定を戻すので、外から透過を保てない
（試した 3 つの道が全部壊れた経緯は `app.apply_tooltip_colors`）。

**Qt に描かせるのをやめ、自分が所有する 1 つの窓を描く。** 作り直され
ないので、透過も丸みも一度決めれば保たれる。採用したウィジェットの
`QEvent.ToolTip` を受け取り、ネイティブの代わりにこれを出す。
"""

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent, QImage, QPainter
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton

from hitofude.app import TOOLTIP_BACKGROUND
from hitofude.ui import tooltip

pytestmark = pytest.mark.gui


def render(widget) -> QImage:
    """透過ごと絵にする。`grab()` は offscreen で alpha を持たない。"""
    image = QImage(widget.size() * 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(2)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    return image


def help_event(widget, at: QPoint | None = None) -> bool:
    """ツールチップの合図を送る。返り値は「消費されたか」。"""
    at = at or QPoint(5, 5)
    event = QHelpEvent(QEvent.Type.ToolTip, at, widget.mapToGlobal(at))
    return QApplication.sendEvent(widget, event)


@pytest.fixture
def button(qtbot):
    found = QPushButton("押す")
    found.setToolTip("サイドバーを折りたたむ  ⌘B")
    qtbot.addWidget(found)
    tooltip.attach(found)
    found.show()
    return found


@pytest.fixture(autouse=True)
def _hide_after():
    yield
    tooltip.hide()


class TestBubble:
    """見た目。黒地・白文字・角丸・四隅は透明。"""

    def bubble(self):
        tooltip.show(QPoint(300, 300), "サイドバーを折りたたむ  ⌘B")
        return tooltip._bubble

    def test_黒地(self, qapp) -> None:
        # 中央は文字（白）に当たるので、余白の内側（上端の少し下）を見る
        image = render(self.bubble())
        ground = image.pixelColor(image.width() // 2, 8)
        assert ground.name().upper() == TOOLTIP_BACKGROUND

    def test_四隅は透明(self, qapp) -> None:
        image = render(self.bubble())
        w, h = image.width(), image.height()
        for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            assert image.pixelColor(x, y).alpha() == 0, f"({x}, {y}) が塗られている"

    def test_文字の大きさは今までと同じ(self, qapp) -> None:
        """`apply_chrome_font` の +2pt（ユーザー要望）を引き継ぐ。"""
        from PySide6.QtWidgets import QToolTip

        assert self.bubble().font().pointSizeF() == QToolTip.font().pointSizeF()

    def test_出しても入力を奪わない(self, qapp) -> None:
        found = self.bubble()
        assert found.windowFlags() & Qt.WindowType.ToolTip
        assert found.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def test_閉じ待ちの窓にならない(self, qapp) -> None:
        """出したままでもアプリの終了を止めない（Mermaid で踏んだ轍）。"""
        assert not self.bubble().testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)


class TestGuide:
    """採用したウィジェットの合図で出し入れする。"""

    def test_合図で出る(self, qapp, button) -> None:
        assert help_event(button) is True
        assert tooltip.is_showing()
        assert tooltip.shown_text() == "サイドバーを折りたたむ  ⌘B"

    def test_文字が無ければ出ない(self, qapp, qtbot) -> None:
        plain = QPushButton("説明なし")
        qtbot.addWidget(plain)
        tooltip.attach(plain)
        plain.show()
        assert help_event(plain) is True  # ネイティブにも出させない
        assert not tooltip.is_showing()

    def test_離れたら消える(self, qapp, button) -> None:
        help_event(button)
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        assert not tooltip.is_showing()

    def test_押したら消える(self, qapp, qtbot, button) -> None:
        help_event(button)
        qtbot.mousePress(button, Qt.MouseButton.LeftButton)
        assert not tooltip.is_showing()

    def test_ウィジェットが隠れたら消える(self, qapp, button) -> None:
        help_event(button)
        button.hide()
        assert not tooltip.is_showing()

    def test_一覧のアイテムの説明も出す(self, qapp, qtbot) -> None:
        """アウトラインと関連ノートはアイテム側に説明を持つ。"""
        view = QListWidget()
        qtbot.addWidget(view)
        view.addItem("最初の見出し")
        view.item(0).setToolTip("## 最初の見出し")
        tooltip.attach_view(view)
        view.show()
        at = view.visualItemRect(view.item(0)).center()
        assert help_event(view.viewport(), at) is True
        assert tooltip.shown_text() == "## 最初の見出し"

    def test_アイテムの外では出ない(self, qapp, qtbot) -> None:
        view = QListWidget()
        qtbot.addWidget(view)
        view.addItem("最初の見出し")
        view.item(0).setToolTip("## 最初の見出し")
        tooltip.attach_view(view)
        view.resize(300, 300)
        view.show()
        assert help_event(view.viewport(), QPoint(150, 280)) is True
        assert not tooltip.is_showing()


class TestAdoption:
    """画面を組んだら一括で採用する。個別に張ると必ず張り漏れる。"""

    def test_本窓のウィジェットが採用されている(self, qapp, window) -> None:
        assert help_event(window.menu_button) is True
        assert tooltip.is_showing()

    def test_設定画面も採用されている(self, qapp, qtbot, tmp_path) -> None:
        from PySide6.QtCore import QSettings

        from hitofude.config import Config
        from hitofude.ui.preferences import PreferencesDialog

        config = Config(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        dialog = PreferencesDialog(config)
        qtbot.addWidget(dialog)
        dialog.show()
        assert help_event(dialog.port_box) is True
        assert tooltip.is_showing()

    def test_アウトラインのアイテムも採用されている(self, qapp, window) -> None:
        window.show()  # 隠れている一覧は見出しを数えない（&座標も持たない）
        window.toggle_outline()
        window.editor.setPlainText("# 見出しの一\n\n本文\n")
        window._update_outline()
        QApplication.processEvents()
        view = window._outline._list
        assert view.count() >= 1
        at = view.visualItemRect(view.item(0)).center()
        assert help_event(view.viewport(), at) is True
        assert tooltip.is_showing()
