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


def _prune_module():
    """`scripts/prune_bundle.py` を読み込む（定数を検査するため）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "prune_bundle", PROJECT_ROOT / "scripts" / "prune_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPruneKeeps:
    """削るスクリプトが、使っているものまで削っていないか。

    ユーザー依頼のサイズ削減レビュー（2026-08-26）で発覚: `QtPdf` を
    import しているのに KEEP に無く、**`.app` の PDF 取り込みが
    壊れていた**（ModuleNotFoundError を実機で確認）。import と
    KEEP の突き合わせで機械に見張らせる。
    """

    @staticmethod
    def _qt_modules() -> set[str]:
        """`hitofude/` が import する PySide6 のモジュール名（Qt〜）。"""
        found = set()
        for name in _imported_names():
            if name.startswith("PySide6.Qt"):
                found.add(name.split(".")[1])
        return found

    def test_使うフレームワークは残す(self) -> None:
        prune = _prune_module()
        missing = sorted(self._qt_modules() - prune.KEEP_FRAMEWORKS)
        assert not missing, f"prune_bundle の KEEP_FRAMEWORKS に足りない: {missing}"

    def test_使うPython束縛は残す(self) -> None:
        prune = _prune_module()
        missing = sorted(self._qt_modules() - prune.KEEP_BINDINGS)
        assert not missing, f"prune_bundle の KEEP_BINDINGS に足りない: {missing}"

    def test_QtPdfを名指しで見る(self) -> None:
        """回帰。PDF 取り込み（F-2 / importer.py）が使う。"""
        prune = _prune_module()
        assert "QtPdf" in prune.KEEP_FRAMEWORKS
        assert "QtPdf" in prune.KEEP_BINDINGS


class TestLiteVariant:
    """Mermaid を諦める軽量版（ユーザー要望 2026-08-26）。

    `make app-lite` は WebEngine（Chromium 約 300MB）ごと削る。
    図が出ない以外は同じアプリで、**数式（ziamath + QtSvg）は残る**。
    """

    def test_liteはWebEngineを残さない(self) -> None:
        prune = _prune_module()
        frameworks, bindings = prune.keep_sets(lite=True)
        assert not frameworks & prune.WEB_ENGINE_FRAMEWORKS
        assert "QtWebEngineWidgets" not in bindings

    def test_liteでも数式とPDFの部品は残る(self) -> None:
        prune = _prune_module()
        frameworks, bindings = prune.keep_sets(lite=True)
        for name in ("QtSvg", "QtPdf", "QtPrintSupport"):
            assert name in frameworks, name
            assert name in bindings, name

    def test_通常版は今まで通り(self) -> None:
        prune = _prune_module()
        frameworks, bindings = prune.keep_sets(lite=False)
        assert frameworks == prune.KEEP_FRAMEWORKS
        assert bindings == prune.KEEP_BINDINGS


class TestMakefileTargets:
    """`Makefile` と `setup.py` の名前が食い違わないこと。

    バンドル名は**両方に出てくる**——`setup.py` が `.app` の名前を決め、
    `Makefile` が `prune_bundle.py` にその道を渡す。片方だけ直すと、
    削る相手が見つからずビルドがそこで止まる。

    `make all` は通常版と軽量版を**一度に**作る（ユーザー要望 2026-08-28）。
    `app` / `app-lite` は先頭で `dist` ごと消すので、並べて呼ぶだけでは
    先に作ったほうが消える。
    """

    def makefile(self) -> str:
        return (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    def bundle_names(self) -> tuple[str, str]:
        import importlib
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            module = importlib.import_module("setup")
            return module.bundle_names(lite=False)[0], module.bundle_names(lite=True)[0]
        finally:
            sys.path.remove(str(PROJECT_ROOT))

    def test_allがある(self) -> None:
        assert "\nall:" in self.makefile()

    def test_allが両方作る(self) -> None:
        full, lite = self.bundle_names()
        body = self.makefile().split("\nall:")[1].split("\n\n")[0]
        assert full in body
        assert lite in body

    def test_allはdistを途中で消さない(self) -> None:
        """**2 つ目を作るときに 1 つ目を消さない。** `build` だけ消す。"""
        body = self.makefile().split("\nall:")[1].split("\n\n")[0]
        assert body.count("rm -rf build dist") <= 1

    def test_名前がsetupと揃っている(self) -> None:
        full, lite = self.bundle_names()
        text = self.makefile()
        assert f"dist/{full}.app" in text
        assert f"dist/{lite}.app" in text
