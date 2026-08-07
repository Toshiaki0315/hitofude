"""pytest 全体の共通設定。

**重要**: `QT_QPA_PLATFORM` は Qt を import する前に設定しないと効かない。
conftest.py はテストモジュールより先に読み込まれるため、ここが唯一の設定場所になる。
"""

import os

# ヘッドレス（CI / バックグラウンド実行）でも GUI テストが動くようにする。
# 実機の描画を見たいときだけ `QT_QPA_PLATFORM=cocoa uv run pytest` で上書きする。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def project_root() -> Path:
    """リポジトリのルート。"""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """回帰テスト用サンプル `.md` の置き場（spec §10）。"""
    return PROJECT_ROOT / "tests" / "fixtures"
