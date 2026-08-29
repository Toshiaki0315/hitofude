"""py2app による macOS アプリのビルド（spec §8.1）。

    make app          # dist/OboeGaki.app を作る
    make app-lite     # dist/OboeGakiLite.app（Mermaid なし）

py2app を選んでいる理由（§8.1）: PyInstaller の `--onedir` ビルドには
PySide6 の QtNetwork / QtSvg フレームワークの署名が不正になり公証に失敗する
既知の不具合がある。py2app は macOS 専用ゆえに Framework バンドルの構造を
正しく扱いやすい。

署名と公証（§8.2）は Apple Developer ID が要るため、このファイルの範囲外。
署名しなくても**自分の Mac では動く**が、他の Mac へ配ると Gatekeeper に
止められる。
"""

import os
from pathlib import Path

from setuptools import setup
from setuptools.dist import Distribution

ROOT = Path(__file__).resolve().parent


class _Py2appDistribution(Distribution):
    """`install_requires` を落とした Distribution。

    setuptools は `pyproject.toml` の `[project] dependencies` を
    `install_requires` として取り込むが、**py2app 0.28 はこれを受け付けず
    `install_requires is no longer supported` で止まる**。
    依存の解決は uv が済ませているのでビルド時には要らない。
    """

    def parse_config_files(self, *args: object, **kwargs: object) -> None:
        super().parse_config_files(*args, **kwargs)
        self.install_requires = []


LITE_ENV = "HITOFUDE_LITE"
"""軽量版として組むかどうかの合図（`make run-lite` と同じ名前を使う）。"""


def building_lite() -> bool:
    return os.environ.get(LITE_ENV) == "1"


def icon_file(*, lite: bool) -> Path:
    """使う `.icns`。軽量版は右下に小さく `Lite` が入った絵（ユーザー要望）。"""
    name = "OboeGakiLite.icns" if lite else "OboeGaki.icns"
    return ROOT / "resources" / name


def bundle_names(*, lite: bool) -> tuple[str, str]:
    """`(.app の名前, Finder に出る名前)`（ユーザー要望 2026-08-28）。

    **表示名も変える。** Finder が並べるのは `CFBundleDisplayName` なので、
    ファイル名だけ変えても**どちらも「覚書」に見えて区別が付かない**。

    **バンドル ID は分けない**（呼ぶ側で固定）。分けると QSettings の
    保存先も分かれ、軽量版で起動したときに設定も保管フォルダの記憶も
    別物になる。これは「同じアプリの軽い作り」であって別のアプリではない。
    """
    if lite:
        return "OboeGakiLite", "覚書Lite"
    return "OboeGaki", "覚書"


APP = ["hitofude/__main__.py"]

# PySide6 は巨大なので、使わないモジュールを落とさないと 1GB 級になる（§8.1）
EXCLUDES = [
    # **QtWebEngine は落とさない**（ADR-0030）。Mermaid の図（ADR-0021）が
    # これで描かれる。落としていたせいで `.app` が起動しなかった
    # （`app.py` の先読み import が ModuleNotFoundError。ユーザー報告 2026-08-26）
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtQuick3D",
    "PySide6.QtCharts",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "tkinter",
    "test",
    "unittest",
    "pytest",
]

OPTIONS = {
    # True にすると Carbon 依存で Apple Silicon で問題が出る（§8.1）
    "argv_emulation": False,
    # **シンボルを削らない。** 既定の strip は wheel が持ち込む署名済みの
    # ライブラリを壊し、`codesign` が "main executable failed strict
    # validation" で止まる（Pillow の liblzma で実際に踏んだ。341KB→184KB に
    # 削られて署名の領域が合わなくなる）。配布には署名が要るので削らない
    "strip": False,
    "iconfile": str(ROOT / "resources" / "OboeGaki.icns"),
    "packages": [
        "PySide6",
        "shiboken6",
        "markdown_it",
        "mdit_py_plugins",
        "pygments",
        "latex2mathml",
        # **数式（ADR-0020）。** `ziamath` はフォントを同梱していて、
        # 実行時に `importlib.resources` で読む。`packages` に入れないと
        # py2app は `.py` だけ拾って `fonts/` を置いていかず、`.app` の中で
        # `No module named 'ziamath.fonts'` で**起動ごと死ぬ**
        # （ユーザー報告 2026-08-26）
        "ziamath",
        "ziafont",
        "pypdf",
        "yaml",
        "watchdog",
        "hitofude",
        # **PowerPoint の読み書き（F 群）。** `packages` に入れないと py2app は
        # PIL の `.so` だけ拾って本体を入れず、`.app` の中で
        # `from PIL import Image` が失敗する（ビルドして確かめた）
        "pptx",
        # **Word の書き出し（U-5）。** pptx と同じく lxml に乗っている
        "docx",
        "PIL",
        "lxml",
    ],
    # **文字の読み取りの道具を忘れない**（ADR-0027）。`make ocr-tool` が
    # `resources/bin/hitofude-ocr` に作る。`packages` の "hitofude" ごと
    # 入るが、**署名の対象が 1 つ増える**（`codesign` を実行ファイルにも当てる）
    "includes": ["sqlite3", "mdurl"],
    "excludes": EXCLUDES,
    "plist": {
        "CFBundleName": "OboeGaki",
        "CFBundleDisplayName": "覚書",
        "CFBundleIdentifier": "app.oboegaki.editor",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        # **対応する言語を申告する（ユーザー指摘）。** ファイルを選ぶ画面や
        # 印刷パネルは macOS が描くので、こちらが何も言わないと英語のまま出る
        # （Finder は日本語なのに「Open / Cancel / New Folder」と並ぶ）。
        # ここに書いた言語と、利用者の優先言語の重なりで表示言語が決まる
        "CFBundleDevelopmentRegion": "ja",
        "CFBundleLocalizations": ["ja", "en"],
        # アプリ自身の文言（日本語）と、OS が描く部分の言語が違ってもよい
        "CFBundleAllowMixedLocalizations": True,
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026 Toshiaki Nomura",
        # 既定の保管フォルダが ~/Documents なので、初回起動で許可を求められる
        "NSDocumentsFolderUsageDescription": "ノートの保管フォルダを読み書きします。",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Markdown Document",
                "CFBundleTypeExtensions": ["md", "markdown"],
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
            }
        ],
    },
}

if __name__ == "__main__":
    # **軽量版だけ名前を差し替える。** ここより上は素の値のままにしておく
    # （`tests/test_packaging.py` が AST で literal を読むため）
    name, display = bundle_names(lite=building_lite())
    OPTIONS["plist"]["CFBundleName"] = name
    OPTIONS["plist"]["CFBundleDisplayName"] = display
    OPTIONS["iconfile"] = str(icon_file(lite=building_lite()))

    setup(
        name=name,
        app=APP,
        options={"py2app": OPTIONS},
        distclass=_Py2appDistribution,
    )
