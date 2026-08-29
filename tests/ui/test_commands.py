"""コマンドパレット（U-3。ユーザー要望 2026-08-29）。

**クイックオープンはノートを開く道**で、命令を探す口が無かった。
メニューが増えた（O-2 / O-3 で整理した）いま、名前で引ける入口が要る。

命令は**メニューバーから集める**。別に一覧を持つと、メニューに足した
のにパレットに出ない（あるいはその逆）が起きる——「同じことをする道が
2 つ」の形は直近で何度も踏んだ。
"""

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenuBar

from hitofude.ui.commands import commands

pytestmark = pytest.mark.gui


@pytest.fixture
def bar(qtbot) -> QMenuBar:
    """**実アプリと同じ作りで組む。**

    `menu.addAction("文字列")` で作ると、PySide が `QAction` を回収して
    しまい「already deleted」になる（実際に踏んだ）。`ui/menus._add` は
    `QAction(label, window)` と**窓に親を付けて**台帳にも登録するので
    起きない。試験だけ脆い作りにすると、本物と違うものを見てしまう。
    """
    found = QMenuBar()
    qtbot.addWidget(found)

    def item(menu, label: str, *, enabled: bool = True) -> QAction:
        action = QAction(label, found)
        action.setEnabled(enabled)
        menu.addAction(action)
        return action

    file_menu = found.addMenu("ファイル")
    item(file_menu, "新しいノート")
    file_menu.addSeparator()
    export = file_menu.addMenu("書き出す")
    item(export, "PDF…")
    item(export, "HTML…")
    view = found.addMenu("表示")
    item(view, "サイドバー")
    item(view, "使えない項目", enabled=False)
    # メニューそのものも手放さない（親は menuBar だが Python 側の参照を残す）
    found._kept = [file_menu, export, view]  # type: ignore[attr-defined]
    return found


class TestCollect:
    def labels(self, bar) -> list[str]:
        return [command.label for command in commands(bar)]

    def test_項目を集める(self, bar) -> None:
        assert "新しいノート" in self.labels(bar)

    def test_入れ子も集める(self, bar) -> None:
        """**▸ の中に埋もれた項目こそ探したい。**"""
        assert "PDF…" in self.labels(bar)

    def test_区切りは入れない(self, bar) -> None:
        assert "" not in self.labels(bar)

    def test_開くだけの項目は入れない(self, bar) -> None:
        """`書き出す ▸` は押しても中が開くだけ。命令ではない。"""
        assert "書き出す" not in self.labels(bar)

    def test_使えない項目は入れない(self, bar) -> None:
        """**押せないものを並べない。** 選んでも何も起きない。"""
        assert "使えない項目" not in self.labels(bar)

    def test_どこの項目か分かる(self, bar) -> None:
        """同じ言葉が別のメニューにもあるので、道筋を添える。"""
        found = next(c for c in commands(bar) if c.label == "PDF…")
        assert found.path == "ファイル ▸ 書き出す"

    def test_直下の項目の道筋はメニュー名だけ(self, bar) -> None:
        found = next(c for c in commands(bar) if c.label == "新しいノート")
        assert found.path == "ファイル"

    def test_動かせる(self, bar) -> None:
        """集めたものから**実際に呼べる**こと。"""
        pressed: list[str] = []
        for command in commands(bar):
            if command.label == "サイドバー":
                command.action.triggered.connect(lambda: pressed.append("ok"))
                command.action.trigger()
        assert pressed == ["ok"]
