"""画面に出る言葉を揃える（ユーザー要望 2026-08-22）。

**同じものを 2 通りで呼ばない。** メニューは「環境設定…」なのに窓の題は
「環境設定」、説明では「設定」……のように揺れると、探すときに手がかりが
増えず、書いた説明も辿れなくなる。

ここは**言葉の検査**。実装の振る舞いではなく、**画面に出る文字列**を
機械で見る（人が気づけるのは、たいてい直した後）。
"""

import ast
import pathlib

import pytest

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui

UI_DIR = pathlib.Path(__file__).resolve().parents[2] / "hitofude"
MANUAL = UI_DIR / "resources" / "manual.md"

# 「こう呼ぶ」と決めた言葉と、混ざりやすい別名
CHOSEN = {
    "設定": "環境設定",
    "ノートの一覧": "ノートリスト",
    "保管フォルダ": "ノートフォルダ",
    "テンプレート": "雛形",
}


def ui_strings() -> list[tuple[str, str]]:
    """画面に出うる文字列（`(ファイル名, 文字列)`）。

    **docstring とコメントは見ない。** 開発者向けの言葉まで縛ると、
    直す理由の説明ができなくなる。
    """
    found: list[tuple[str, str]] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            written = isinstance(node, ast.Constant) and isinstance(node.value, str)
            if written and id(node) not in docstrings:
                found.append((path.name, node.value))
    return found


class TestChosenWords:
    @pytest.mark.parametrize(("chosen", "avoided"), CHOSEN.items())
    def test_画面には決めた言葉だけを出す(self, chosen: str, avoided: str) -> None:
        slips = [
            f"{name}: {text}" for name, text in ui_strings() if avoided in text and text.strip()
        ]
        assert slips == [], f"「{avoided}」ではなく「{chosen}」で揃える"

    @pytest.mark.parametrize(("chosen", "avoided"), CHOSEN.items())
    def test_使い方のノートも同じ言葉(self, chosen: str, avoided: str) -> None:
        """**説明とボタンの言葉が違うと、説明を読んでも探せない。**"""
        text = MANUAL.read_text(encoding="utf-8")
        assert avoided not in text, f"使い方のノートで「{avoided}」を使っている"


class TestMenus:
    def test_メニューの言葉が揃っている(self, window: MainWindow) -> None:
        labels = set(window.menu_actions)
        assert "設定…" in labels
        assert "環境設定…" not in labels
        assert "ノートの一覧" in labels

    def test_設定の窓の題も同じ(self, window: MainWindow) -> None:
        from hitofude.ui.preferences import PreferencesDialog

        dialog = PreferencesDialog(window._config, window)
        try:
            assert dialog.windowTitle() == "設定"
        finally:
            dialog.deleteLater()
