"""検索インデックス（spec §7.3）。

**このファイルは捨ててよいキャッシュ（R9）。** 消しても `.md` から完全に
再構築できること。真実は常にファイル側にある。ここに DB にしか無い情報を
置いてはいけない。

日本語検索の要は `tokenize='trigram'`。`unicode61` だと日本語の 1 文が
まるごと 1 トークンになり、部分一致で引けなくなる。
"""

import functools
import logging
import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from hitofude.core import tags as tag_utils
from hitofude.core import wikilink
from hitofude.core.document import Note, note_key, searchable_text

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
# 残り続ける。2 で `links`（E-6）を足し、3 でプレビューからマーカーを外し、
# 4 で `links.relation`（M-3 の続柄）を足した
SCHEMA_VERSION = 5
"""5: 索引の写しを NFKC に寄せた（全角と半角を跨いで引ける）。
**上げると作り直される。** 寄せ方を変えたら索引の中身も変わるので、
古いままだと全角のノートが引けない。"""

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
    trashed      INTEGER NOT NULL DEFAULT 0,
    -- 短い言葉（2 文字以下）の照合用。題名と抜粋を NFKC に寄せた写し。
    -- **見せる字は変えない**（一覧には書いたとおりの全角で出す）ので、
    -- 表示用とは別に持つ
    search_key   TEXT NOT NULL DEFAULT ''
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
    -- 続柄（M-3）。無印は空文字。**主キーに入れる** — 入れないと
    -- 同じ相手を別の関係で指したときに片方が黙って消える
    relation TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (note_id, target, relation)
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


# ルートを表すフォルダの合図（ユーザー要望）。`sanitize_filename` が
# 先頭のドットを剥ぐので、実在のフォルダ名がこれと衝突することはない
ROOT_FOLDER = "."


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


@functools.cache
def _expected_definitions() -> dict[str, str]:
    """`SCHEMA` どおりに作ったときの定義。**書き写さない**（ずれると気づけない）。"""
    probe = sqlite3.connect(":memory:")
    try:
        probe.executescript(SCHEMA)
        return IndexDb._definitions(probe)
    finally:
        probe.close()


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
        self._migrate()

    def _migrate(self) -> None:
        """古い作りの索引を捨てて作り直す。

        **表ごと作り直す。** 中身だけ消していたら列を足したときに直らなかった
        （ユーザー報告 2026-08-23）——`CREATE TABLE IF NOT EXISTS` は既にある
        表を作り変えないので、`links` が 2 列のまま残り、`relation` を書こうと
        して毎回失敗し、**索引が空のままになった**（一覧からノートが全部
        消えて見えた。ファイルは無事）。

        **版だけでは足りない。** 版 4 を古い形のまま出してしまったので、
        使っている人の索引は「版は 4、形は 3」になっている。形も見る。

        **`SCHEMA` を流す前にここを通す**（利用者報告 2026-09-05）。以前は
        `__init__` が先に流していたので、**知らない形**の索引があると
        `CREATE TABLE IF NOT EXISTS` が素通りし、続く
        `CREATE INDEX ... ON notes(modified_at DESC)` が無い列を指して
        `sqlite3.OperationalError` で**起動ごと落ちた**。実機では、同じ
        保管フォルダを共有する作り直し版（Tauri/Rust）が置いた索引で踏んだ。

        古い形だけを相手にしていたのが誤りで、**こちらが知らない形もある**。
        版の大小も当てにしない——別のアプリの版はこちらと無関係に進む。
        「今の形と一致するか」だけを見て、違えば作り直す。

        次の `sync()` が全ファイルを読み直して埋める（R9）。真実はファイル側に
        あるので、ここで失うものは無い。
        """
        if self.schema_version() == SCHEMA_VERSION and self._shape_matches():
            return
        logger.info("索引の作りが違うので作り直す（版 %s）", self.schema_version())
        self._rebuild_schema()
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()

    def _shape_matches(self) -> bool:
        """表の形が今の作りと合っているか。**定義そのものを突き合わせる。**

        列の一覧ではなく `sqlite_master.sql` を比べる——列が合っていても
        **主キーが古い**ことがあり（M-3 で主キーを変えた）、それだと同じ
        相手を別の続柄で指したときに片方が黙って消える。
        """
        return self._definitions(self._connection) == _expected_definitions()

    @staticmethod
    def _definitions(connection: sqlite3.Connection) -> dict[str, str]:
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type IN ('table', 'index') AND sql IS NOT NULL"
            " AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0]: " ".join(str(row[1]).split()) for row in rows}

    def rebuild_in_place(self, vault) -> "SyncResult":
        """索引を作り直す。**ファイルは同じまま**（ユーザー要望の「作り直す」）。

        `rebuild()` はファイルを消して作り直すが、それを背景スレッドで
        やると**UI 側が持っている接続は消えた実体を読み続ける**——作り直した
        のに一覧が空のまま、という壊れ方になる（実測）。同じファイルの上で
        表を作り直せば、開いたままの接続からも新しい中身が見える。

        **捨てるのは索引だけ**（R9 / ADR-0023）。`.md` も
        `.OboeGaki/history/` も触らない。
        """
        self._rebuild_schema()
        return self.sync(vault)

    def _rebuild_schema(self) -> None:
        """表を捨てて作り直す。**形が変わっていても直る**（R9）。"""
        names = [
            row[0]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        # 仮想表（`notes_fts`）を先に落とす。影の表（`notes_fts_data` など）も
        # 一緒に消えるので、後から個別に落とそうとすると無いと言われる
        for name in sorted(names, key=lambda found: found != "notes_fts"):
            self._connection.execute(f'DROP TABLE IF EXISTS "{name}"')
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def reset(self) -> None:
        """索引を空にする。ファイルは触らない（R9）。**テストの道具。**

        本番の「作り直す」はここではなく `rebuild_in_place`（表ごと
        作り直す。中身だけ消す方式は、列を足すマイグレーションで直らない
        ことが分かって退役した——`_migrate` の注記）。残してあるのは、
        テストが「スキーマは正しいがデータが空」という壊れた索引を
        作るのに使うため（R9 の逃げ道そのものの検査に要る）。
        """
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
        note_id = note_key(note, root)
        relative = note.relative_to(root)
        note_id = self._resolve_duplicate_id(note_id, relative, root)
        parsed = note.meta

        self._forget_conflicting(note_id, relative)
        self._connection.execute(
            """
            INSERT INTO notes (id, path, title, preview, created_at, modified_at,
                               mtime_ns, size_bytes, pinned, trashed, search_key)
            VALUES (:id, :path, :title, :preview, :created, :modified,
                    :mtime, :size, :pinned, :trashed, :search_key)
            ON CONFLICT(id) DO UPDATE SET
                path = excluded.path, title = excluded.title, preview = excluded.preview,
                search_key = excluded.search_key,
                modified_at = excluded.modified_at, mtime_ns = excluded.mtime_ns,
                size_bytes = excluded.size_bytes, pinned = excluded.pinned,
                trashed = excluded.trashed
            """,
            {
                "id": note_id,
                "path": relative,
                "title": note.title,
                "preview": note.preview,
                # 照合用。**見せる字はそのまま**で、引くための写しだけ寄せる
                "search_key": unicodedata.normalize("NFKC", f"{note.title}\n{note.preview}"),
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
            "INSERT OR IGNORE INTO links (note_id, target, relation) VALUES (?, ?, ?)",
            [(note_id, target, relation) for target, relation in wikilink.relations(note.text)],
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

    def tags_of(self, note_id: str) -> list[str]:
        """そのノートに付いているタグ（L-3）。"""
        rows = self._connection.execute(
            "SELECT tag FROM tags WHERE note_id = ? ORDER BY tag", (note_id,)
        )
        return [row["tag"] for row in rows]

    def links_of(self, note_id: str) -> list[str]:
        """そのノートが `[[…]]` で指している先の題名（L-3）。"""
        rows = self._connection.execute(
            "SELECT target FROM links WHERE note_id = ? ORDER BY target", (note_id,)
        )
        return [row["target"] for row in rows]

    def relations(self) -> list[str]:
        """使われている続柄の一覧（M-3）。**無印は出さない** — それが普通で、
        空の選択肢が並ぶと邪魔になる。"""
        rows = self._connection.execute(
            """
            SELECT DISTINCT links.relation AS relation
            FROM links JOIN notes ON notes.id = links.note_id
            WHERE links.relation <> '' AND notes.trashed = 0
            ORDER BY links.relation
            """
        )
        return [row["relation"] for row in rows]

    def link_map(self, *, relation: str | None = None) -> dict[str, list[str]]:
        """題名 → その題名が指している先の一覧（M-2 の図が使う）。

        **1 本ずつ引かない。** 深さ 2 でも数十本になり、そのたびに問い合わせると
        図を開くのが遅くなる（`titles()` を足したときと同じ理由）。

        **リンクの無いノートも鍵にする。** 索引にあるかどうかが「まだ無い
        ノート」との違いで、図はそこを見分けて中抜きに描く。
        """
        found: dict[str, list[str]] = {}
        # **絞ってもノートは鍵に残す**（`LEFT JOIN` の条件側に置く）。
        # `WHERE` で絞ると、その続柄を持たないノートが鍵ごと消え、
        # 図の起点を置く場所が無くなる
        rows = self._connection.execute(
            f"""
            SELECT notes.title AS title, links.target AS target
            FROM notes LEFT JOIN links
              ON links.note_id = notes.id
              {"AND links.relation = ?" if relation is not None else ""}
            WHERE notes.trashed = 0
            ORDER BY notes.title, links.target
            """,
            () if relation is None else (relation,),
        )
        for row in rows:
            targets = found.setdefault(row["title"], [])
            # **同じ題名のノートが 2 つ**あることがある（題名は本文から決まる）。
            # 鍵は題名なので、両方の行き先を足し合わせる
            if row["target"] is not None and row["target"] not in targets:
                targets.append(row["target"])
        return found

    def notes_sharing_tags(
        self, tags: list[str], *, order: "SortOrder" = SortOrder.MODIFIED
    ) -> list[NoteRow]:
        """どれか 1 つでも同じタグを持つノート（L-3）。

        **新しい表は増やさない。** 既にある `tags` を引き直すだけなので、
        索引は今まで通り捨てて作り直せる（R9）。
        """
        normalized = [tag_utils.normalize(tag) for tag in tags if tag_utils.normalize(tag)]
        if not normalized:
            return []
        marks = ",".join("?" for _ in normalized)
        rows = self._connection.execute(
            f"""
            SELECT DISTINCT notes.* FROM notes
            JOIN tags ON tags.note_id = notes.id
            WHERE tags.tag IN ({marks}) AND notes.trashed = 0
            ORDER BY {_order_by(order, prefix="notes.")}
            """,
            normalized,
        )
        return [_to_row(row) for row in rows]

    def backlinks(
        self,
        title: str,
        *,
        order: "SortOrder" = SortOrder.MODIFIED,
        relation: str | None = None,
    ) -> list[NoteRow]:
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
            SELECT DISTINCT notes.* FROM notes
            JOIN links ON links.note_id = notes.id
            WHERE links.target = ? COLLATE NOCASE AND notes.trashed = 0
              {"AND links.relation = ?" if relation is not None else ""}
            ORDER BY {_order_by(order, prefix="notes.")}
            """,
            (target,) if relation is None else (target, relation),
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
        """フォルダごとの件数（K-2）。**そのフォルダ直下だけを数える**。

        **ルート（直下）も常に先頭に並べる**（ユーザー要望）。
        数え方はどのフォルダも同じ（直下だけ）で、選んだときに出る
        ノートの数と一致する。

        パスの組み立ては SQL でやらず Python 側で数える。ノート数ぶんの
        文字列操作だが、5,000 件でも数 ms（実測）で、SQL に階層を
        組み込むより読める。
        """
        counts: dict[str, int] = {}
        root_count = 0
        rows = self._connection.execute("SELECT path FROM notes WHERE trashed = 0")
        for row in rows:
            parts = Path(row["path"]).parent.parts
            if not parts:
                root_count += 1
                continue
            # **直下だけを数える。** 親が子のぶんまで数えると、選んだ
            # ときに出る件数と食い違う（ユーザー指摘）
            folder = "/".join(parts)
            counts[folder] = counts.get(folder, 0) + 1
        found = [FolderCount(folder=ROOT_FOLDER, count=root_count)]
        found.extend(FolderCount(folder=folder, count=counts[folder]) for folder in sorted(counts))
        return found

    def notes_in_folder(
        self, folder: str, *, order: "SortOrder" = SortOrder.MODIFIED
    ) -> list[NoteRow]:
        """そのフォルダ**直下**のノート（ユーザー要望）。

        **子孫は含めない。** ルートだけ非再帰でサブフォルダは再帰、と
        いう食い違いがあった。Finder と同じで、選んだフォルダの中身が
        出るほうが読める。

        **区切りまで含めて前方一致する。** `仕事` で `仕事場/` を拾わない。
        """
        if folder.strip("/") in ("", ROOT_FOLDER):
            rows = self._connection.execute(
                f"""
                SELECT * FROM notes
                WHERE trashed = 0 AND instr(path, '/') = 0
                ORDER BY {_order_by(order)}
                """
            )
            return [_to_row(row) for row in rows]

        prefix = f"{folder.strip('/')}/"
        # **LIKE ではなく範囲で引く**（コードレビュー指摘）。既定の LIKE は
        # 大文字小文字を区別せず、BINARY の UNIQUE 索引と噛み合わないため
        # 常に全表走査になる（EXPLAIN で実測）。前方一致は
        # `path >= '仕事/' AND path < '仕事0'`（'/' の次の文字が '0'）で
        # 表せて、索引をそのまま使える。ワイルドカードが無いので
        # エスケープも要らない
        upper = prefix[:-1] + chr(ord(prefix[-1]) + 1)
        # 範囲で索引を使い（前方一致）、そのうえで**残りに区切りが無い**
        # ものだけを採る = 直下のノート。substr の開始は 1 始まり
        rows = self._connection.execute(
            f"""
            SELECT * FROM notes
            WHERE trashed = 0 AND path >= ? AND path < ?
              AND instr(substr(path, ?), '/') = 0
            ORDER BY {_order_by(order)}
            """,
            (prefix, upper, len(prefix) + 1),
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
        （ピン留めが先頭）。

        絞り込みだけ（言葉が空）なら**上限は無い**。言葉で当てる場合は
        `_MATCH_LIMIT` 件までで、パレットの 50 件よりは多く出す。
        上限があるのは id を `IN` 句へ並べるため（SQLite の変数の上限）。
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
        # **索引と同じ形に寄せる**（NFKC。`document.searchable_text` と対）。
        # 片方だけだと「全角で書いたノートは全角でしか引けない」が残る
        text = unicodedata.normalize("NFKC", query.strip())
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
              AND notes.search_key LIKE ? ESCAPE '\'
              {clause}{date_clause}
            ORDER BY notes.pinned DESC, notes.modified_at DESC
            LIMIT ?
            """,
            [pattern, *tag_params, *date_params, limit],
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


def merge_folders(counts: list[FolderCount], folders: list[str]) -> list[FolderCount]:
    """索引の件数（`folder_tree`）とディスクのフォルダ（`Vault.folders`）を合わせる。

    **存在はディスクが決め、件数は索引が決める。** 索引だけを見ると
    空フォルダが出ず「作ったのに現れない」になり、ディスクだけを見ると
    件数が出ない。索引にあってディスクに無いものは出さない（R9: 真実は
    ファイル側）。ルートは常に先頭。
    """
    known = {count.folder: count.count for count in counts}
    found = [FolderCount(folder=ROOT_FOLDER, count=known.get(ROOT_FOLDER, 0))]
    found.extend(
        FolderCount(folder=folder, count=known.get(folder, 0)) for folder in sorted(folders)
    )
    return found


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

    `.OboeGaki/index.sqlite` を消しても `.md` から完全に復元できることを、
    この関数の存在と回帰テストで保証する。
    """
    db_path.unlink(missing_ok=True)
    for extra in (".sqlite-wal", ".sqlite-shm"):
        db_path.with_suffix(extra).unlink(missing_ok=True)
    with IndexDb(db_path) as db:
        return db.sync(vault)
