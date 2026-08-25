"""メニューの絵は焼いてから渡す（性能。2026-08-25 の実測）。

`make bench` の「起動 → ウィンドウ表示」が **1923ms**（基準 1500ms）で
落ちていた。分解すると `MainWindow` の構築が 1 秒で、その中身は
**`QIcon.fromTheme()` の戻りをネイティブメニューへ入れる瞬間**だった。

| 20 個をメニューバーへ入れる | 所要 |
| --- | --- |
| `fromTheme` をそのまま | **255ms**（1 個 13ms） |
| **先に絵へ焼いてから** | **14ms** |
| 絵なし | 0ms |
| ポップアップへ `fromTheme` | 0ms |

**遅いのはネイティブメニューへの挿入だけ**（`fromTheme` を呼ぶこと自体は
0ms、ポップアップも 0ms）。焼いてから渡すと **1923ms → 1374ms** になり、
基準に収まった。**見た目は変わらない。**

戻ってしまうのを防ぐため、**`QIcon.fromTheme` を `icons.py` の外で
呼ばせない**（`test_architecture.py` と同じ作法の検査）。
"""

import ast
from pathlib import Path

import pytest

from hitofude.ui.icons import MENU_ICONS, _baked_icon, menu_icon

pytestmark = pytest.mark.gui

HITOFUDE = Path(__file__).resolve().parent.parent.parent / "hitofude"
BAKERY = HITOFUDE / "ui" / "icons.py"
"""ここだけが `QIcon.fromTheme` を呼んでよい。"""


def _calls_from_theme(path: Path) -> bool:
    """`…​.fromTheme(...)` を呼んでいるか。

    **呼ぶ相手の名前は見ない。** `QIcon` だけを見ていたら、
    `from PySide6.QtGui import QIcon as _QI` と別名にした変異が素通りした
    （実測）。`fromTheme` という名前の呼び出しはこの用途しかない。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.Attribute) and node.attr == "fromTheme" for node in ast.walk(tree)
    )


class TestOnlyOnePlaceBakes:
    """**`QIcon.fromTheme` は 1 か所だけ。** 直に呼ぶと起動が 0.5 秒延びる。"""

    def test_他の場所では呼ばない(self) -> None:
        offenders = [
            str(path.relative_to(HITOFUDE))
            for path in sorted(HITOFUDE.rglob("*.py"))
            if path != BAKERY and _calls_from_theme(path)
        ]
        assert offenders == [], f"焼かずに渡している: {offenders}"

    def test_焼く場所は残っている(self) -> None:
        """検査が空振りしていないこと（呼び出しを消したら気づけるように）。"""
        assert _calls_from_theme(BAKERY)

    def test_焼いてから返している(self) -> None:
        """**ソースを見る。** offscreen では OS の絵が空で返るので、
        焼いたかどうかを**戻り値からは見分けられない**（`isNull()` も
        `name()` も同じ）。焼くのをやめる変異が素通りしたので、
        `pixmap(...)` を通していることを直に見張る。
        """
        tree = ast.parse(BAKERY.read_text(encoding="utf-8"), filename=str(BAKERY))
        baker = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_baked_icon"
        )
        assert any(
            isinstance(node, ast.Attribute) and node.attr == "pixmap" for node in ast.walk(baker)
        ), "焼かずにテーマの絵をそのまま返している"


class TestMenuIcon:
    def test_台帳にある言葉には絵を返す(self) -> None:
        assert menu_icon("新規ノート") is not None

    def test_台帳に無い言葉には返さない(self) -> None:
        """チェック印の付く項目には付けない（印が絵を隠すため）。"""
        assert menu_icon("サイドバー") is None

    @pytest.mark.parametrize("label", sorted(MENU_ICONS))
    def test_台帳の言葉は全部引ける(self, label: str) -> None:
        assert menu_icon(label) is not None

    def test_同じ絵は焼き直さない(self) -> None:
        """**焼くのが高い**（1 個 13ms）。メニューバーと右クリックで共用する。"""
        name = MENU_ICONS["新規ノート"]
        assert _baked_icon(name, 2.0) is _baked_icon(name, 2.0)

    def test_画面の倍率ごとに焼く(self) -> None:
        """**16x16 で焼くと Retina でぼやける。** 倍率が違えば別物。"""
        name = MENU_ICONS["新規ノート"]
        assert _baked_icon(name, 1.0) is not _baked_icon(name, 2.0)


class TestMenusUseIt:
    def test_メニューバーの項目に絵が付く(self, window) -> None:
        """**付かなくなっていないこと。** 速さのために消してしまわない。

        offscreen では OS の絵が空で返るので、**絵そのもの**は見られない。
        見るのは「台帳の言葉には絵を設定しに行っている」ところまで。
        """
        labels = {action.text() for action in window.menus["ファイル"].actions()}
        assert labels & set(MENU_ICONS), labels
