"""py2app による macOS アプリのビルド（spec §8.1）。

    make app          # dist/Hitofude.app を作る

py2app を選んでいる理由（§8.1）: PyInstaller の `--onedir` ビルドには
PySide6 の QtNetwork / QtSvg フレームワークの署名が不正になり公証に失敗する
既知の不具合がある。py2app は macOS 専用ゆえに Framework バンドルの構造を
正しく扱いやすい。

署名と公証（§8.2）は Apple Developer ID が要るため、このファイルの範囲外。
署名しなくても**自分の Mac では動く**が、他の Mac へ配ると Gatekeeper に
止められる。
"""

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


APP = ["hitofude/__main__.py"]

# PySide6 は巨大なので、使わないモジュールを落とさないと 1GB 級になる（§8.1）
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtCharts",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
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
    "iconfile": str(ROOT / "resources" / "Hitofude.icns"),
    "packages": ["PySide6", "shiboken6", "markdown_it", "yaml", "watchdog", "hitofude"],
    "includes": ["sqlite3", "mdurl"],
    "excludes": EXCLUDES,
    "plist": {
        "CFBundleName": "Hitofude",
        "CFBundleDisplayName": "Hitofude",
        "CFBundleIdentifier": "app.hitofude.editor",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
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

setup(
    name="Hitofude",
    app=APP,
    options={"py2app": OPTIONS},
    distclass=_Py2appDistribution,
)
