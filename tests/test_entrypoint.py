"""エントリポイントのテスト（タスク 0-B-4）。

`app.exec()` を実際に呼ぶとイベントループが止まらないので、配線だけを検証する。
"""

import pytest

from hitofude import __main__ as entrypoint

pytestmark = pytest.mark.gui


def test_mainがウィンドウを表示してイベントループの戻り値を返す(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[object] = []

    monkeypatch.setattr(qapp, "exec", lambda: 0)
    monkeypatch.setattr(
        entrypoint.MainWindow,
        "show",
        lambda self: shown.append(self),
    )

    assert entrypoint.main([]) == 0
    assert len(shown) == 1, "ウィンドウが 1 度だけ show() される"


def test_mainはexecの終了コードをそのまま返す(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qapp, "exec", lambda: 3)
    monkeypatch.setattr(entrypoint.MainWindow, "show", lambda self: None)

    assert entrypoint.main([]) == 3
