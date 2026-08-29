"""コマンドパレットを窓に繋ぐ（U-3）。

**ノートを開く道具と同じ `Palette` を使う。** 入口が増えても操作を
覚え直さずに済む（アウトラインのパレットと同じ考え方）。
"""

import pytest

pytestmark = pytest.mark.gui


class TestOpen:
    def test_開ける(self, window, qtbot) -> None:
        palette = window.command_palette()
        try:
            assert palette is not None
            assert palette.isVisible()
        finally:
            palette.close()

    def test_命令が並ぶ(self, window) -> None:
        palette = window.command_palette()
        try:
            labels = [item.title for item in palette.items]
            assert "新規ノート" in labels
        finally:
            palette.close()

    def test_どこの項目か出る(self, window) -> None:
        palette = window.command_palette()
        try:
            found = next(item for item in palette.items if item.title == "新規ノート")
            assert "ファイル" in found.subtitle
        finally:
            palette.close()

    def test_絞り込める(self, window) -> None:
        palette = window.command_palette()
        try:
            palette.open_with("新規")
            labels = [item.title for item in palette.items]
            assert labels and all("新" in label or "規" in label for label in labels)
        finally:
            palette.close()


class TestRun:
    def test_選ぶと動く(self, window, qtbot) -> None:
        """**選んで終わりではない。** 実際にその命令が走る。"""
        palette = window.command_palette()
        try:
            before = window.reference.isHidden()
            # **絞ってから選ぶ。** 空の入力では上位 50 件しか並ばない
            palette.open_with("横に開く")
            found = next(item for item in palette.items if item.title == "横に開く欄")
            palette.chosen.emit(found)
            assert window.reference.isHidden() is not before
        finally:
            palette.close()
