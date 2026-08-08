"""保管フォルダ（vault）の走査と CRUD（spec §7.1, §7.6）。

```
HitofudeNotes/
├── 会議メモ.md          ← ノートは vault 直下のフラット構成
├── attachments/         ← 画像等
├── .trash/              ← 削除したノート（既定 30 日で自動消去）
└── .hitofude/           ← アプリの管理領域（index.sqlite）
```

**フォルダ階層で分類しない。** 分類はタグで行う（§7.1）。ユーザーが手で
サブフォルダを作った場合は再帰的に読み込むが、アプリからは作らせない。
"""

import re
import time
import unicodedata
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path

from hitofude.core import frontmatter
from hitofude.core.document import Note, new_id
from hitofude.storage.autosave import save_atomic

MARKDOWN_SUFFIXES = (".md", ".markdown")
ATTACHMENTS_DIR = "attachments"
TRASH_DIR = ".trash"
MANAGED_DIR = ".hitofude"
DEFAULT_TRASH_DAYS = 30
UNTITLED = "無題"

# ファイル名の上限は 255 バイト。日本語は 1 文字 3 バイトなので余裕を取る
MAX_FILENAME_BYTES = 200

# macOS で使えない、または使うと事故る文字。`/` はパス区切り、`:` は Finder が嫌う
_ILLEGAL_RE = re.compile(r"[/:\\]")
_WHITESPACE_RE = re.compile(r"\s+")

_SKIP_DIRS = frozenset({TRASH_DIR, MANAGED_DIR, ATTACHMENTS_DIR})


def sanitize_filename(title: str) -> str:
    """タイトルをファイル名に使える形へ直す（spec §7.1）。"""
    text = unicodedata.normalize("NFC", title)
    text = "".join(
        character for character in text if character.isprintable() or character.isspace()
    )
    text = _ILLEGAL_RE.sub("-", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.lstrip(".").strip()  # 先頭のドットは隠しファイルになってしまう

    while len(text.encode("utf-8")) > MAX_FILENAME_BYTES:
        text = text[:-1]

    return text or UNTITLED


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """重複しないパスを返す。衝突したら `-2`, `-3` を付ける（spec §7.1）。"""
    candidate = directory / f"{stem}{suffix}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------- レイアウト

    def ensure_layout(self) -> None:
        for directory in (self.root, self.trash_dir, self.managed_dir, self.attachments_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def trash_dir(self) -> Path:
        return self.root / TRASH_DIR

    @property
    def managed_dir(self) -> Path:
        return self.root / MANAGED_DIR

    @property
    def attachments_dir(self) -> Path:
        return self.root / ATTACHMENTS_DIR

    # ----------------------------------------------------------------- 走査

    def scan(self) -> Iterator[Path]:
        """vault 内の `.md` を返す。`.trash` と `.hitofude` は除く。"""
        if not self.root.is_dir():
            return
        yield from self._walk(self.root)

    def _walk(self, directory: Path) -> Iterator[Path]:
        for entry in sorted(directory.iterdir()):
            if entry.is_dir():
                if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                    continue
                yield from self._walk(entry)
            elif entry.suffix.lower() in MARKDOWN_SUFFIXES:
                yield entry

    # ----------------------------------------------------------------- 読み書き

    def read(self, path: Path) -> Note:
        return Note.read(path)

    def create(self, title: str, text: str | None = None) -> Note:
        """新しいノートを作る。front matter に ULID と日時を入れる（spec §7.2）。"""
        self.ensure_layout()
        path = unique_path(self.root, sanitize_filename(title))

        parsed = frontmatter.split(text or "")
        timestamp = _now()
        meta = {
            "id": new_id(),
            "created": timestamp,
            "modified": timestamp,
            **parsed.meta,
        }
        save_atomic(path, frontmatter.join(meta, parsed.body))
        return self.read(path)

    def write(self, path: Path, text: str) -> None:
        """本文を保存する。電源断で壊れないようアトミックに書く（spec §7.4）。"""
        save_atomic(path, text)

    def touch_modified(self, text: str) -> str:
        """保存時に front matter の `modified` を更新した本文を返す（spec §7.2）。"""
        parsed = frontmatter.split(text)
        if not parsed.present:
            return text
        return frontmatter.join({**parsed.meta, "modified": _now()}, parsed.body)

    # ----------------------------------------------------------------- 移動

    def rename(self, path: Path, title: str) -> Path:
        """タイトル変更に合わせてファイル名を変える。

        旧名は `.trash` に残さない（spec §7.1）。リネームは削除ではないため、
        ゴミ箱に増えていくとユーザーが混乱する。
        """
        target = self.root / f"{sanitize_filename(title)}.md"
        if target == path:
            return path
        target = unique_path(self.root, sanitize_filename(title))
        path.replace(target)
        return target

    def trash(self, path: Path) -> Path:
        """`.trash` へ移す（spec §7.6）。同名があればタイムスタンプを付ける。"""
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        target = self.trash_dir / path.name
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.trash_dir / f"{path.stem}-{stamp}{path.suffix}"
        path.replace(target)
        return target

    def restore(self, path: Path) -> Path:
        """ゴミ箱から vault 直下へ戻す。"""
        target = unique_path(self.root, path.stem, path.suffix)
        path.replace(target)
        return target

    def purge_trash(self, days: int = DEFAULT_TRASH_DAYS) -> list[Path]:
        """期限を過ぎたゴミ箱の中身を消す（spec §7.6）。起動時に呼ぶ。"""
        if not self.trash_dir.is_dir():
            return []

        deadline = time.time() - days * 24 * 3600
        removed: list[Path] = []
        for entry in sorted(self.trash_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.stat().st_mtime < deadline:
                entry.unlink()
                removed.append(entry)
        return removed


# --------------------------------------------------------------------------
# 競合検知（spec §7.5）
#
# 読み込んだ時点の mtime とダイジェストを持っておき、保存の直前に再検査する。
# TOCTOU を完全には防げないが、外部エディタとの併用という現実的な用途には
# 十分（§7.5）。
# --------------------------------------------------------------------------


class ConflictAction(Enum):
    WRITE = auto()
    """そのまま保存してよい。"""

    RELOAD = auto()
    """外部の変更を黙って取り込む（こちらは未編集）。"""

    ASK = auto()
    """双方が変更している。ユーザーに選ばせる。"""

    RECREATE = auto()
    """外部で削除された。作り直すか尋ねる。"""


def decide(
    *,
    exists: bool,
    disk_mtime_ns: int,
    disk_digest: str,
    loaded_mtime_ns: int,
    loaded_digest: str,
    dirty: bool,
) -> ConflictAction:
    """保存直前にどうするかを決める（spec §7.5 の表）。純関数。"""
    if not exists:
        return ConflictAction.RECREATE
    if disk_mtime_ns == loaded_mtime_ns:
        return ConflictAction.WRITE
    if disk_digest == loaded_digest:
        # mtime だけ動いて中身が同じ。touch や同内容の保存。知らせる意味がない
        return ConflictAction.WRITE
    return ConflictAction.ASK if dirty else ConflictAction.RELOAD


def check_conflict(note: Note, *, dirty: bool) -> ConflictAction:
    """ディスクの現状を読んで `decide()` にかける。"""
    try:
        stat = note.path.stat()
    except OSError:
        return ConflictAction.RECREATE

    if stat.st_mtime_ns == note.mtime_ns:
        # 中身を読まずに済む一番多い経路
        return ConflictAction.WRITE

    current = Note.read(note.path)
    return decide(
        exists=True,
        disk_mtime_ns=current.mtime_ns,
        disk_digest=current.digest,
        loaded_mtime_ns=note.mtime_ns,
        loaded_digest=note.digest,
        dirty=dirty,
    )


def keep_both_path(path: Path, date: str | None = None) -> Path:
    """「両方残す」ときの保存先（spec §7.5）。

    `会議メモ.md` → `会議メモ (競合 2026-08-08).md`。
    元のファイル名を保つので、あとで見たときにどれと競合したのか分かる。
    """
    stamp = date or datetime.now().date().isoformat()
    return unique_path(path.parent, f"{path.stem} (競合 {stamp})", path.suffix)
