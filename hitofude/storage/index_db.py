"""検索インデックス（spec §7.3）。

**このファイルは捨ててよいキャッシュ（R9）。** 消しても `.md` から完全に
再構築できること。真実は常にファイル側にある。ここに DB にしか無い情報を
置いてはいけない。

日本語検索の要は `tokenize='trigram'`。`unicode61` だと日本語の 1 文が
まるごと 1 トークンになり、部分一致で引けなくなる。
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from hitofude.core import tags as tag_utils
from hitofude.core.document import Note, searchable_text

# trigram は 3 文字単位で索引するため、2 文字以下のクエリは構造上ヒットしない
MIN_TRIGRAM_QUERY = 3

# スニペットの一致部分を挟む印。HTML を直接返させると本文中の `<` が
# タグとして解釈されるため、表示直前に UI 側が変換する
HIGHLIGHT_START = "\x02"
HIGHLIGHT_END = "\x03"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    preview      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    modified_at  TEXT NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    size_bytes   INTEGER NOT NULL,
    pinned       INTEGER NOT NULL DEFAULT 0,
    trashed      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notes_modified ON notes(modified_at DESC);

CREATE TABLE IF NOT EXISTS tags (
    note_id  TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    body,
    note_id UNINDEXED,
    tokenize = 'trigram'
);
"""


class SortOrder(Enum):
    """一覧の並び順（C-3）。"""

    MODIFIED = "modified"
    """更新の新しい順。既定。"""

    CREATED = "created"
    """作成の新しい順。"""

    TITLE = "title"
    """名前順。"""


_ORDER_COLUMNS = {
    SortOrder.MODIFIED: "modified_at DESC",
    SortOrder.CREATED: "created_at DESC",
    SortOrder.TITLE: "title COLLATE NOCASE ASC",
}


def _order_by(order: SortOrder, *, prefix: str = "") -> str:
    """`ORDER BY` の中身。

    **ピン留めは常に先頭。** 並び順を変えても動かさない。ピン留めは
    「上に置いておきたい」という明示の意思で、並べ替えの対象ではない。
    """
    column = _ORDER_COLUMNS.get(order, _ORDER_COLUMNS[SortOrder.MODIFIED])
    return f"{prefix}pinned DESC, {prefix}{column}"


@dataclass(frozen=True, slots=True)
class NoteRow:
    id: str
    path: Path
    title: str
    preview: str
    modified_at: str
    mtime_ns: int
    size_bytes: int
    pinned: bool


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: str
    path: Path
    title: str
    snippet: str


@dataclass(frozen=True, slots=True)
class TagCount:
    tag: str
    count: int

    @property
    def depth(self) -> int:
        return tag_utils.ancestors(self.tag).__len__() - 1

    @property
    def label(self) -> str:
        return tag_utils.leaf(self.tag)


@dataclass(frozen=True, slots=True)
class SyncResult:
    added: list[Path]
    updated: list[Path]
    removed: list[Path]

    @property
    def changed(self) -> int:
        return len(self.added) + len(self.updated) + len(self.removed)


class IndexDb:
    """**1 接続 = 1 スレッド。** 別スレッドで使うなら `IndexDb` を作り直すこと。

    sqlite3 の接続はスレッドをまたげない。起動時の走査を背景で回すときは、
    ワーカー側が自分の接続を開く（`ui/main_window.py` の `_IndexSyncTask`）。
    WAL なので、書いている最中も UI 側の読み取りはブロックされない。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        # 背景スレッドが書いている最中に UI 側が読むことがある。WAL なので
        # 読み手はブロックされないが、書き込みの競合に備えて待つ余地を持たせる
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "IndexDb":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ 書き込み

    def upsert_note(self, note: Note, root: Path, *, trashed: bool = False) -> str:
        """1 つのノートを索引に入れ直す。ID を返す。"""
        note_id = _note_id(note, root)
        relative = note.relative_to(root)
        parsed = note.meta

        self._forget_conflicting(note_id, relative)
        self._connection.execute(
            """
            INSERT INTO notes (id, path, title, preview, created_at, modified_at,
                               mtime_ns, size_bytes, pinned, trashed)
            VALUES (:id, :path, :title, :preview, :created, :modified,
                    :mtime, :size, :pinned, :trashed)
            ON CONFLICT(id) DO UPDATE SET
                path = excluded.path, title = excluded.title, preview = excluded.preview,
                modified_at = excluded.modified_at, mtime_ns = excluded.mtime_ns,
                size_bytes = excluded.size_bytes, pinned = excluded.pinned,
                trashed = excluded.trashed
            """,
            {
                "id": note_id,
                "path": relative,
                "title": note.title,
                "preview": note.preview,
                "created": str(parsed.get("created", "")),
                "modified": str(parsed.get("modified", "")),
                "mtime": note.mtime_ns,
                "size": note.size_bytes,
                "pinned": int(note.pinned),
                "trashed": int(trashed),
            },
        )

        self._connection.execute("DELETE FROM tags WHERE note_id = ?", (note_id,))
        # 祖先も入れておく。サイドバーのタグツリー（§5.1）で親の件数を
        # 数えるとき、SQL 側で前方一致を組む必要がなくなる
        expanded = {ancestor for tag in note.tags for ancestor in tag_utils.ancestors(tag)}
        self._connection.executemany(
            "INSERT OR IGNORE INTO tags (note_id, tag) VALUES (?, ?)",
            [(note_id, tag) for tag in sorted(expanded)],
        )

        self._connection.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
        self._connection.execute(
            "INSERT INTO notes_fts (title, body, note_id) VALUES (?, ?, ?)",
            # 索引にはマーカーを外した写しを入れる。ソースは変えない（R1）
            (note.title, searchable_text(note.text), note_id),
        )
        self._connection.commit()
        return note_id

    def _forget_conflicting(self, note_id: str, relative: str) -> None:
        """同じパスに別 ID の行が残っていたら捨てる。

        ノートの ID は front matter 由来なので、外部エディタで front matter を
        消されると ID が変わる（パスから合成した ID に落ちる）。そのとき
        `path` の UNIQUE 制約に当たって索引の更新が止まってしまうため、
        古いほうを先に消す。ファイル側が真実（R9）なので、これで正しい。
        """
        row = self._connection.execute(
            "SELECT id FROM notes WHERE path = ? AND id != ?", (relative, note_id)
        ).fetchone()
        if row is None:
            return
        self._connection.execute("DELETE FROM notes_fts WHERE note_id = ?", (row["id"],))
        self._connection.execute("DELETE FROM notes WHERE id = ?", (row["id"],))

    def remove_path(self, root: Path, path: Path) -> None:
        relative = str(path.relative_to(root)) if path.is_absolute() else str(path)
        row = self._connection.execute(
            "SELECT id FROM notes WHERE path = ?", (relative,)
        ).fetchone()
        if row is None:
            return
        self._connection.execute("DELETE FROM notes_fts WHERE note_id = ?", (row["id"],))
        self._connection.execute("DELETE FROM notes WHERE id = ?", (row["id"],))
        self._connection.commit()

    def sync(self, vault) -> SyncResult:
        """vault と索引の差分だけを取り込む（spec §7.3 の起動時同期）。

        全件を読み直すと 5,000 ノートで数秒かかる。`mtime_ns` と
        `size_bytes` の突き合わせで、触られていないファイルは開かない。
        """
        known = {
            row["path"]: (row["mtime_ns"], row["size_bytes"])
            for row in self._connection.execute("SELECT path, mtime_ns, size_bytes FROM notes")
        }

        added: list[Path] = []
        updated: list[Path] = []
        seen: set[str] = set()

        for path in vault.scan():
            relative = str(path.relative_to(vault.root))
            seen.add(relative)
            stat = path.stat()
            current = (stat.st_mtime_ns, stat.st_size)
            previous = known.get(relative)
            if previous == current:
                continue

            self.upsert_note(Note.read(path), vault.root)
            (added if previous is None else updated).append(path)

        removed = [vault.root / relative for relative in sorted(set(known) - seen)]
        for path in removed:
            self.remove_path(vault.root, path)

        return SyncResult(added=added, updated=updated, removed=removed)

    # -------------------------------------------------------------------- 参照

    def notes(
        self,
        *,
        include_trashed: bool = False,
        limit: int | None = None,
        order: "SortOrder" = SortOrder.MODIFIED,
    ) -> list[NoteRow]:
        sql = "SELECT * FROM notes"
        if not include_trashed:
            sql += " WHERE trashed = 0"
        sql += f" ORDER BY {_order_by(order)}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [_to_row(row) for row in self._connection.execute(sql)]

    def notes_with_tag(self, tag: str, *, order: "SortOrder" = SortOrder.MODIFIED) -> list[NoteRow]:
        """そのタグ、または配下のタグを持つノート。"""
        normalized = tag_utils.normalize(tag)
        rows = self._connection.execute(
            f"""
            SELECT notes.* FROM notes
            JOIN tags ON tags.note_id = notes.id
            WHERE tags.tag = ? AND notes.trashed = 0
            ORDER BY {_order_by(order, prefix="notes.")}
            """,
            (normalized,),
        )
        return [_to_row(row) for row in rows]

    def tag_tree(self) -> list[TagCount]:
        """タグごとの件数。祖先も含む（spec §5.1 のサイドバー）。"""
        rows = self._connection.execute(
            """
            SELECT tags.tag AS tag, COUNT(DISTINCT tags.note_id) AS count
            FROM tags JOIN notes ON notes.id = tags.note_id
            WHERE notes.trashed = 0
            GROUP BY tags.tag
            ORDER BY tags.tag
            """
        )
        return [TagCount(tag=row["tag"], count=row["count"]) for row in rows]

    def search(self, query: str, *, limit: int = 50) -> list[SearchHit]:
        """全文検索（spec §7.3）。

        trigram は 3 文字単位で索引するため、**2 文字以下のクエリは構造上
        ヒットしない**。「人事」「経費」のような 2 文字の日本語は日常的に
        検索されるので、短いクエリでは FTS を諦めて LIKE に切り替える。
        """
        text = query.strip()
        if not text:
            return []
        if len(text) < MIN_TRIGRAM_QUERY:
            return self._search_like(text, limit=limit)
        return self._search_fts(text, limit=limit)

    def _search_fts(self, text: str, *, limit: int) -> list[SearchHit]:
        rows = self._connection.execute(
            """
            SELECT notes.id AS id, notes.path AS path, notes.title AS title,
                   snippet(notes_fts, 1, :start, :end, '…', 12) AS snippet
            FROM notes_fts
            JOIN notes ON notes.id = notes_fts.note_id
            WHERE notes_fts MATCH :query AND notes.trashed = 0
            ORDER BY rank
            LIMIT :limit
            """,
            {
                "query": _quote(text),
                "limit": limit,
                "start": HIGHLIGHT_START,
                "end": HIGHLIGHT_END,
            },
        )
        return [_to_hit(row) for row in rows]

    def _search_like(self, text: str, *, limit: int) -> list[SearchHit]:
        """短いクエリ用のフォールバック。

        走査対象はタイトルとプレビューだけ（spec §7.3）。本文まで LIKE で
        舐めると件数に比例して遅くなるため、G4（200ms）を守れなくなる。
        """
        pattern = f"%{text}%"
        rows = self._connection.execute(
            """
            SELECT id, path, title, preview AS snippet FROM notes
            WHERE trashed = 0 AND (title LIKE ? OR preview LIKE ?)
            ORDER BY pinned DESC, modified_at DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        )
        return [_to_hit(row) for row in rows]


def _quote(text: str) -> str:
    """FTS5 のクエリ構文として解釈させず、そのまま部分一致させる。

    引用符で囲まないと `AND` や `*` が演算子になり、ユーザーが打った
    記号でエラーになる。
    """
    escaped = text.replace('"', '""')
    return f'"{escaped}"'


def _note_id(note: Note, root: Path) -> str:
    """front matter に `id` があればそれ、無ければ相対パスから作る。

    外部エディタで作られたノートには front matter が無い。索引の主キーは
    必ず要るので、パスから安定した ID を合成する。
    """
    return note.id or f"path:{note.relative_to(root)}"


def _to_row(row: sqlite3.Row) -> NoteRow:
    return NoteRow(
        id=row["id"],
        path=Path(row["path"]),
        title=row["title"],
        preview=row["preview"],
        modified_at=row["modified_at"],
        mtime_ns=row["mtime_ns"],
        size_bytes=row["size_bytes"],
        pinned=bool(row["pinned"]),
    )


def _to_hit(row: sqlite3.Row) -> SearchHit:
    return SearchHit(
        id=row["id"], path=Path(row["path"]), title=row["title"], snippet=row["snippet"]
    )


def rebuild(db_path: Path, vault) -> SyncResult:
    """索引を作り直す（R9 の担保）。

    `.hitofude/index.sqlite` を消しても `.md` から完全に復元できることを、
    この関数の存在と回帰テストで保証する。
    """
    db_path.unlink(missing_ok=True)
    for extra in (".sqlite-wal", ".sqlite-shm"):
        db_path.with_suffix(extra).unlink(missing_ok=True)
    with IndexDb(db_path) as db:
        return db.sync(vault)


def paths_of(rows: Iterable[NoteRow], root: Path) -> list[Path]:
    return [root / row.path for row in rows]
