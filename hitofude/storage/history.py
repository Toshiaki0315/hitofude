"""版の履歴（提案 6 / ADR-0023）。

保存のたびに全文を 1 ファイルとして残し、「昨日の状態に戻す」を可能にする。

- **差分にしない。** 差分はそれ自体が壊れうる構造で、壊れたときに何も
  戻せなくなる。素の `.md` のままなら、アプリが無くても Finder から読める
- **id で分ける。** 題名（＝ファイル名）は変わるが、front matter の ULID は
  変わらない。名前を変えても履歴が途切れない
- **間引く。** 自動保存は打ち終わって 0.8 秒で走るので、1 版/保存にすると
  1 時間の執筆で数百版になる

**ここは Qt を知らない**（R3）。いつ呼ぶかは UI の仕事。
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from hitofude.core import frontmatter
from hitofude.core.document import title_of

logger = logging.getLogger(__name__)

MIN_INTERVAL_MINUTES = 5
"""前の版からこれだけ経っていなければ残さない（ADR-0023）。既定。"""

INTERVAL_CHOICES = (0, 5, 15, 30, 60)
"""設定で選べる間隔（分）。`0` は「なし」（ユーザー要望 2026-08-24）。

**細かさの好みは人による。** 打つたびに残っていてほしい人と、
版が増えるのを嫌う人がいる。`0` は自分で保存したときだけ残す。
"""

MAX_VERSIONS = 50
"""1 ノートにつき保つ版の数。"""

MAX_DAYS = 30
"""保つ期間。ゴミ箱（`DEFAULT_TRASH_DAYS`）と揃える。"""

# ファイル名にできる形の日時。`:` は macOS の Finder が `/` に見せるので使わない
_STAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"
_STAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}")

UNTITLED = "無題"


def folder_name(key: str) -> str:
    """索引の鍵をフォルダ名にする。

    front matter のある ノートは ULID（そのまま使える）。無いノートの鍵は
    `path:サブ/フォルダ/名前.md` の形で、`/` を含むのでフォルダ名にできない。
    **短く畳む**（中身は読まないので、一意でありさえすればよい）。
    """
    if not key.startswith("path:"):
        return key
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"path-{digest}"


@dataclass(frozen=True, slots=True)
class Version:
    """残っている 1 つの版。"""

    path: Path
    saved_at: datetime

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def title(self) -> str:
        """その版の題名。**触るまで読まない**（コードレビュー指摘）。

        題名が要るのは一覧（履歴ダイアログ）だけ。保存のたびの間引き
        判定や起動時の整理が全版の中身（最大 6.3MB/ノート）を読むのは
        無駄で、16ms / 1.5s の予算（CLAUDE.md §7）を食い潰す。
        """
        return _title_of(self.path)


def keep(
    root: Path,
    key: str,
    text: str,
    *,
    now: datetime,
    force: bool = False,
    interval_minutes: int = MIN_INTERVAL_MINUTES,
) -> Path | None:
    """今の全文を 1 版として残す。残したら場所を、残さなければ `None`。

    **残さない場合**（`force=True` なら間引きだけ飛ばす）:

    - 本文が空（新規ノートを開いただけで版が増えない）
    - `interval_minutes` が `0`（「なし」。自分で保存したときだけ残す）
    - 直前の版から `interval_minutes` 経っていない
    - 直前の版と中身が同じ（打っていないのに増えない）
    """
    if not text.strip():
        return None

    if not force and interval_minutes <= 0:
        return None

    note_id = folder_name(key)
    latest = _latest(root, note_id)
    if latest is not None:
        # **時刻の判定が先。** ファイル名だけで済み、中身を読まずに
        # 大半（間隔の内に入る自動保存）を弾ける。中身の比較はその後
        if not force and now - latest.saved_at < timedelta(minutes=interval_minutes):
            return None
        try:
            if latest.read() == text:
                return None
        except OSError:
            logger.warning("前の版を読めなかった: %s", latest.path)

    target = root / note_id / f"{now.strftime(_STAMP_FORMAT)}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    # 同じ秒に 2 回来たら上書きでよい（中身は同じか、直後の打ち直し）
    target.write_text(text, encoding="utf-8")
    return target


def versions(root: Path, key: str) -> list[Version]:
    """残っている版を**新しい順**に返す。読めないものは飛ばす。"""
    folder = root / folder_name(key)
    if not folder.is_dir():
        return []

    found: list[Version] = []
    for path in folder.glob("*.md"):
        saved_at = _stamp_of(path)
        if saved_at is None:
            continue
        found.append(Version(path=path, saved_at=saved_at))
    found.sort(key=lambda version: version.saved_at, reverse=True)
    return found


def prune(root: Path, *, now: datetime) -> list[Path]:
    """多すぎる版と古すぎる版を捨てる。捨てたものを返す。

    **古いほうから捨てる。** 直近の状態ほど戻したくなる。
    """
    if not root.is_dir():
        return []

    deadline = now - timedelta(days=MAX_DAYS)
    removed: list[Path] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        found = versions(root, folder.name)
        for index, version in enumerate(found):
            if index >= MAX_VERSIONS or version.saved_at < deadline:
                version.path.unlink(missing_ok=True)
                removed.append(version.path)
        if not any(folder.iterdir()):
            folder.rmdir()
    return removed


def total_bytes(root: Path) -> int:
    """履歴が使っている容量。**見えないところで太らせない**ために出す。"""
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*.md") if path.is_file())


def _latest(root: Path, note_id: str) -> Version | None:
    found = versions(root, note_id)
    return found[0] if found else None


def _stamp_of(path: Path) -> datetime | None:
    if not _STAMP_RE.match(path.stem):
        return None
    try:
        return datetime.strptime(path.stem[:19], _STAMP_FORMAT)
    except ValueError:
        return None


def _title_of(path: Path) -> str:
    """その版の題名。一覧に出すと、どれか見当が付く。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return UNTITLED
    return title_of(frontmatter.split(text).body, UNTITLED)
