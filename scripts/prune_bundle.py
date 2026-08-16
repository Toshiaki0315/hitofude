"""ビルドしたアプリから使わない Qt を削る（spec §8.1）。

    uv run python scripts/prune_bundle.py dist/Hitofude.app

py2app の `excludes` は **Python モジュールにしか効かない**。PySide6 が同梱する
Qt のフレームワーク本体はパッケージごと丸ごとコピーされるため、
`QtWebEngineCore`（単体で 500MB 超）まで入って 1GB を軽く超える。

そこで「使うものだけ残す」方式で後から削る。除外リストを育てるより、
残すものを明示するほうが取りこぼしがない。

削るとバンドルの封印（Sealed Resources）が壊れるので、最後にアドホック署名を
やり直す。これをしないと macOS が起動を拒む。
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Widgets だけで作っているアプリが要る Qt。QtPrintSupport は PDF 出力（§9 Phase 6）、
# QtDBus と QtNetwork は QtGui/QtWidgets が動的に必要とする。
KEEP_FRAMEWORKS = {
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtPrintSupport",
    "QtDBus",
    "QtNetwork",
    "QtSvg",
}

# 残す Qt プラグイン。platforms が無いとウィンドウを作れず即座に落ちる
KEEP_PLUGINS = {"platforms", "styles", "imageformats", "printsupport", "iconengines"}

# 丸ごと消してよいディレクトリ
DROP_DIRS = ["Qt/qml", "Qt/translations", "Qt/libexec", "Qt/resources", "scripts", "examples"]


def _pyside_root(app: Path) -> Path:
    candidates = list(app.glob("Contents/Resources/lib/python*/PySide6"))
    if not candidates:
        raise SystemExit(f"PySide6 が見つからない: {app}")
    return candidates[0]


def prune(app: Path) -> tuple[int, int]:
    before = _size(app)
    root = _pyside_root(app)

    for relative in DROP_DIRS:
        shutil.rmtree(root / relative, ignore_errors=True)

    lib = root / "Qt" / "lib"
    if lib.is_dir():
        for framework in lib.glob("*.framework"):
            if framework.stem not in KEEP_FRAMEWORKS:
                shutil.rmtree(framework, ignore_errors=True)

    plugins = root / "Qt" / "plugins"
    if plugins.is_dir():
        for directory in plugins.iterdir():
            if directory.is_dir() and directory.name not in KEEP_PLUGINS:
                shutil.rmtree(directory, ignore_errors=True)

    # 使わない拡張モジュール本体（QtQuick 等の .so）も落とす
    for module in root.glob("Qt*.abi3.so"):
        if module.name.split(".")[0] not in KEEP_FRAMEWORKS:
            module.unlink(missing_ok=True)

    for junk in ("*.pyi", "py.typed", "*.debug"):
        for path in root.rglob(junk):
            path.unlink(missing_ok=True)

    _resign(app)
    return before, _size(app)


def _resign(app: Path) -> None:
    """アドホック署名をやり直す。

    ファイルを消すと Sealed Resources が合わなくなり、macOS が起動を拒む。
    Developer ID での署名（§8.2）とは別物で、これは配布用ではない。

    **先に壊れたライブラリを直す。** py2app は wheel が持ち込む署名済みの
    `.dylib` から署名の中身だけを外し、目印（`LC_CODE_SIGNATURE`）を残す
    ことがある。そのままだと `codesign` が
    "main executable failed strict validation" で止まる
    （Pillow の `liblzma.5.dylib` で踏んだ）。
    """
    for library in sorted(app.rglob("*.dylib")):
        _repair_signature(library)

    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        check=True,
        capture_output=True,
    )


def _repair_signature(library: Path) -> None:
    """署名し直せない `.dylib` を、書き直して署名できる形に戻す。

    `install_name_tool` に**今と同じ id を入れ直す**と Mach-O が組み直され、
    壊れた署名の跡が消える。中身は変わらない。
    """
    if _sign(library):
        return

    identity = (
        subprocess.run(["otool", "-D", str(library)], capture_output=True, text=True)
        .stdout.strip()
        .split("\n")[-1]
    )
    if not identity:
        return

    library.chmod(library.stat().st_mode | 0o200)
    subprocess.run(
        ["install_name_tool", "-id", identity, str(library)],
        capture_output=True,
        check=False,
    )
    if not _sign(library):
        print(f"  署名できなかった: {library.name}")


def _sign(target: Path) -> bool:
    result = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(target)],
        capture_output=True,
    )
    return result.returncode == 0


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="アプリバンドル（dist/Hitofude.app）")
    args = parser.parse_args()

    if not args.app.is_dir():
        sys.exit(f"見つからない: {args.app}")

    before, after = prune(args.app)
    print(
        f"{args.app.name}: {before / 1024 / 1024:,.0f} MB → {after / 1024 / 1024:,.0f} MB "
        f"（{(1 - after / before) * 100:.0f}% 削減）"
    )


if __name__ == "__main__":
    main()
