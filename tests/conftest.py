"""pytest 全体の共通設定。

**重要**: `QT_QPA_PLATFORM` は Qt を import する前に設定しないと効かない。
conftest.py はテストモジュールより先に読み込まれるため、ここが唯一の設定場所になる。
"""

import os
import tempfile

# ヘッドレス（CI / バックグラウンド実行）でも GUI テストが動くようにする。
# 実機の描画を見たいときだけ `QT_QPA_PLATFORM=cocoa uv run pytest` で上書きする。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# **テストが実ユーザーのホームを触らないようにする。**
# MainWindow は設定が無いと `~/Documents/HitofudeNotes` に vault を作る。
# ここを隔離しないと、テストを走らせるたびにユーザーの Documents が汚れる
# （実際に汚した）。`Path.home()` は HOME を見るので、import 時点で差し替える。
_SANDBOX_HOME = tempfile.mkdtemp(prefix="hitofude-test-home-")
os.environ["HOME"] = _SANDBOX_HOME

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

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
