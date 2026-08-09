"""アーキテクチャ規約の自動検査（CLAUDE.md R3 / spec §6.1）。

`core/` と `storage/` を PySide6 非依存に保つ。これが崩れるとパーサと保存ロジックを
ヘッドレスでテストできなくなり、テスト戦略ごと破綻する。
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HITOFUDE = PROJECT_ROOT / "hitofude"

# spec §6.1 の唯一の例外: watchdog のイベントを Qt シグナルへ橋渡しする箇所
QT_ALLOWED = {HITOFUDE / "storage" / "watcher.py"}

GUI_FREE_PACKAGES = ("core", "storage")


def _python_files(package: str) -> list[Path]:
    return sorted(p for p in (HITOFUDE / package).rglob("*.py") if p.name != "__init__.py")


def _imported_roots(path: Path) -> set[str]:
    """そのファイルが import しているトップレベルモジュール名の集合。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                roots.update(alias.name.split(".")[0] for alias in names)
            case ast.ImportFrom(module=str(module), level=0):
                roots.add(module.split(".")[0])
    return roots


@pytest.mark.parametrize("package", GUI_FREE_PACKAGES)
def test_パッケージが存在する(package: str) -> None:
    assert (HITOFUDE / package / "__init__.py").is_file()


@pytest.mark.parametrize("package", GUI_FREE_PACKAGES)
def test_coreとstorageはPySide6に依存しない(package: str) -> None:
    violations = [
        path.relative_to(PROJECT_ROOT)
        for path in _python_files(package)
        if path not in QT_ALLOWED and "PySide6" in _imported_roots(path)
    ]
    assert not violations, (
        f"{violations} が PySide6 を import している。"
        "core/ と storage/ は GUI 非依存に保つこと（CLAUDE.md R3）"
    )


MARKDOWN_ROUNDTRIP_API = frozenset({"setMarkdown", "toMarkdown"})


def test_setMarkdownをどこでも使っていない() -> None:
    """CLAUDE.md R2 / spec §3.3: 往復変換でデータが壊れることを実機検証済み。

    **例外はもう無い。** かつては HTML/PDF の書き出しだけが許されていたが、
    B-2 で書き出しを markdown-it-py に移した（ADR-0007）。理由は R2 の趣旨
    （往復変換）ではなく、`setMarkdown()` がコードフェンスの言語・生 HTML・
    脚注を落とすため。除外を消せたので、ここも全ファイルを見る。

    判定は AST の属性アクセスで行う。文字列一致にすると「なぜこの API を
    使わないのか」を説明したコメント自体が違反として検出されてしまう。
    """
    offenders: list[str] = []
    for path in HITOFUDE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{node.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in MARKDOWN_ROUNDTRIP_API
        )
    assert not offenders, (
        f"{offenders} が QTextDocument の Markdown 変換 API を使っている（CLAUDE.md R2）"
    )
