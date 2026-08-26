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
# QtPdf は PDF の取り込み（F-2。**削っていて `.app` で壊れていた**。
# ユーザー依頼のサイズ削減レビュー 2026-08-26 で発覚）、
# QtDBus と QtNetwork は QtGui/QtWidgets が動的に必要とする。
KEEP_FRAMEWORKS = {
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtPrintSupport",
    "QtPdf",
    "QtDBus",
    "QtNetwork",
    "QtSvg",
}

# Mermaid の図（ADR-0021 / 0030）。`QtWebEngineWidgets` が動くのに要るものを
# **otool -L の実測で**並べた。Chromium 本体だけで 572MB あるが、同梱しないと
# `.app` では図が出ない（ユーザーの選択 2026-08-26）
WEB_ENGINE_FRAMEWORKS = {
    "QtWebEngineCore",
    "QtWebEngineWidgets",
    "QtWebEngineQuick",  # qml の QtWebEngine モジュールが読む
    "QtWebChannel",
    "QtWebChannelQuick",
    "QtQml",
    "QtQmlMeta",
    "QtQmlModels",
    "QtQmlWorkerScript",
    "QtQuick",
    "QtQuickWidgets",
    "QtOpenGL",
    "QtPositioning",
}
KEEP_FRAMEWORKS |= WEB_ENGINE_FRAMEWORKS

# 残す **Python 束縛**（`Qt*.abi3.so`）。フレームワーク（dyld が読む
# C++ 側）とは別で、Python から import するものだけ要る。実測は
# `import PySide6.QtWebEngineWidgets` 後の sys.modules ＋ hitofude の
# import 文（tests/test_packaging.py が突き合わせる）。
# QtOpenGL や QtQuick は C++ 側だけ要り、束縛は 15MB のただの重り
KEEP_BINDINGS = {
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtNetwork",
    "QtPrintSupport",
    "QtPdf",
    "QtSvg",
    "QtWebChannel",
    "QtWebEngineCore",
    "QtWebEngineWidgets",
}

# PySide6 が同梱する開発道具。アプリの実行には要らない（計 53MB）。
# lupdate（39MB）だけで Chromium 以外のどの部品より大きい
PYSIDE_TOOLS = [
    "Assistant.app",
    "Designer.app",
    "Linguist.app",
    "QtAsyncio",
    "balsam",
    "balsamui",
    "doc",
    "glue",
    "include",
    "lrelease",
    "lupdate",
    "qmlformat",
    "qmllint",
    "qmlls",
    "qsb",
    "svgtoqml",
    "typesystems",
]

# WebEngine の Python 束縛。軽量版（--lite）ではこれも削る
WEB_ENGINE_BINDINGS = {"QtWebChannel", "QtWebEngineCore", "QtWebEngineWidgets"}


def keep_sets(*, lite: bool) -> tuple[set[str], set[str]]:
    """残すもの（フレームワーク, Python 束縛）。

    軽量版（ユーザー要望 2026-08-26）は Mermaid を諦めて WebEngine
    （Chromium 約 300MB）ごと削る。図が出ない以外は同じアプリで、
    数式は ziamath + QtSvg なので残る。アプリ側は QtWebEngine が
    無ければ図を諦めて動く（ADR-0030 の preload_web_engine）。
    """
    if not lite:
        return set(KEEP_FRAMEWORKS), set(KEEP_BINDINGS)
    return (
        KEEP_FRAMEWORKS - WEB_ENGINE_FRAMEWORKS,
        KEEP_BINDINGS - WEB_ENGINE_BINDINGS,
    )


# Chromium が読む翻訳。**使う言語だけ残す**（全部で 38MB、2 つなら 1MB 弱）
KEEP_LOCALES = {"ja.pak", "en-US.pak"}

# 残す CPU。**Apple Silicon 専用にする**（ADR-0030）。wheel の Qt は
# universal（x86_64 + arm64）で、削ると全体がほぼ半分になる
KEEP_ARCH = "arm64"

# 残す Qt プラグイン。platforms が無いとウィンドウを作れず即座に落ちる
KEEP_PLUGINS = {"platforms", "styles", "imageformats", "printsupport", "iconengines"}

# 丸ごと消してよいディレクトリ。qml（QML のモジュール置き場）は
# QWebEngineView（Widgets）には要らない——消しても図が描けることを
# バンドルの中で実測した（2026-08-26）。metatypes は QML ツール用の
# メタ情報で実行時には読まれない
DROP_DIRS = [
    "Qt/translations",
    "Qt/libexec",
    "Qt/resources",
    "Qt/qml",
    "Qt/metatypes",
    "scripts",
    "examples",
]


def _pyside_root(app: Path) -> Path:
    candidates = list(app.glob("Contents/Resources/lib/python*/PySide6"))
    if not candidates:
        raise SystemExit(f"PySide6 が見つからない: {app}")
    return candidates[0]


def prune(app: Path, *, lite: bool = False) -> tuple[int, int]:
    before = _size(app)
    root = _pyside_root(app)
    keep_frameworks, keep_bindings = keep_sets(lite=lite)

    for relative in DROP_DIRS:
        shutil.rmtree(root / relative, ignore_errors=True)

    for name in PYSIDE_TOOLS:
        target = root / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)

    lib = root / "Qt" / "lib"
    if lib.is_dir():
        for framework in lib.glob("*.framework"):
            if framework.stem not in keep_frameworks:
                shutil.rmtree(framework, ignore_errors=True)
        # QtMultimedia（削除済み）の ffmpeg。WebEngine は自前の
        # コーデックを静的に持っていて、これは誰も読まない（36MB。
        # 元は symlink の組が py2app で実体の複製になっている）
        for library in list(lib.glob("libav*")) + list(lib.glob("libsw*")):
            library.unlink(missing_ok=True)

    plugins = root / "Qt" / "plugins"
    if plugins.is_dir():
        for directory in plugins.iterdir():
            if directory.is_dir() and directory.name not in KEEP_PLUGINS:
                shutil.rmtree(directory, ignore_errors=True)

    # Python から import しない束縛（QtOpenGL 等の .so）も落とす
    for module in root.glob("Qt*.abi3.so"):
        if module.name.split(".")[0] not in keep_bindings:
            module.unlink(missing_ok=True)

    for junk in ("*.pyi", "py.typed", "*.debug"):
        for path in root.rglob(junk):
            path.unlink(missing_ok=True)

    _prune_web_engine(root)
    _thin(app)
    _sign_mach_o(app)
    _resign(app)
    return before, _size(app)


def _prune_web_engine(root: Path) -> None:
    """Chromium の付属物のうち、図を描くのに要らないものを落とす。

    翻訳は 100 言語ぶんで 38MB。開発者ツールの資源（10MB）はページを
    開いて調べるためのもので、絵にするだけなら要らない。
    """
    resources = root / "Qt" / "lib" / "QtWebEngineCore.framework" / "Versions" / "A" / "Resources"
    if not resources.is_dir():
        return

    locales = resources / "qtwebengine_locales"
    if locales.is_dir():
        for pak in locales.glob("*.pak"):
            if pak.name not in KEEP_LOCALES:
                pak.unlink(missing_ok=True)

    (resources / "qtwebengine_devtools_resources.pak").unlink(missing_ok=True)
    # V8 のスナップショットは CPU ごとに 1 つ。残す CPU のぶんだけ置く
    for snapshot in resources.glob("v8_context_snapshot.*.bin"):
        if f".{KEEP_ARCH}." not in snapshot.name:
            snapshot.unlink(missing_ok=True)


def _thin(app: Path) -> None:
    """universal のバイナリを `KEEP_ARCH` だけに削る（ADR-0030）。

    wheel の Qt は x86_64 と arm64 の両方を含む。片方だけにすると
    **全体がほぼ半分**になる（Chromium 本体は 448MB → 約半分）。
    引き換えに Intel Mac では動かなくなる（ユーザーの選択 2026-08-26）。
    """
    thinned = 0
    for path in app.rglob("*"):
        if not _is_mach_o(path):
            continue
        archs = subprocess.run(
            ["lipo", "-archs", str(path)], capture_output=True, text=True, check=False
        ).stdout.split()
        if KEEP_ARCH not in archs or len(archs) < 2:
            continue  # 既に 1 つ、または残す CPU が入っていない
        path.chmod(path.stat().st_mode | 0o200)
        subprocess.run(
            ["lipo", str(path), "-thin", KEEP_ARCH, "-output", str(path)],
            capture_output=True,
            check=True,
        )
        thinned += 1
    print(f"  {KEEP_ARCH} だけに削った: {thinned} 個")


def _sign_mach_o(app: Path) -> None:
    """バンドルの中の実行コードを 1 つずつ署名し直す。

    **`codesign --deep` では届かない。** PySide6 が持ち込む Qt の
    フレームワークは `Contents/Resources/` の下——macOS から見れば
    「入れ子のコード」ではなく**ただの資源**なので、封をするときに
    ハッシュは取られるが、中身の署名は触られない。

    `lipo` で CPU を削ると各バイナリの署名が合わなくなり、dyld が
    読み込む瞬間に **SIGKILL (Code Signature Invalid)** で殺す
    （ユーザー報告 2026-08-26 の crash report で確認）。深いものから
    順に署名し直す。
    """
    targets = sorted(
        (path for path in app.rglob("*") if _is_mach_o(path)),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    failed = 0
    for path in targets:
        path.chmod(path.stat().st_mode | 0o200)
        if not _sign(path):
            failed += 1
    print(f"  署名し直した: {len(targets) - failed} 個" + (f"（失敗 {failed}）" if failed else ""))


def _is_mach_o(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    found = subprocess.run(
        ["lipo", "-archs", str(path)], capture_output=True, text=True, check=False
    )
    return found.returncode == 0


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
    parser.add_argument(
        "--lite",
        action="store_true",
        help="Mermaid を諦めて WebEngine ごと削る軽量版（数式は残る）",
    )
    args = parser.parse_args()

    if not args.app.is_dir():
        sys.exit(f"見つからない: {args.app}")

    before, after = prune(args.app, lite=args.lite)
    print(
        f"{args.app.name}: {before / 1024 / 1024:,.0f} MB → {after / 1024 / 1024:,.0f} MB "
        f"（{(1 - after / before) * 100:.0f}% 削減）"
    )


if __name__ == "__main__":
    main()
