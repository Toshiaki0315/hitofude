"""保存フローの束（spec §7.4 / §7.5 / §9 Phase 6）。

デバウンス保存・即時フラッシュ・競合解決・タイトル追従の改名・
未保存内容の退避（クラッシュ対策の保険）を 1 か所に集める。
`MainWindow` から切り出した協調オブジェクトで、**挙動は変えない**
（export_actions / search_actions と同じ「友達」の作り）。

Debouncer と退避の状態はここが持ち、`MainWindow` は同じオブジェクトへの
別名（`_debouncer` / `_recovery_root`）を保持する。ノート切り替えや
外部変更の判定など、保存の外からも pending を見る箇所が多いため。
"""

import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer

from hitofude.core.document import Note
from hitofude.storage import autosave
from hitofude.storage.autosave import Debouncer
from hitofude.storage.vault import ConflictAction, check_conflict, keep_both_path, sanitize_filename
from hitofude.ui.conflict_dialog import ConflictDialog, Resolution

logger = logging.getLogger(__name__)

SAVE_TICK_MS = 200
STASH_INTERVAL_SECONDS = 2.0


class SaveController:
    """保存のタイミングと競合の裁き。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window
        self.debouncer = Debouncer()
        self.recovery_root = autosave.recovery_root(window._vault.root)
        self._last_stash = 0.0

        self.timer = QTimer(window)
        self.timer.setInterval(SAVE_TICK_MS)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start()

    # ------------------------------------------------------------- 見張り

    def on_tick(self) -> None:
        if self.debouncer.due():
            self.flush()
            return
        if self.debouncer.pending:
            self._maybe_stash()

    def _maybe_stash(self) -> None:
        """未保存の内容を退避する（spec §9 Phase 6）。

        毎チック書くと 1 秒に 5 回ディスクを叩くので、間隔を空ける。
        通常は 800ms で保存されるのでここまで来ることは少ないが、
        保存できない状態（競合の未解決など）が続いたときの保険になる。
        """
        window = self._window
        now = time.monotonic()
        if window._note is None or now - self._last_stash < STASH_INTERVAL_SECONDS:
            return
        self._last_stash = now
        try:
            autosave.stash(self.recovery_root, window._note.path, window._editor.toPlainText())
        except OSError:
            logger.warning("未保存内容の退避に失敗した", exc_info=True)

    # ------------------------------------------------------------- 保存

    def flush(self, *, interactive: bool = True) -> None:
        """未保存の内容を今すぐ書く（§7.4 の即時フラッシュ）。

        `interactive=False` のときは競合してもダイアログを出さない。
        終了処理から呼ぶときに使う。**`closeEvent` の中でモーダルを開くと
        アプリが終了できなくなる**（実装中に踏んだ）。
        """
        window = self._window
        if window._note is None or not self.debouncer.pending:
            return
        self.debouncer.clear()
        self._save(window._editor.toPlainText(), interactive=interactive)

    def _save(self, text: str, *, interactive: bool = True) -> None:
        window = self._window
        note = window._note
        if note is None:
            return

        action = check_conflict(note, dirty=True)
        if action is ConflictAction.ASK:
            if interactive:
                if not self._resolve_conflict(note, text):
                    return
            else:
                # 聞けないときは書いたものを失わない側に倒す。
                # ダイアログの既定（両方残す）と同じ判断
                self._keep_both(note, text)
                return
        if action is ConflictAction.RELOAD:
            # 自分は書いていないのにここへ来ることはないが、来たら外部を優先する
            window.open_note(note.path)
            return

        payload = window._vault.touch_modified(text)
        window._watcher.suppress(note.path)
        if not self._write(note.path, payload):
            return
        # **書けたあとに残す**（ADR-0023）。書けなかった内容を版にすると、
        # ファイルに無いものが履歴に出る
        window.keep_version(payload)
        # 書けた時点で「ここが保存済みの状態」。これを怠ると、保存後の
        # カーソル移動（リビールの textChanged）が編集扱いに戻ってしまう
        window._editor.document().setModified(False)

        autosave.discard(self.recovery_root, note.path)
        window._note = self._rename_if_title_changed(note, window._vault.read(note.path))
        # ゴミ箱の中のノートを編集しても**生き返らせない**（コードレビュー
        # 指摘）。trashed を付けずに upsert すると「すべて」に幽霊が現れ、
        # フォルダツリーに .trash が生える
        in_trash = window._note.path.is_relative_to(window._vault.trash_dir)
        window._db.upsert_note(window._note, window._vault.root, trashed=in_trash)
        window.refresh()
        window._update_title()
        window._show_saved(datetime.now())
        window._remember_note(window._note.path)

    def _write(self, path: Path, payload: str) -> bool:
        """ファイルへ書く。書けたら True。

        **書けなかったことを黙って飲まない**（コードレビュー指摘）。
        `flush()` は再入を防ぐために保存の前に待ちを解いているので、
        ここで例外が抜けると「保存済み」の顔をしたまま何も書かれない。
        退避（`_maybe_stash`）も待ちを見ているため、保険まで止まる。

        待ちに戻せば次のチックでもう一度試し、退避も続く。ディスクが
        戻れば自然に保存される。
        """
        window = self._window
        try:
            window._vault.write(path, payload)
        except OSError:
            logger.warning("保存できなかった: %s", path, exc_info=True)
            self.debouncer.touch()
            window.notify("保存できませんでした。書き込み先を確かめてください")
            return False
        return True

    def _rename_if_title_changed(self, previous: Note, current: Note) -> Note:
        """タイトルが変わったらファイル名も合わせる（spec §7.1）。

        ただし**ファイル名がそれまでのタイトルと一致していたときだけ**動かす。
        `2026-08-08-会議.md` のように意図して別名を付けている人のファイルを、
        保存のたびに勝手に改名してしまわないため。
        """
        window = self._window
        if current.path.stem != sanitize_filename(previous.title):
            return current

        new_stem = sanitize_filename(current.title)
        if new_stem == current.path.stem:
            return current

        window._watcher.suppress(current.path)
        target = window._vault.rename(current.path, current.title)
        window._watcher.suppress(target)
        window._db.remove_path(window._vault.root, current.path)
        logger.info("タイトル変更に合わせて改名した: %s → %s", current.path.name, target.name)
        return window._vault.read(target)

    # ------------------------------------------------------------- 競合（§7.5）

    def _resolve_conflict(self, note: Note, text: str) -> bool:
        """競合ダイアログを出す。書き込みを続けてよいなら True。"""
        window = self._window
        dialog = ConflictDialog(note.path, window)
        dialog.exec()
        dialog.deleteLater()  # exec() 後も親の子リストに残るため

        match dialog.resolution:
            case Resolution.KEEP_BOTH:
                kept = self._keep_both(note, text)
                if kept is not None:
                    window.open_note(kept)
                return False
            case Resolution.TAKE_EXTERNAL:
                window.open_note(note.path)
                return False
            case Resolution.TAKE_MINE:
                return True
            case _:
                # キャンセルは「まだ決めない」であって「保存できた」ではない。
                # `flush()` は保存の前に待ちを解除しているので、ここで戻さないと
                # 未保存の編集が「保存済み」扱いになり、終了時の「両方残す」も
                # 走らず、書いた内容が消える。退避（_maybe_stash）も pending を
                # 見ているため、戻すことで保険も生き返る
                self.debouncer.touch()
                return False

    def _keep_both(self, note: Note, text: str) -> Path | None:
        """自分の版を別名で保存する（spec §7.5）。書いたものを失わない道。

        書けなければ `None`。ここも待ちに戻して次の機会に試す。
        """
        window = self._window
        target = keep_both_path(note.path)
        window._watcher.suppress(target)
        if not self._write(target, text):
            return None
        window._db.upsert_note(window._vault.read(target), window._vault.root)
        logger.info("競合したため別名で保存した: %s", target.name)
        window.refresh()
        return target
