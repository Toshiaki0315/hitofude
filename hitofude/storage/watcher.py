"""外部からの変更を検知して Qt シグナルへ橋渡しする（spec §7.5）。

**このファイルは R3 の唯一の例外**で、`storage/` の中で PySide6 を
import してよい。watchdog はコールバックを別スレッドで呼ぶため、
Qt のイベントループへ渡す口がどこかに要る。

そのぶん判断ロジック（`WriteSuppressor` と `classify_event`）は Qt に
触れない純関数側へ寄せてある。Qt を挟むと組み合わせを検査しづらい。
"""

import queue
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from hitofude.storage.vault import (
    ATTACHMENTS_DIR,
    MANAGED_DIR,
    MARKDOWN_SUFFIXES,
    TRASH_DIR,
    Vault,
)

SUPPRESS_SECONDS = 1.5
"""spec §7.5: 自分で書いた直後、このあいだは同じパスのイベントを無視する。"""

_SKIP_DIRS = frozenset({TRASH_DIR, MANAGED_DIR, ATTACHMENTS_DIR})


class ChangeKind(Enum):
    CREATED = auto()
    MODIFIED = auto()
    DELETED = auto()


@dataclass
class WriteSuppressor:
    """自分で書いたファイルのイベントを無視する（spec §7.5）。

    保存すれば当然 watchdog が発火する。それを外部変更として扱うと、
    保存のたびにリロードが走る無限ループになる。
    """

    window: float = SUPPRESS_SECONDS
    clock: Callable[[], float] = time.monotonic
    _until: dict[Path, float] = field(default_factory=dict, init=False)

    def suppress(self, path: Path) -> None:
        self._until[Path(path)] = self.clock() + self.window

    def should_ignore(self, path: Path) -> bool:
        self._prune()
        return Path(path) in self._until

    def _prune(self) -> None:
        # 期限切れを残すと、長時間の編集で保存回数ぶん溜まっていく
        now = self.clock()
        expired = [path for path, until in self._until.items() if until <= now]
        for path in expired:
            del self._until[path]

    def __len__(self) -> int:
        return len(self._until)


def classify_event(
    root: Path, kind: str, path: Path, is_directory: bool = False
) -> tuple[ChangeKind, Path] | None:
    """watchdog のイベントを扱うべき変更に翻訳する。対象外なら None。

    落とすもの: ディレクトリ、`.md` 以外、`.trash` / `.hitofude` /
    `attachments` の中、vault の外、そして `save_atomic` が作る `.md.tmp`。
    最後のひとつを落とし忘れると、自分の保存が毎回「新しいファイルの作成」
    として見えてしまう。
    """
    if is_directory:
        return None

    path = Path(path)
    if path.suffix.lower() not in MARKDOWN_SUFFIXES:
        return None
    if not path.is_relative_to(root):
        return None

    relative = path.relative_to(root)
    if any(part in _SKIP_DIRS or part.startswith(".") for part in relative.parts[:-1]):
        return None

    match kind:
        case "created":
            return ChangeKind.CREATED, path
        case "modified":
            return ChangeKind.MODIFIED, path
        case "deleted":
            return ChangeKind.DELETED, path
        case _:
            return None


class VaultWatcher(QObject):
    """vault を監視して Qt シグナルを出す。

    **watchdog のスレッドからは Qt シグナルを出さない。** 監視スレッドは Qt が
    関知しない素の Python スレッドで、そこから `object` を載せたシグナルを
    emit するとセグメンテーション違反で落ちる（実際に踏んだ）。

    そのため受け取ったイベントはスレッド安全なキューに積むだけにして、
    Qt スレッド側の `QTimer` が定期的に取り出して `changed` を出す。
    副次的な利点として、macOS の FSEvents が 1 回の保存で複数のイベントを
    出すのを、取り出しのたびにまとめられる。
    """

    changed = Signal(object, object)
    """`(ChangeKind, Path)`。必ず Qt スレッドから出る。"""

    def __init__(
        self, vault: Vault, parent: QObject | None = None, *, poll_interval_ms: int = 100
    ) -> None:
        super().__init__(parent)
        self._vault = vault
        self._suppressor = WriteSuppressor()
        self._observer: Observer | None = None
        self._pending: queue.Queue[tuple[str, Path, bool]] = queue.Queue()

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self.poll)

    def suppress(self, path: Path) -> None:
        """自分が書いたことを伝える。保存の**直前**に呼ぶ。"""
        self._suppressor.suppress(path)

    def start(self) -> None:
        if self._observer is not None:
            return
        self._vault.ensure_layout()
        self._observer = Observer()
        self._observer.schedule(_Handler(self._enqueue), str(self._vault.root), recursive=True)
        self._observer.start()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2.0)
        self._observer = None

    @property
    def running(self) -> bool:
        return self._observer is not None

    def poll(self) -> list[tuple[ChangeKind, Path]]:
        """溜まったイベントを取り出して `changed` を出す。Qt スレッドから呼ぶ。

        テストからは明示的に呼べるので、タイマーを待たずに検査できる。
        """
        seen: dict[Path, ChangeKind] = {}
        while True:
            try:
                kind, path, is_directory = self._pending.get_nowait()
            except queue.Empty:
                break
            classified = classify_event(self._vault.root, kind, path, is_directory)
            if classified is None:
                continue
            change, target = classified
            if self._suppressor.should_ignore(target):
                continue
            seen[target] = change  # 同じパスの連続イベントは最後だけ残す

        emitted = [(change, path) for path, change in seen.items()]
        for change, path in emitted:
            self.changed.emit(change, path)
        return emitted

    def _enqueue(self, kind: str, path: Path, is_directory: bool) -> None:
        """**監視スレッドから呼ばれる。** ここで Qt に触れてはいけない。"""
        self._pending.put((kind, path, is_directory))


class _Handler(FileSystemEventHandler):
    """watchdog のイベントを 1 つのコールバックにまとめるだけの層。"""

    def __init__(self, callback: Callable[[str, Path, bool], None]) -> None:
        super().__init__()
        self._callback = callback

    def on_created(self, event: FileSystemEvent) -> None:
        self._callback("created", Path(event.src_path), event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._callback("modified", Path(event.src_path), event.is_directory)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._callback("deleted", Path(event.src_path), event.is_directory)

    def on_moved(self, event: FileSystemEvent) -> None:
        # `save_atomic` の replace はここに来る。移動先が本体
        self._callback("deleted", Path(event.src_path), event.is_directory)
        self._callback("modified", Path(event.dest_path), event.is_directory)
