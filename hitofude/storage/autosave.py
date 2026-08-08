"""保存の実行とデバウンス（spec §7.4）。

GUI 非依存（R3）。デバウンスは `QTimer` ではなく「いつ書くべきか」を判断する
状態機械として持ち、実際の時計は呼び出し側が渡す。こうすると
イベントループ無しで時間の経過を検査できる。
"""

import hashlib
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


# --------------------------------------------------------------------------
# クラッシュリカバリ（spec §9 Phase 6）
#
# 未保存の内容を `~/Library/Application Support/Hitofude/recovery/` に退避する。
# 通常は 800ms で保存されるので出番は少ないが、保存できない状態（競合の未解決、
# ディスクエラー）のまま落ちたときに書いたものを失わないための保険。
#
# 退避先は**プレーンテキスト 2 ファイル**（本文と元のパス）にしてある。
# 復元の仕組み自体が壊れても、Finder から中身を読んで手で救い出せる。
# --------------------------------------------------------------------------

APP_SUPPORT_NAME = "Hitofude"
RECOVERY_DIRNAME = "recovery"
SOURCE_SUFFIX = ".source"
STASH_SUFFIX = ".md"


@dataclass(frozen=True, slots=True)
class Stashed:
    source: Path
    """元のノートのパス。"""

    text: str
    stashed_at: float


def recovery_root(vault_path: Path, home: Path | None = None) -> Path:
    """退避先。**vault ごとに分ける。**

    複数の保管フォルダを使い分けている場合、片方の未保存内容がもう片方の
    起動時に出てくると混乱する。vault のパスから作った鍵で分離する。
    """
    base = home if home is not None else Path.home()
    key = _key(vault_path)
    return base / "Library" / "Application Support" / APP_SUPPORT_NAME / RECOVERY_DIRNAME / key


def _key(note_path: Path) -> str:
    return hashlib.blake2b(str(note_path).encode("utf-8"), digest_size=12).hexdigest()


def stash(root: Path, note_path: Path, text: str) -> Path:
    """未保存の内容を退避する。同じノートの退避は上書きする。"""
    root.mkdir(parents=True, exist_ok=True)
    key = _key(note_path)
    target = root / f"{key}{STASH_SUFFIX}"
    save_atomic(target, text)
    save_atomic(root / f"{key}{SOURCE_SUFFIX}", str(note_path))
    return target


def discard(root: Path, note_path: Path) -> None:
    """保存できたので退避を捨てる。"""
    key = _key(note_path)
    (root / f"{key}{STASH_SUFFIX}").unlink(missing_ok=True)
    (root / f"{key}{SOURCE_SUFFIX}").unlink(missing_ok=True)


def pending(root: Path) -> list[Stashed]:
    """起動時に拾う。壊れた退避は黙って飛ばす。"""
    if not root.is_dir():
        return []

    found: list[Stashed] = []
    for source_file in sorted(root.glob(f"*{SOURCE_SUFFIX}")):
        body = source_file.with_suffix(STASH_SUFFIX)
        if not body.is_file():
            continue
        try:
            found.append(
                Stashed(
                    source=Path(source_file.read_text(encoding="utf-8").strip()),
                    text=body.read_text(encoding="utf-8"),
                    stashed_at=body.stat().st_mtime,
                )
            )
        except OSError:
            continue  # 読めない退避のせいで起動できなくなってはいけない
    return found


def clear_all(root: Path) -> None:
    for path in root.glob("*"):
        path.unlink(missing_ok=True)
