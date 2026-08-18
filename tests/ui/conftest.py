"""UI テストの共通フィクスチャ。

同じ形の `window` が 19 ファイルに写されていた（約 218 行）。**設定の
作り方を変えるたびに 19 か所直す**ことになるので、ここへ 1 つ置く。

`show()` や最初のノートが要るファイルは、同じ名前で上書きすればよい
（pytest は下位で同名のフィクスチャを定義すると、上位のものを引数に
取れる）。差分だけがそのファイルに残る。
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from hitofude.config import Config
from hitofude.ui.main_window import MainWindow


@pytest.fixture
def config(tmp_path: Path, qapp) -> Config:
    """隔離した設定と保管フォルダ。

    **使い方のノートは置かせない**（`seeded` マーカーを先に立てる）。
    置かれると、一覧の件数を数えるテストが 1 件ずれる。
    """
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.Format.IniFormat)
    found = Config(settings)
    found.vault_path = tmp_path / "HitofudeNotes"
    marker = found.vault_path / ".hitofude" / "seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("test", encoding="utf-8")
    return found


@pytest.fixture
def window(qtbot, config: Config) -> MainWindow:
    """開いたままのウィンドウ。**表示はしない**（要るファイルで上書きする）。

    `close()` まで面倒を見る。閉じないと監視スレッドと索引の接続が残る。
    """
    widget = MainWindow(config)
    qtbot.addWidget(widget)
    yield widget
    widget.close()
