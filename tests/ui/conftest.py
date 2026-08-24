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


class _OfflineLLM:
    """繋がらない相手。試験の既定（本物の Ollama を叩かないため）。"""

    model = "test"

    def available(self) -> bool:
        return False

    def models(self) -> list[str]:
        return []

    def generate(self, prompt: str, *, on_chunk=None, should_stop=None) -> str:
        raise AssertionError("この試験は LLM を使わない（使うなら set_llm する）")


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
    # **外に繋ぎに行かせない。** 既定のままだと `available()` / `models()` が
    # 本物の Ollama（127.0.0.1:11434）を叩き、動かしている人の手元だけ
    # 結果が変わる（アシスタントの開閉と `Cmd+,` が実際にそうなっていた）。
    # 中身を見たいテストは自分で `set_llm` する
    widget.set_llm(_OfflineLLM())
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def activate(qtbot):
    """窓を**活きた状態**にする。メニューのショートカットを押す試験に要る。

    `QAction` の既定は `WindowShortcut` で、**活きていない窓には届かない**。
    表示しただけでは活性にならないことがあり、実測で `fired: []`（押しても
    何も起きない）になった。`Cmd+Shift+X` の取り違え（M-1）を見つけたのは
    この経路の試験なので、**素通りさせない**。
    """

    def go(window):
        window.show()
        qtbot.waitExposed(window)
        window.activateWindow()
        window.raise_()
        qtbot.waitUntil(window.isActiveWindow, timeout=2000)
        return window

    return go
