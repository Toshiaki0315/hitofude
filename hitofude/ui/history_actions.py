"""版の履歴の束（ADR-0023）。

`MainWindow` から切り出した協調オブジェクトで、**挙動は変えない**
（note_actions / save_controller と同じ「友達」の作り）。残す・見る・
戻す・掃除の判断はここに集め、`MainWindow` は薄く委譲する。

**今の時刻は `window._history_now()` から取る。** テストがそこを
インスタンス属性で差し替える（間引きの検査）ので、自前で持たない。
"""

import logging
from pathlib import Path

from hitofude.core.document import note_key
from hitofude.storage import history
from hitofude.ui.history_dialog import HistoryDialog

logger = logging.getLogger(__name__)


class HistoryActions:
    """版の残し方と戻し方。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window

    def root(self) -> Path:
        """版の置き場（ADR-0023）。管理フォルダの中で、一覧にも検索にも出ない。"""
        return history.store_root(self._window._vault.managed_dir)

    def prune(self) -> None:
        """多すぎる版と古すぎる版を捨てる。起動時に 1 回。"""
        history.prune(self.root(), now=self._window._history_now())

    def keep_version(self, text: str, *, force: bool = False) -> Path | None:
        """今の内容を 1 版として残す（ADR-0023）。保存の道から呼ぶ。

        **id で分ける。** 題名（＝ファイル名）は変わるが、front matter の
        ULID は変わらないので、名前を変えても履歴が途切れない。
        """
        window = self._window
        note = window._note
        if note is None:
            return None
        try:
            return history.keep(
                self.root(),
                note_key(note, window._vault.root),
                text,
                now=window._history_now(),
                force=force,
                interval_minutes=window._config.history_interval_minutes,
            )
        except OSError as error:
            # **履歴は付随物。** 本体（.md）は既に書けているのに、ここで
            # 例外を上げると保存の後処理（setModified / 索引更新 / 保存表示）
            # ごと壊れ、自動保存のたびに壊れ続ける（コードレビュー指摘）
            logger.warning("版を残せなかった: %s", error)
            return None

    def note_versions(self) -> list[history.Version]:
        """開いているノートの版（新しい順）。無ければ空。"""
        window = self._window
        note = window._note
        if note is None:
            return []
        return history.versions(self.root(), note_key(note, window._vault.root))

    def restore_version(self, version: history.Version) -> bool:
        """その版に戻す。戻せたら True。

        **戻す前に今の内容を 1 版残す。** 「やっぱり戻す前がよかった」と
        言えるようにする（取り消せない操作を増やさない）。
        """
        window = self._window
        if window._note is None:
            return False
        try:
            text = version.read()
        except OSError:
            logger.warning("版を読めなかった: %s", version.path)
            return False

        self.keep_version(window._editor.toPlainText(), force=True)
        window._editor.setPlainText(text)
        window.flush()
        window.notify(f"{version.saved_at:%Y-%m-%d %H:%M} の版に戻しました")
        return True

    def build_history_dialog(self) -> HistoryDialog | None:
        """版の履歴の画面を作る。ノートを開いていなければ `None`。

        **開く前に今の内容を書く。** 打ちかけのまま開くと、いちばん新しい
        版と画面の内容が食い違う。
        """
        window = self._window
        if window._note is None:
            return None
        window.flush()
        dialog = HistoryDialog(self.note_versions(), window)
        dialog.restore_requested.connect(self.restore_version)
        return dialog

    def show_history(self) -> None:
        """版の履歴を開く（ADR-0023）。**キーは付けていない**——
        `Cmd+Shift+H` はエディタがマーカーに使っている（2026-08-23 に取り下げ、
        2026-08-25 に `編集 → 書式 → マーカー` へ正式に付いた）。
        """
        dialog = self.build_history_dialog()
        if dialog is None:
            self._window.notify("ノートを開いてから使ってください")
            return
        dialog.exec()
        dialog.deleteLater()
