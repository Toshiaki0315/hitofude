"""開発環境そのものの検証（タスク 0-A-6）。

依存の入れ忘れやバージョン不一致を、実装のテストより先に落とすためのもの。
"""

import importlib
import sys

import pytest


def test_python_バージョンは312以上である() -> None:
    # spec §4: `match` 文と型パラメータ構文を使うため 3.12 が下限
    assert sys.version_info >= (3, 12)


@pytest.mark.parametrize(
    "module_name",
    [
        "PySide6.QtWidgets",
        "markdown_it",
        "yaml",
        "watchdog",
        "sqlite3",
    ],
)
def test_必須依存がimportできる(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None


def test_sqliteがFTS5のtrigramトークナイザを持つ() -> None:
    """spec §7.3: 日本語全文検索は trigram に依存する。無ければ設計が成立しない。"""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='trigram')")
    finally:
        conn.close()


def test_hitofudeパッケージがimportできる() -> None:
    import hitofude

    assert hitofude.__version__
