"""変換中の静かな読み直しを止める（ユーザー報告 2026-08-27）。

日本語の変換を未確定のまま置いていると、未確定の文字が見えなくなり、
Enter（確定）で現れる——という報告。再現手順は無いが、症状と一致する
経路が 1 本だけある:

    保存（800ms のデバウンス）→ 自分の書き込みのエコーが抑制窓
    （1.5 秒）を超えて届く → 未編集扱いで _reload_open_note →
    **変換中に setPlainText** → プリエディットが古い文書に取り残されて
    描かれない → 確定はいまの文書に入るので文字が現れる

R6（変換中は特殊処理を無効化）の穴。読み直しは変換が終わるまで待たせる。
"""

import pytest
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.gui


def compose(editor, text: str) -> None:
    QApplication.sendEvent(editor, QInputMethodEvent(text, []))


def commit(editor, text: str) -> None:
    event = QInputMethodEvent("", [])
    event.setCommitString(text)
    QApplication.sendEvent(editor, event)


class TestCompositionEnded:
    def test_確定で合図が飛ぶ(self, window, qtbot) -> None:
        window.new_note()
        editor = window.editor
        with qtbot.waitSignal(editor.composition_ended, timeout=500):
            compose(editor, "にほんご")
            commit(editor, "日本語")

    def test_変換中は飛ばない(self, window, qtbot) -> None:
        window.new_note()
        editor = window.editor
        fired = []
        editor.composition_ended.connect(lambda: fired.append(True))
        compose(editor, "に")
        compose(editor, "にほ")
        assert fired == []


class TestReloadDeferred:
    def make_disk_note(self, window):
        """ディスク側だけ書き換えた Note を作る。"""
        path = window._note.path
        payload = window._note.text + "\n外部の追記\n"
        path.write_text(payload, encoding="utf-8")
        return window._vault.read(path)

    def test_変換中は読み直さない(self, window) -> None:
        window.new_note()
        editor = window.editor
        before = editor.toPlainText()
        compose(editor, "にほんご")

        window._reload_open_note(self.make_disk_note(window))

        assert editor.toPlainText() == before, "変換中に setPlainText している"

    def test_取り消しで終われば読み直す(self, window) -> None:
        """未確定を捨てた（Esc）なら本文は無傷 → 待たせた読み直しを流す。"""
        window.new_note()
        editor = window.editor
        compose(editor, "にほんご")
        disk = self.make_disk_note(window)
        window._reload_open_note(disk)

        compose(editor, "")  # 取り消し（確定文字なし）

        assert "外部の追記" in editor.toPlainText()

    def test_確定したら読み直しは捨てる(self, window) -> None:
        """確定で本文が変わった。読み直すと**打った文字を失う**ので捨てて、
        次の保存の競合裁きに任せる。"""
        window.new_note()
        editor = window.editor
        compose(editor, "にほんご")
        window._reload_open_note(self.make_disk_note(window))

        commit(editor, "日本語")

        assert "日本語" in editor.toPlainText()
        assert "外部の追記" not in editor.toPlainText()

    def test_変換していなければ今まで通り(self, window) -> None:
        window.new_note()
        window._reload_open_note(self.make_disk_note(window))
        assert "外部の追記" in window.editor.toPlainText()
