"""検索インデックス（spec §7.3）。

**このファイルは捨ててよいキャッシュ（R9）。** 消しても `.md` から完全に
再構築できること。真実は常にファイル側にある。ここに DB にしか無い情報を
置いてはいけない。

日本語検索の要は `tokenize='trigram'`。`unicode61` だと日本語の 1 文が
まるごと 1 トークンになり、部分一致で引けなくなる。
"""

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from hitofude.core import tags as tag_utils
from hitofude.core import wikilink
from hitofude.core.document import Note, searchable_text

logger = logging.getLogger(__name__)

# trigram は 3 文字単位で索引するため、2 文字以下のクエリは構造上ヒットしない
MIN_TRIGRAM_QUERY = 3

# スニペットの一致部分を挟む印。HTML を直接返させると本文中の `<` が
# タグとして解釈されるため、表示直前に UI 側が変換する
HIGHLIGHT_START = "\x02"
HIGHLIGHT_END = "\x03"

# 索引の作り。**増やしたら上げる。** 上げると次の起動で中身を捨てて
# 走査し直す（R9: 索引は捨ててよいキャッシュ）。表を足すだけでは、既にある
# ノートは触られるまで読み直されず（`sync()` は mtime を見る）、新しい列が
# 黙って空のままになる。**中身の作り方を変えたときも同じ**で、古い値が
# 残り続ける。2 で `links`（E-6）を足し、3 でプレビューからマーカーを外した
SCHEMA_VERSION = 3

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

CREATE TABLE IF NOT EXISTS links (
    note_id  TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target   TEXT NOT NULL,
    PRIMARY KEY (note_id, target)
);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target);

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


# 保存した検索が一覧に出す最大件数。SQLite の IN 句の既定上限
# （999 変数）より十分下に置く
_MATCH_LIMIT = 500


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: str
    path: Path
    title: str
    snippet: str


@dataclass(frozen=True, slots=True)
class FolderCount:
    """フォルダ 1 つと、その中（子孫を含む）のノート数（K-2）。"""

    folder: str
    """vault からの相対パス（`仕事/2026`）。区切りは常に `/`。"""

    count: int

    @property
    def label(self) -> str:
        """画面に出す名前。**末端だけ**（階層は字下げで見せる）。"""
        return self.folder.rsplit("/", 1)[-1]


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
    skipped: list[Path] = field(default_factory=list)
    """読めずに飛ばしたファイル。索引の既存行は消さずに残す。"""

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
        self._migrate()

    def _migrate(self) -> None:
        """古い作りの索引を捨てて作り直す。

        **中身だけ消して表は残す。** 次の `sync()` が全ファイルを読み直して
        埋める（R9）。真実はファイル側にあるので、ここで失うものは無い。
        """
        if self.schema_version() == SCHEMA_VERSION:
            return
        self.reset()
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()

    def schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def reset(self) -> None:
        """索引を空にする。ファイルは触らない（R9）。"""
        self._connection.execute("DELETE FROM notes")
        self._connection.execute("DELETE FROM links")
        self._connection.execute("DELETE FROM tags")
        self._connection.execute("DELETE FROM notes_fts")
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
        note_id = self._resolve_duplicate_id(note_id, relative, root)
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
                # modified が無い（外部エディタ製の front matter 無し）
                # ノートはファイルの mtime で代用する。空文字のままだと
                # 文字列比較の after: に永遠に掛からず before: には常に
                # 掛かり、並び順でも最下位に沈む（コードレビュー指摘）
                "modified": str(parsed.get("modified", "")) or _mtime_stamp(note.mtime_ns),
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

        # 指しているノート（E-6）。**行き先の有無は問わない。**
        # まだ無いノートへのリンクも、作られた瞬間に繋がるべきもの
        self._connection.execute("DELETE FROM links WHERE note_id = ?", (note_id,))
        self._connection.executemany(
            "INSERT OR IGNORE INTO links (note_id, target) VALUES (?, ?)",
            [(note_id, target) for target in wikilink.links(note.text)],
        )

        self._connection.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
        self._connection.execute(
            "INSERT INTO notes_fts (title, body, note_id) VALUES (?, ?, ?)",
            # 索引にはマーカーを外した写しを入れる。ソースは変えない（R1）
            (note.title, searchable_text(note.text), note_id),
        )
        self._connection.commit()
        return note_id

    def _resolve_duplicate_id(self, note_id: str, relative: str, root: Path) -> str:
        """同じ id が**実在する別ファイル**に付いているなら、パス合成 id に落とす。

        Finder でコピーすると同じ ULID の 2 ファイルができる。id を奪い合うと
        `ON CONFLICT(id)` が行を上書きし、sync のたびに見える側が入れ替わる。
        元の行のファイルが実在するなら複製と見なし、後から来たほうをパスで
        区別する。ファイルが消えているなら改名・移動なので、そのまま引き継ぐ。
        """
        row = self._connection.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None or row["path"] == relative:
            return note_id
        if (root / row["path"]).is_file():
            return f"path:{relative}"
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
        skipped: list[Path] = []
        seen: set[str] = set()

        for path in vault.scan():
            relative = str(path.relative_to(vault.root))
            seen.add(relative)
            # 1 ファイルの故障（非 UTF-8・走査後に消えた等）で索引更新全体を
            # 止めない。飛ばしても seen には入れてあるので、既に索引済みの
            # 行は消えずに残る（一覧から見えなくなるより古いままのほうがいい）
            try:
                stat = path.stat()
                current = (stat.st_mtime_ns, stat.st_size)
                previous = known.get(relative)
                if previous == current:
                    continue

                self.upsert_note(Note.read(path), vault.root)
            except (OSError, UnicodeDecodeError):
                logger.warning("読めないので索引から飛ばす: %s", path, exc_info=True)
                skipped.append(path)
                continue
            (added if previous is None else updated).append(path)

        removed = [vault.root / relative for relative in sorted(set(known) - seen)]
        for path in removed:
            self.remove_path(vault.root, path)

        return SyncResult(added=added, updated=updated, removed=removed, skipped=skipped)

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

    def titles(self) -> list[str]:
        """ゴミ箱以外の題名だけの一覧。

        `[[` の補完（打鍵ごとに呼ばれる）用。`notes()` は SELECT * で
        preview まで運んで NoteRow を組むため、大きな vault では打鍵の
        16ms 予算（§6.6）を食う（コードレビュー指摘）。
        """
        rows = self._connection.execute("SELECT title FROM notes WHERE trashed = 0")
        return [row["title"] for row in rows]

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

    def backlinks(self, title: str, *, order: "SortOrder" = SortOrder.MODIFIED) -> list[NoteRow]:
        """その題名を `[[...]]` で指しているノート（E-6）。

        **大小は無視する**（`COLLATE NOCASE`）。解決（`wikilink.resolve`）が
        無視する以上、逆から引くときも同じでないと片道になる。日本語には
        大小が無いので、効くのは英字だけ。
        """
        target = wikilink.normalize(title)
        if not target:
            return []
        rows = self._connection.execute(
            f"""
            SELECT notes.* FROM notes
            JOIN links ON links.note_id = notes.id
            WHERE links.target = ? COLLATE NOCASE AND notes.trashed = 0
            ORDER BY {_order_by(order, prefix="notes.")}
            """,
            (target,),
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

    def folder_tree(self) -> list["FolderCount"]:
        """フォルダごとの件数（K-2）。**親は子も数える**（タグと同じ）。

        vault 直下は数えない。「すべて」と同じ意味になり、フォルダとして
        並べても選ぶ意味がない。

        パスの組み立ては SQL でやらず Python 側で数える。ノート数ぶんの
        文字列操作だが、5,000 件でも数 ms（実測）で、SQL に階層を
        組み込むより読める。
        """
        counts: dict[str, int] = {}
        rows = self._connection.execute("SELECT path FROM notes WHERE trashed = 0")
        for row in rows:
            parts = Path(row["path"]).parent.parts
            for depth in range(1, len(parts) + 1):
                folder = "/".join(parts[:depth])
                counts[folder] = counts.get(folder, 0) + 1
        return [FolderCount(folder=folder, count=counts[folder]) for folder in sorted(counts)]

    def notes_in_folder(
        self, folder: str, *, order: "SortOrder" = SortOrder.MODIFIED
    ) -> list[NoteRow]:
        """そのフォルダ（子孫を含む）のノート。

        **区切りまで含めて前方一致する。** `仕事` で `仕事場/` を拾わない。
        """
        prefix = f"{folder.strip('/')}/"
        # **LIKE ではなく範囲で引く**（コードレビュー指摘）。既定の LIKE は
        # 大文字小文字を区別せず、BINARY の UNIQUE 索引と噛み合わないため
        # 常に全表走査になる（EXPLAIN で実測）。前方一致は
        # `path >= '仕事/' AND path < '仕事0'`（'/' の次の文字が '0'）で
        # 表せて、索引をそのまま使える。ワイルドカードが無いので
        # エスケープも要らない
        upper = prefix[:-1] + chr(ord(prefix[-1]) + 1)
        rows = self._connection.execute(
            f"""
            SELECT * FROM notes
            WHERE trashed = 0 AND path >= ? AND path < ?
            ORDER BY {_order_by(order)}
            """,
            (prefix, upper),
        )
        return [_to_row(row) for row in rows]

    def notes_matching(
        self,
        *,
        text: str,
        tags: Sequence[str] = (),
        after: "date | None" = None,
        before: "date | None" = None,
        order: "SortOrder" = SortOrder.MODIFIED,
    ) -> list[NoteRow]:
        """検索式に合うノートを一覧の行として返す（K-4 / 保存した検索）。

        当たりの判定は全文検索（`search`）と同じ。並びは一覧と同じ
        （ピン留めが先頭）。**件数の上限は設けない**（一覧なので、
        パレットの 50 件とは役目が違う）。
        """
        if not text:
            clause, tag_params = self._tag_clause(tags)
            date_clause, date_params = self._date_clause(after, before)
            rows = self._connection.execute(
                f"""
                SELECT * FROM notes
                WHERE trashed = 0{clause}{date_clause}
                ORDER BY {_order_by(order)}
                """,
                (*tag_params, *date_params),
            )
            return [_to_row(row) for row in rows]

        hits = self.search(text, tags=tags, after=after, before=before, limit=_MATCH_LIMIT)
        if not hits:
            return []
        ids = [hit.id for hit in hits]
        marks = ", ".join("?" for _ in ids)
        rows = self._connection.execute(
            f"""
            SELECT * FROM notes
            WHERE trashed = 0 AND id IN ({marks})
            ORDER BY {_order_by(order)}
            """,
            ids,
        )
        return [_to_row(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        tags: Sequence[str] = (),
        after: date | None = None,
        before: date | None = None,
        limit: int = 50,
    ) -> list[SearchHit]:
        """全文検索（spec §7.3）。`tags` と期間で絞れる（提案 3 / 案 A）。

        trigram は 3 文字単位で索引するため、**2 文字以下のクエリは構造上
        ヒットしない**。「人事」「経費」のような 2 文字の日本語は日常的に
        検索されるので、短いクエリでは FTS を諦めて LIKE に切り替える。

        **タグは全部満たすものだけ**（AND）。OR だと、絞ったのに件数が
        増えて驚く。タグ表は先祖まで展開して入れているので、`仕事` で
        `仕事/会議` も当たる。

        言葉が空で絞り込みだけのときは、そのノートを並べる（絞り込みだけを
        書いたのに何も出ないと、打ち間違えたように見える）。

        **期間は両端を含む**（`after:2026-08-01` は 8/1 も出す）。区切りとして
        打つ日付は含むほうが素直。
        """
        text = query.strip()
        narrow = bool(tags) or after is not None or before is not None
        if not text:
            return self._search_filters(tags, after, before, limit=limit) if narrow else []
        if len(text) < MIN_TRIGRAM_QUERY:
            return self._search_like(text, tags=tags, after=after, before=before, limit=limit)
        return self._search_fts(text, tags=tags, after=after, before=before, limit=limit)

    def _date_clause(self, after: date | None, before: date | None) -> tuple[str, list[str]]:
        """更新日の範囲。**両端を含む。** 区切りとして打つ日付は含むほうが素直。

        `substr(modified_at, 1, 10)` で日付の部分だけを見る。`modified_at` は
        時刻と時差まで入った文字列なので、そのまま比べると
        `before:2026-08-20` が同じ日の 10:00 を落とす。
        """
        clause = ""
        params: list[str] = []
        if after is not None:
            clause += " AND substr(notes.modified_at, 1, 10) >= ?"
            params.append(after.isoformat())
        if before is not None:
            clause += " AND substr(notes.modified_at, 1, 10) <= ?"
            params.append(before.isoformat())
        return clause, params

    def _tag_clause(self, tags: Sequence[str]) -> tuple[str, list[str]]:
        """タグの AND 条件。渡されなければ空。

        1 タグにつき 1 つの `EXISTS` を並べる。`IN` + `COUNT` でも書けるが、
        こちらのほうが `idx_tags_tag` をそのまま使える。
        """
        if not tags:
            return "", []
        clause = "".join(
            " AND EXISTS (SELECT 1 FROM tags WHERE tags.note_id = notes.id AND tags.tag = ?)"
            for _ in tags
        )
        return clause, list(tags)

    def _search_filters(
        self,
        tags: Sequence[str],
        after: date | None,
        before: date | None,
        *,
        limit: int,
    ) -> list[SearchHit]:
        """言葉なしで絞り込みだけ。並びは一覧と同じ（ピン留め → 更新順）。"""
        tag_clause, tag_params = self._tag_clause(tags)
        date_clause, date_params = self._date_clause(after, before)
        rows = self._connection.execute(
            f"""
            SELECT notes.id AS id, notes.path AS path, notes.title AS title,
                   notes.preview AS snippet
            FROM notes
            WHERE notes.trashed = 0{tag_clause}{date_clause}
            ORDER BY notes.pinned DESC, notes.modified_at DESC
            LIMIT ?
            """,
            [*tag_params, *date_params, limit],
        )
        return [_to_hit(row) for row in rows]

    def _search_fts(
        self,
        text: str,
        *,
        tags: Sequence[str] = (),
        after: date | None = None,
        before: date | None = None,
        limit: int,
    ) -> list[SearchHit]:
        clause, tag_params = self._tag_clause(tags)
        date_clause, date_params = self._date_clause(after, before)
        rows = self._connection.execute(
            f"""
            SELECT notes.id AS id, notes.path AS path, notes.title AS title,
                   snippet(notes_fts, 1, ?, ?, '…', 12) AS snippet
            FROM notes_fts
            JOIN notes ON notes.id = notes_fts.note_id
            WHERE notes_fts MATCH ? AND notes.trashed = 0{clause}{date_clause}
            ORDER BY rank
            LIMIT ?
            """,
            [HIGHLIGHT_START, HIGHLIGHT_END, _quote(text), *tag_params, *date_params, limit],
        )
        return [_to_hit(row) for row in rows]

    def _search_like(
        self,
        text: str,
        *,
        tags: Sequence[str] = (),
        after: date | None = None,
        before: date | None = None,
        limit: int,
    ) -> list[SearchHit]:
        """短いクエリ用のフォールバック。

        走査対象はタイトルとプレビューだけ（spec §7.3）。本文まで LIKE で
        舐めると件数に比例して遅くなるため、G4（200ms）を守れなくなる。
        """
        # `%` と `_` は LIKE のワイルドカード。エスケープしないと
        # 「%」の 1 文字検索が全件に一致する（打った文字をそのまま探す）
        pattern = f"%{_like_escape(text)}%"
        clause, tag_params = self._tag_clause(tags)
        date_clause, date_params = self._date_clause(after, before)
        rows = self._connection.execute(
            rf"""
            SELECT notes.id AS id, notes.path AS path, notes.title AS title,
                   notes.preview AS snippet
            FROM notes
            WHERE notes.trashed = 0
              AND (notes.title LIKE ? ESCAPE '\' OR notes.preview LIKE ? ESCAPE '\')
              {clause}{date_clause}
            ORDER BY notes.pinned DESC, notes.modified_at DESC
            LIMIT ?
            """,
            [pattern, pattern, *tag_params, *date_params, limit],
        )
        return [_to_hit(row) for row in rows]


def _quote(text: str) -> str:
    """FTS5 のクエリ構文として解釈させず、そのまま部分一致させる。

    引用符で囲まないと `AND` や `*` が演算子になり、ユーザーが打った
    記号でエラーになる。
    """
    escaped = text.replace('"', '""')
    return f'"{escaped}"'


def _mtime_stamp(mtime_ns: int) -> str:
    """mtime を front matter の modified と比べられる形にする。

    日付の絞り込みは先頭 10 文字（YYYY-MM-DD）の文字列比較なので、
    その形で始まってさえいればよい。
    """
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000).isoformat(timespec="seconds")


def _like_escape(text: str) -> str:
    """`LIKE` のワイルドカードを打った文字として扱わせる。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def note_key(note: Note, root: Path) -> str:
    """front matter に `id` があればそれ、無ければ相対パスから作る。

    外部エディタで作られたノートには front matter が無い。索引の主キーは
    必ず要るので、パスから安定した ID を合成する。

    **版の履歴（ADR-0023）も同じ鍵を使う。** 別々に決めると、索引と履歴で
    「同じノート」の判定がずれる。
    """
    return note.id or f"path:{note.relative_to(root)}"


# 旧名。索引の中からはこちらで呼ばれている
_note_id = note_key


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
