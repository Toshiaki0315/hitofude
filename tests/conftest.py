"""pytest 全体の共通設定。

**重要**: `QT_QPA_PLATFORM` は Qt を import する前に設定しないと効かない。
conftest.py はテストモジュールより先に読み込まれるため、ここが唯一の設定場所になる。
"""

import os
import tempfile

# ヘッドレス（CI / バックグラウンド実行）でも GUI テストが動くようにする。
# 実機の描画を見たいときだけ `QT_QPA_PLATFORM=cocoa uv run pytest` で上書きする。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QtWebEngine（Mermaid の描画）も offscreen で動かす。sandbox はヘッドレスで
# 立ち上がらないことがあるので切る。GPU も無い前提で描かせる
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

# **テストが実ユーザーのホームを触らないようにする。**
# MainWindow は設定が無いと `~/Documents/HitofudeNotes` に vault を作る。
# ここを隔離しないと、テストを走らせるたびにユーザーの Documents が汚れる
# （実際に汚した）。`Path.home()` は HOME を見るので、import 時点で差し替える。
_SANDBOX_HOME = tempfile.mkdtemp(prefix="hitofude-test-home-")
os.environ["HOME"] = _SANDBOX_HOME

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# QtWebEngine は QApplication より先に import されている必要がある。
# ここ（すべてのテストモジュールより先に読まれる場所）で済ませる
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
import PySide6.QtWebEngineWidgets  # noqa: E402, F401

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# QSettings も隔離する。既定では ~/Library/Preferences に書き込むため、
# 設定を書くテストが実ユーザーの環境を書き換えてしまう。
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
    QSettings.setPath(QSettings.Format.IniFormat, scope, _SANDBOX_HOME)


SANDBOX_HOME = Path(_SANDBOX_HOME)


@pytest.fixture(scope="session")
def sandbox_home() -> Path:
    """テスト中の擬似ホーム。実ユーザーのホームではない。"""
    return SANDBOX_HOME


@pytest.fixture(scope="session")
def project_root() -> Path:
    """リポジトリのルート。"""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """回帰テスト用サンプル `.md` の置き場（spec §10）。"""
    return PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def png_bytes():
    """PNG のバイト列を作る。画像まわりのテストで使い回す（タスク A-2 系）。

    **受け皿は変数で保持すること。** `QBuffer(QByteArray())` と書くと
    一時オブジェクトが即座に回収され、解放済みの領域へ書いて SIGSEGV になる
    （実際にテストがプロセスごと落ちた）。
    """
    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QColor, QImage

    def make(width: int = 100, height: int = 50, color: str = "red") -> bytes:
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        storage = QByteArray()
        buffer = QBuffer(storage)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return bytes(storage)

    return make


@pytest.fixture
def write_png(png_bytes):
    """PNG をその場所へ書く。親フォルダも作る。"""

    def make(path: Path, width: int = 100, height: int = 50, color: str = "red") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(width, height, color))
        return path

    return make


@pytest.fixture(scope="session", autouse=True)
def _release_clipboard():
    """終了する前にクリップボードを空にする。

    **これを怠るとテストの最後に segfault で落ちる（exit 139）。**
    Python 側で作った `QMimeData` をクリップボードに載せたまま終了すると、
    Qt の後片付け（C++ の静的デストラクタ）が、既に終了した Python
    インタプリタへ触りに行く。実測でも `QMimeData` を載せて終了する
    プログラムは **20 回中 20 回**落ちた。

    **offscreen のときだけ。** 実機（cocoa）では落ちない（5 回中 0 回）ので、
    アプリ側の問題ではない。`cocoa` で走らせた人の**本物のクリップボードを
    消さない**ために、ここで環境を見て分ける。

    全件流すと出たり出なかったりしたのは、後から走るテストが別の中身で
    上書きすると落ちなくなるため。`tests/editor/test_exporter.py` を
    単独で流すと必ず再現する。
    """
    yield

    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        return
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.clipboard().clear()
