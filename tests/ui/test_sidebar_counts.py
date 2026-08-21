"""件数を名前から切り離して出す（ユーザー要望 2026-08-22）。

`テスト２  2` のように、**名前が数字で終わると件数と見分けが付かなかった**。
括弧で囲む手もあるが、同じ色・同じ並びのままなので `日報 (2)` のような
名前を付けた人には結局読み分けが要る。

**位置で分ける。** 名前は左、件数は右端に薄い色で置く（Finder や Mail と
同じ作法）。狭いときに削るのは名前のほうで、件数は必ず見える。
"""

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QStyleOptionViewItem

from hitofude.storage.index_db import ROOT_FOLDER, FolderCount, TagCount
from hitofude.theme import LIGHT
from hitofude.ui.sidebar import COUNT_GAP, COUNT_ROLE, Sidebar, SidebarItemDelegate

pytestmark = pytest.mark.gui

FOLDERS = [
    FolderCount(folder=ROOT_FOLDER, count=9),
    FolderCount(folder="仕事", count=3),
    FolderCount(folder="テスト２", count=2),
]


@pytest.fixture
def sidebar(qtbot) -> Sidebar:
    widget = Sidebar()
    qtbot.addWidget(widget)
    return widget


def find(sidebar: Sidebar, label: str):
    """表示名がその文字列の行を返す（子も見る）。"""
    model = sidebar.model()

    def walk(item):
        if item.text() == label:
            return item
        for row in range(item.rowCount()):
            found = walk(item.child(row))
            if found is not None:
                return found
        return None

    for row in range(model.rowCount()):
        found = walk(model.item(row))
        if found is not None:
            return found
    return None


class TestData:
    """**名前に数を混ぜない。** 混ざっていると、描く側で切り分けられない。"""

    def test_表示名は名前だけ(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        assert find(sidebar, "テスト２") is not None

    def test_件数は別に持つ(self, sidebar) -> None:
        sidebar.set_folders(FOLDERS)
        assert find(sidebar, "テスト２").data(COUNT_ROLE) == 2

    def test_タグも同じ(self, sidebar) -> None:
        sidebar.set_tags([TagCount(tag="日報", count=4)])
        assert find(sidebar, "日報").data(COUNT_ROLE) == 4

    def test_フォルダの見出しも同じ(self, sidebar) -> None:
        """見出しの「フォルダ」は直下そのもの（0bd3b84）なので件数を持つ。"""
        sidebar.set_folders(FOLDERS)
        assert find(sidebar, "フォルダ").data(COUNT_ROLE) == 9

    def test_件数の無い行もある(self, sidebar) -> None:
        """「すべて」「ゴミ箱」に数は付かない。無いことを区別できること。"""
        assert find(sidebar, "すべて").data(COUNT_ROLE) is None


class TestPaint:
    """描いた絵で確かめる。持たせただけでは見えない。"""

    WIDTH = 200
    HEIGHT = 26

    def painted(self, label: str, count: int | None) -> QImage:
        from PySide6.QtGui import QStandardItem, QStandardItemModel

        model = QStandardItemModel()
        item = QStandardItem(label)
        if count is not None:
            item.setData(count, COUNT_ROLE)
        model.appendRow(item)

        delegate = SidebarItemDelegate(LIGHT)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, self.WIDTH, self.HEIGHT)
        # **名前をテーマの色で描かせる。** 既定の黒のままだと「名前の色が
        # 件数の場所に無いこと」を確かめても、色違いで素通りしてしまう
        option.palette.setColor(QPalette.ColorRole.Text, QColor(LIGHT.foreground))
        option.palette.setColor(QPalette.ColorRole.WindowText, QColor(LIGHT.foreground))

        image = QImage(QSize(self.WIDTH, self.HEIGHT), QImage.Format.Format_ARGB32)
        image.fill(QColor(LIGHT.background))
        painter = QPainter(image)
        delegate.paint(painter, option, model.index(0, 0))
        painter.end()
        return image

    def ink(self, image: QImage, left: int, right: int) -> int:
        """その帯にある「背景でない点」の数。"""
        background = QColor(LIGHT.background).rgb()
        return sum(
            1
            for x in range(left, right)
            for y in range(image.height())
            if image.pixel(x, y) != background
        )

    def test_件数は右端に出る(self, qapp) -> None:
        with_count = self.painted("仕事", 3)
        without = self.painted("仕事", None)
        right = self.WIDTH * 3 // 4
        assert self.ink(with_count, right, self.WIDTH) > 0
        assert self.ink(without, right, self.WIDTH) == 0

    def test_名前は動かない(self, qapp) -> None:
        """件数が 1 桁でも 3 桁でも、名前の位置は変わらない。"""
        few = self.painted("仕事", 3)
        many = self.painted("仕事", 128)
        half = self.WIDTH // 2
        assert self.ink(few, 0, half) == self.ink(many, 0, half)

    def test_薄い色で描く(self, qapp) -> None:
        """**名前が主、数は添え物。** 同じ濃さだと名前の続きに見える。"""
        image = self.painted("仕事", 3)
        colors = {
            QColor(image.pixelColor(x, y)).name()
            for x in range(self.WIDTH * 3 // 4, self.WIDTH)
            for y in range(image.height())
        }
        assert LIGHT.muted_foreground.lower() in colors
        assert LIGHT.foreground.lower() not in colors

    def test_狭いときに削るのは名前(self, qapp) -> None:
        """名前が長くても件数は消えない（消えると数える手段が無くなる）。"""
        image = self.painted("とても長いフォルダの名前がここに入ります", 12)
        assert self.ink(image, self.WIDTH * 3 // 4, self.WIDTH) > 0

    def test_長い名前が件数に重ならない(self, qapp) -> None:
        """**字下げとアイコンのぶんを忘れない。** 行の幅から引くだけだと、
        名前を切り詰めても数字の上に乗る（実際に重なっていた）。"""
        from PySide6.QtGui import QFontMetrics

        image = self.painted("とても長いフォルダの名前がここに入ります", 128)
        option = QStyleOptionViewItem()
        reserved = QFontMetrics(option.font).horizontalAdvance("128") + COUNT_GAP

        colors = {
            QColor(image.pixelColor(x, y)).name()
            for x in range(self.WIDTH - reserved, self.WIDTH)
            for y in range(image.height())
        }
        assert LIGHT.foreground.lower() not in colors, "名前が件数の場所まで来ている"
        assert LIGHT.muted_foreground.lower() in colors
