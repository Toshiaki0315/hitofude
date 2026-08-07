"""保存の実行とデバウンス（spec §7.4）。

GUI 非依存（R3）。デバウンスは `QTimer` ではなく「いつ書くべきか」を判断する
状態機械として持ち、実際の時計は呼び出し側が渡す。こうすると
イベントループ無しで時間の経過を検査できる。
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

DEBOUNCE_SECONDS = 0.8
"""spec §7.4: テキスト変更から 800ms 後に書く。"""

TEMP_SUFFIX = ".tmp"


def save_atomic(path: Path, text: str) -> None:
    """一時ファイルへ書いてから差し替える（spec §7.4）。

    `fsync` してから `os.replace` する。これで電源断が起きても、
    「古い内容のまま」か「新しい内容」かのどちらかにしかならない。
    中途半端に切れたファイルが残らないことがノートアプリでは決定的に重要。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + TEMP_SUFFIX)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)  # os.replace と同じ。同一ボリューム内なら atomic
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@dataclass
class Debouncer:
    """「最後の変更から一定時間経ったら書く」を判断する（spec §7.4）。

    保存の契機は 800ms のデバウンスのほかに、ノート切り替え・
    フォーカス喪失・`Cmd+S`・終了時があり、そちらは即時に書く。
    """

    delay: float = DEBOUNCE_SECONDS
    clock: Callable[[], float] = time.monotonic
    _pending_at: float | None = field(default=None, init=False)

    @property
    def pending(self) -> bool:
        return self._pending_at is not None

    def touch(self) -> None:
        """変更があったことを伝える。待ち時間はそのつど延びる。"""
        self._pending_at = self.clock()

    def due(self) -> bool:
        """今書くべきか。"""
        if self._pending_at is None:
            return False
        return self.clock() - self._pending_at >= self.delay

    def remaining(self) -> float:
        """あと何秒待てばよいか。待ち中でなければ 0。"""
        if self._pending_at is None:
            return 0.0
        return max(0.0, self.delay - (self.clock() - self._pending_at))

    def clear(self) -> None:
        """書いたので待ちを解除する。"""
        self._pending_at = None
