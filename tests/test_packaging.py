"""`.app` の組み方が実装とずれていないか（ユーザー報告 2026-08-26）。

`make app` は普段のテストで動かないので、**ずれても気づけない**。実際に
2 つ踏んだ:

- Mermaid（ADR-0021）で入れた `QtWebEngine` を `setup.py` が除外し続けて
  いて、`.app` が起動と同時に落ちた
- 数式の `ziamath` はフォントを同梱していて実行時に読むのに、`packages` に
  入っていなかった（`.py` だけ拾われ `ziamath.fonts` が無い）

どちらも「import しているのに包み方に書いていない」形なので、
**ソースの import と `setup.py` を突き合わせる**ことで機械で捕まえる。
"""

import ast
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HITOFUDE = PROJECT_ROOT / "hitofude"

# 標準ライブラリと自分自身は包み方の対象外
SELF = {"hitofude"}


def _setup_options() -> dict:
    """`setup.py` を読まずに OPTIONS だけ取り出す。

    import すると `setup()` が走ってしまうので、AST で該当の代入を拾う。
    """
    tree = ast.parse((PROJECT_ROOT / "setup.py").read_text(encoding="utf-8"))
    found: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("OPTIONS", "EXCLUDES"):
                found[name] = _literal(node.value)
    return found


def _literal(node: ast.AST):
    """定数だけ読む。**関数呼び出しは None にする**（`str(ROOT / ...)` がある）。"""
    match node:
        case ast.Constant(value=value):
            return value
        case ast.List(elts=items) | ast.Tuple(elts=items):
            return [_literal(item) for item in items]
        case ast.Dict(keys=keys, values=values):
            return {_literal(k): _literal(v) for k, v in zip(keys, values, strict=True)}
        case _:
            return None


def _imported_roots() -> set[str]:
    """`hitofude/` 全体が import しているトップレベルの名前。"""
    roots: set[str] = set()
    for path in HITOFUDE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            match node:
                case ast.Import(names=names):
                    roots.update(alias.name.split(".")[0] for alias in names)
                case ast.ImportFrom(module=str(module), level=0):
                    roots.add(module.split(".")[0])
    return roots


def _imported_names() -> set[str]:
    """import している名前（`PySide6.QtWebEngineWidgets` のような点付きも含む）。"""
    names: set[str] = set()
    for path in HITOFUDE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            match node:
                case ast.Import(names=aliases):
                    names.update(alias.name for alias in aliases)
                case ast.ImportFrom(module=str(module), level=0):
                    names.add(module)
        # `importlib.import_module("PySide6.QtWebEngineWidgets")` のような
        # 文字列での読み込みも見る（先読み用の関数がこの形。app.py）
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("PySide6.")
            ):
                names.add(node.value)
    return names


def _third_party(roots: set[str]) -> set[str]:
    """標準ライブラリと自分を除いた、外から入れているもの。"""
    found = set()
    for name in roots - SELF:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            continue
        if "site-packages" in spec.origin or (
            spec.submodule_search_locations
            and any("site-packages" in str(entry) for entry in spec.submodule_search_locations)
        ):
            found.add(name)
    return found


class TestPackages:
    def test_外から入れたものは全部包む(self) -> None:
        """`packages` か `includes` に無いと `.app` の中で ImportError。"""
        options = _setup_options()["OPTIONS"]
        packed = set(options["packages"]) | set(options["includes"])
        missing = sorted(_third_party(_imported_roots()) - packed)
        assert not missing, f"setup.py の packages に足りない: {missing}"


class TestExcludes:
    def test_使っているものを除外しない(self) -> None:
        """除外に書いたものを import していたら、`.app` は起動と同時に落ちる。"""
        excludes = set(_setup_options()["EXCLUDES"])
        used = sorted(name for name in _imported_names() if name in excludes)
        assert not used, f"setup.py の excludes に入っているのに使っている: {used}"

    @pytest.mark.parametrize("name", ["PySide6.QtWebEngineWidgets", "ziamath"])
    def test_踏んだものを名指しで見る(self, name: str) -> None:
        """回帰。実際に `.app` が起動しなくなった 2 つ。"""
        options = _setup_options()
        assert name not in options["EXCLUDES"]
        packed = set(options["OPTIONS"]["packages"]) | set(options["OPTIONS"]["includes"])
        assert name.split(".")[0] in packed
