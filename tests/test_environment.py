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


class TestIsolation:
    """テストが実ユーザーの環境を触らないことの検査（回帰テスト）。

    `MainWindow` は設定が無いと `~/Documents/HitofudeNotes` に vault を作る。
    ここが壊れると、テストを走らせるたびにユーザーの Documents が汚れる。
    """

    def test_ホームが隔離されている(self, sandbox_home) -> None:
        from pathlib import Path

        assert Path.home() == sandbox_home
        assert "hitofude-test-home-" in str(Path.home())

    def test_QSettingsの保存先も隔離されている(self, qapp, sandbox_home) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings(QSettings.Scope.UserScope, "テスト組織", "テストアプリ")
        assert str(sandbox_home) in settings.fileName()

    def test_設定なしのvaultが擬似ホームを指す(self, qapp, sandbox_home) -> None:
        from hitofude.config import Config

        assert Config().vault_path.is_relative_to(sandbox_home)

    def test_旧ドメインも隔離されている(self, qapp, sandbox_home) -> None:
        """改名（ADR-0032）で入った引っ越しの読み口。

        `QSettings(組織, アプリ)` と書くと macOS では常にネイティブ
        （plist）で開き、擬似ホームへの差し替えを**素通りする**。
        `vault_path` の検査だけでは、実ユーザーの旧設定を持つ機械でしか
        落ちない（＝CI は緑のまま）ので、ここで直に見る。
        """
        from PySide6.QtCore import QSettings

        from hitofude.config import legacy_settings

        opened = legacy_settings()
        assert opened.format() == QSettings.defaultFormat()
        assert str(sandbox_home) in opened.fileName()
        assert opened.allKeys() == [], "実ユーザーの設定が見えている"
