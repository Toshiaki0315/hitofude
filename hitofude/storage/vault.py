"""保管フォルダ（vault）の走査と CRUD（spec §7.1, §7.6）。

```
HitofudeNotes/
├── 会議メモ.md          ← ノートは vault 直下のフラット構成
├── attachments/         ← 画像等
├── templates/           ← 雛形（E-4）。ノートとしては読まない
├── .trash/              ← 削除したノート（既定 30 日で自動消去）
└── .OboeGaki/          ← アプリの管理領域（索引と履歴。ADR-0034）
```

**フォルダ階層で分類しない。** 分類はタグで行う（§7.1）。ユーザーが手で
サブフォルダを作った場合は再帰的に読み込むが、アプリからは作らせない。

`attachments/` と `templates/` は**分類ではなく道具の置き場**なので、
走査から外す（`SKIP_DIRS`）。日次ノートを日付フォルダに分けないのも
同じ理由で、`2026-08-14.md` として vault 直下に置く。
"""

import logging
import os
import re
import shutil
import time
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path

from hitofude.core import frontmatter
from hitofude.core.document import UNTITLED, Note, new_id, path_key, with_title
from hitofude.core.references import attachment_names
from hitofude.core.table import find_table, format_table
from hitofude.core.template import Expanded, daily_title, expand
from hitofude.storage import history
from hitofude.storage.autosave import TEMP_SUFFIX, save_atomic, save_bytes_atomic

logger = logging.getLogger(__name__)

MARKDOWN_SUFFIXES = (".md", ".markdown")
ATTACHMENTS_DIR = "attachments"
TEMPLATES_DIR = "templates"
TRASH_DIR = ".trash"
MANAGED_DIR = ".OboeGaki"
LEGACY_MANAGED_DIR = ".hitofude"
"""旧名（改名 2026-08-27 / ADR-0032）。開くときに一度だけ改名して引き継ぐ。"""


def migrate_managed_dir(root: Path) -> None:
    """旧名 `.hitofude` を `.OboeGaki` へ改名して引き継ぐ（ADR-0032）。

    索引は捨ててよいが、`history/` の版は作り直せない（ADR-0023）ので
    **中身ごと連れて行く**。同一ボリューム内の rename 1 回で原子的。
    両方あるとき（引っ越し済み）は新しい側が正で、旧側は触らない。

    **管理フォルダに触るすべての入口がこれを先に通す**こと。起動は
    ロック（app.acquire_vault_lock）が ensure_layout より先に管理フォルダを
    作るため、ロック側が通さないと「両方ある」扱いになり履歴が旧側に
    取り残される（実機で発覚）。
    """
    legacy = root / LEGACY_MANAGED_DIR
    target = root / MANAGED_DIR
    if legacy.is_dir() and not target.exists():
        legacy.rename(target)


DEFAULT_TRASH_DAYS = 30

# 一時ファイルの拡張子。autosave が正で、こちらは名前を借りるだけ
# （「循環 import 回避で値を持つ」と書かれていたが、38 行目で既に
# autosave を import しており、循環は無い。レビュー 2026-08-25）
# これより古い .tmp はクラッシュの残骸と見なして掃除する（H-1 層 1）
TEMP_SWEEP_AGE_SECONDS = 3600.0
# UNTITLED は core/document.py が持つ（タイトル導出のフォールバックと同じ値）。
# ここからは import で再輸出している（既存の `vault.UNTITLED` 参照のため）

MANUAL_TITLE = "覚書の使い方"
MANUAL_RESOURCE = "manual.md"
# 一度置いたら二度と置き直さない印。ユーザーが消したものを復活させない
SEED_MARKER = "seeded"

# 雛形（E-4）。**ただの `.md`** なので Finder で足しても増やせる
DAILY_TEMPLATE = "日次.md"
DEFAULT_TEMPLATES = (DAILY_TEMPLATE, "議事録.md", "日報.md", "PowerPoint下書き.md")
TEMPLATES_RESOURCE = "templates"
TEMPLATES_MARKER = "templates-seeded"
# 更新前の印は日時しか持っていない。そのとき置かれていた雛形は分かっている
# ので、その分は置き直さない（**手で消したものを復活させない**）
LEGACY_TEMPLATES = (DAILY_TEMPLATE, "議事録.md", "日報.md")

# ファイル名の上限は 255 バイト。日本語は 1 文字 3 バイトなので余裕を取る
MAX_FILENAME_BYTES = 200

# macOS で使えない、または使うと事故る文字。`/` はパス区切り、`:` は Finder が嫌う
_ILLEGAL_RE = re.compile(r"[/:\\]")
_WHITESPACE_RE = re.compile(r"\s+")

# macOS が勝手に置くファイル。フォルダが「空か」の判定では無視する
_IGNORED_FILE = ".DS_Store"

# 走査から外すフォルダ。**`storage/watcher.py` もこれを使う。**
# 2 か所に書くと、片方だけ直したときに「一覧には出ないのに索引には入る」
# という食い違いが出る（E-4 で実際に起きた）
SKIP_DIRS = frozenset({TRASH_DIR, MANAGED_DIR, ATTACHMENTS_DIR, TEMPLATES_DIR})

DEFAULT_ATTACHMENT_SUFFIX = ".png"
# 拡張子に通す文字。パス区切りや空白を持ち込ませない
_SUFFIX_RE = re.compile(r"[^a-z0-9]")


def attachment_suffix(raw: str) -> str:
    """貼り付け元から来た拡張子を、ファイル名に使える形へ直す。

    クリップボードやドロップ元の文字列をそのまま繋ぐと、`../` や空白で
    attachments の外へ書ける。英数字だけ残す。
    """
    cleaned = _SUFFIX_RE.sub("", raw.lower().rsplit(".", 1)[-1])
    return f".{cleaned}" if cleaned else DEFAULT_ATTACHMENT_SUFFIX


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


def _is_same_file(candidate: Path, other: Path | None) -> bool:
    """同じ実体を指しているか。**名前ではなく実体で見る**（S-3）。

    macOS の既定（APFS）は大文字小文字を区別しないので、`Meeting.md` と
    `meeting.md` は**同じファイル**。名前を比べると別物に見える。
    """
    if other is None:
        return False
    try:
        return candidate.samefile(other)
    except OSError:
        return False  # 片方が無い・読めない。別物として扱えば安全側


def unique_path(
    directory: Path, stem: str, suffix: str = ".md", *, ignoring: Path | None = None
) -> Path:
    """重複しないパスを返す。衝突したら `-2`, `-3` を付ける（spec §7.1）。

    `ignoring` に**動かそうとしている当人**を渡すと、それは衝突と数えない。
    渡さないと、大文字小文字だけ変えた改名で**自分自身を衝突相手と見て**
    `-2` が付く（S-3。APFS は区別しないため `meeting.md` が「既に在る」）。
    """
    candidate = directory / f"{stem}{suffix}"
    index = 2
    while candidate.exists() and not _is_same_file(candidate, ignoring):
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def _read_resource(name: str) -> str | None:
    """同梱リソースを読む。無くても起動を止めない。"""
    from importlib.resources import files

    try:
        return (files("hitofude.resources") / name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None


@dataclass(frozen=True, slots=True)
class NewNote:
    """作ったノートと、書き始める場所（E-4）。"""

    note: Note
    cursor: int | None = None
    """`{{cursor}}` があった位置。**front matter を含む先頭からの文字数**
    （エディタの位置とソースの位置は 1:1。R4）。既にあるノートを開いた
    ときは None。"""


def _with_aligned_tables(filled: Expanded) -> Expanded:
    """作ったノートの表の桁を揃える（ユーザー報告）。

    **雛形が揃っていなくても、できたノートは揃っている**ようにする。
    罫線は 1 行目の `|` の位置に引くので、揃っていない表は開いた瞬間に
    ずれて見える（行を離れれば自動整形が走るが、それまで読めない）。

    **雛形そのものは書き換えない**（R1。直すのは作ったノートだけ）。
    """
    lines = filled.text.split("\n")
    number = 0
    changed = False
    while number < len(lines):
        found = find_table(lines, number)
        if found is None or found[0] != number:
            number += 1
            continue
        start, end = found
        formatted = format_table(lines[start:end])
        if formatted != lines[start:end]:
            lines[start:end] = formatted
            changed = True
        number = end

    if not changed:
        return filled
    # 桁を揃えると文字数が変わる。**キャレットの位置は捨てる**
    # （ずれた位置に置くより、本文の頭から書き始めるほうがまし）
    return Expanded("\n".join(lines), None)


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------- レイアウト

    def ensure_layout(self) -> None:
        migrate_managed_dir(self.root)
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

    @property
    def templates_dir(self) -> Path:
        return self.root / TEMPLATES_DIR

    # ----------------------------------------------------------------- 走査

    def scan(self) -> Iterator[Path]:
        """vault 内の `.md` を返す。`.trash` と管理フォルダは除く。"""
        if not self.root.is_dir():
            return
        yield from self._walk(self.root, frozenset({self.root.resolve()}))

    def _walk(self, directory: Path, ancestors: frozenset[Path]) -> Iterator[Path]:
        # **1 つのフォルダで走査ごと止めない**（レビュー指摘）。索引の同期は
        # まるごと 1 回の処理なので、途中で例外が出ると他の正常なノートまで
        # 索引に入らない（`folders()` は既にこうしている）
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            logger.warning("読めないフォルダを飛ばす: %s", directory)
            return
        for entry in entries:
            # **保管フォルダの外へ出るリンクは辿らない。** 辿ると外のノートが
            # 索引に入り、編集やゴミ箱移動の対象になる。ゴミ箱移動はボリュームを
            # またぐこともあり、vault が自己完結しなくなる
            if entry.is_symlink() and not self._inside(entry):
                continue
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                # **祖先へ戻るリンクは辿らない。** `vault/loop -> vault` のような
                # 中を指すリンクは _inside を通るため、これが無いと同じノートを
                # 別パスで重複して yield し続ける。祖先だけを見るのは、兄弟への
                # 別名リンク（今まで通り辿る）を巻き込まないため
                real = entry.resolve()
                if real in ancestors:
                    continue
                yield from self._walk(entry, ancestors | {real})
            elif entry.suffix.lower() in MARKDOWN_SUFFIXES:
                yield entry

    def _inside(self, entry: Path) -> bool:
        """リンクを辿った先が保管フォルダの中に留まるか。

        `resolve()` はリンクを辿るので、外へ出るものはここで落ちる。
        判定の規則は `core/paths.py` と同じ（外を指す参照は扱わない）。
        """
        try:
            return entry.resolve().is_relative_to(self.root.resolve())
        except OSError:
            return False

    # ----------------------------------------------------------------- 読み書き

    def read(self, path: Path) -> Note:
        return Note.read(path)

    def writable_folder(self, folder: str | None = None) -> Path:
        """書き込んでよい場所か確かめて、無ければ作る（レビュー指摘）。

        `folder` は **vault からの相対（str）**。`None` と空文字は直下。
        フォルダの言葉はこれに統一した（レビュー 2026-08-25。move_note /
        create_folder 系と、索引・サイドバー・履歴の鍵がすべて相対 str）。

        **`Vault` の外で置き場を決めさせない。** ドロップの取り込みが
        ここを通らずに直にコピーしていたため、予約フォルダ（`attachments`
        など）を指すリンクを選ぶと、その中へノートが入っていた（実測）。
        一覧にも索引にも出ない場所なので、書いた人からは消えたように見える。
        """
        cleaned = self._folder_relative(self._relative_str(folder))
        target = self._writable_folder(self.root / cleaned) if cleaned else self.root
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _relative_str(folder: str | None) -> str:
        """`folder` 引数の受付。**絶対 Path は型で大きく断る**（移行の
        失敗を黙らせない。旧 API は絶対 Path を取っていた）。"""
        if folder is None:
            return ""
        if isinstance(folder, Path):
            raise TypeError(f"folder は vault からの相対（str）で渡す: {folder}")
        return folder

    def create(self, title: str, text: str | None = None, *, folder: str | None = None) -> Note:
        """新しいノートを作る。front matter に ULID と日時を入れる（spec §7.2）。

        `folder` は vault からの相対（`仕事/2026`）。渡すとそこに作る
        （既定は直下）。複製が「元と同じ場所」に作るために使う（K-1）。
        **vault の外には作らせない**（渡し間違いを黙って通すと、
        保管フォルダの外にノートが散る）。
        """
        self.ensure_layout()
        target = self.writable_folder(folder)
        path = unique_path(target, sanitize_filename(title))

        parsed = frontmatter.split(text or "")
        timestamp = _now()
        # **id はこちらが勝つ。** 持ち込まれた front matter（複製・取り込み）
        # の id を通すと 2 つのノートが同じ ULID になり、版の履歴（ADR-0023、
        # id が鍵）が混線して「この版に戻す」が別ノートの内容を書き込む。
        # created / modified は持ち込みを尊重する（取り込みで日付を保つ）
        meta = {
            "created": timestamp,
            "modified": timestamp,
            **parsed.meta,
            "id": new_id(),
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

    def set_pinned(self, path: Path, pinned: bool) -> Note:
        """front matter の `pinned` を書き換える。

        **`modified` は触らない。** ピン留めは本文の編集ではないので、
        一覧の並び順が動くのは筋が悪い。

        外すときは `pinned: false` を残さず鍵ごと消す。書いていないことを
        ファイルに書かないため、ピン留め → 解除でファイルが元の姿へ戻る。

        front matter が壊れていても本文は必ず残す（G3）。`split()` が
        壊れたメタデータを空として返すので、ここでは何も特別扱いしない。
        """
        parsed = frontmatter.split(path.read_text(encoding="utf-8"))
        meta = dict(parsed.meta)
        if pinned:
            meta["pinned"] = True
        else:
            meta.pop("pinned", None)

        save_atomic(path, frontmatter.join(meta, parsed.body))
        return self.read(path)

    # --------------------------------------------------------------- 添付

    def add_attachment(self, data: bytes, suffix: str = DEFAULT_ATTACHMENT_SUFFIX) -> Path:
        """画像などを `attachments/` へ置き、その場所を返す（spec §7.1）。

        名前は時刻から作る。並べたときに貼った順になるほうが、後から
        探すときに手がかりになる。同名があれば `-2` を付けて上書きしない。
        """
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        stem = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = unique_path(self.attachments_dir, stem, attachment_suffix(suffix))
        save_bytes_atomic(path, data)
        return path

    def attachment_link(self, path: Path) -> str:
        """本文へ挿す Markdown。**vault からの相対パス**で書く。

        絶対パスで書くと、保管フォルダごと移したときに全部切れる。
        素の `.md` として他のアプリでも読めることを保つ（G3）。
        """
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            relative = Path(ATTACHMENTS_DIR) / path.name
        return f"![]({relative.as_posix()})"

    # ----------------------------------------------------------------- 移動

    def create_folder(self, folder: str) -> Path:
        """フォルダを作る（ユーザー要望）。作った場所を返す。

        `folder` は vault からの相対（`日報/2026`）。ADR-0024 では
        「移動の副産物としてのみ作る」としていたが、空フォルダも
        サイドバーに出すようにしたので、先に作って後で入れる順序も
        通るようになった。

        既にあるときは `FileExistsError`。黙って受けると「作った」の
        知らせが嘘になる（別の場所を作ったと誤解させる）。
        """
        cleaned = self._folder_relative(folder)
        if not cleaned:
            raise ValueError("フォルダの名前が空")
        target = self._writable_folder(self.root / cleaned)
        if target.exists():
            raise FileExistsError(target)
        target.mkdir(parents=True)
        return target

    def rename_folder(self, folder: str, name: str) -> Path:
        """フォルダの名前を変える（ユーザー要望）。新しい場所を返す。

        **中身は触らない。** ディレクトリの名前を変えるだけなので、中の
        ノートは 1 バイトも変わらない（front matter の id も、履歴の鍵も
        無傷）。**親も変えない**（動かすのは「フォルダへ移動」の仕事）。

        既に同じ名前があれば `FileExistsError`。黙って中身が合流すると、
        どちらのノートだったのか分からなくなる。
        """
        cleaned = self._folder_relative(folder)
        if not cleaned:
            raise ValueError("フォルダの名前が空")
        source = self._writable_folder(self.root / cleaned)
        if not source.is_dir():
            raise ValueError(f"フォルダが無い: {folder}")

        # **空は先に断る。** `sanitize_filename("")` は「無題」を返すので、
        # 通すと打ち間違いが「無題」というフォルダになる
        typed = name.strip()
        if not typed:
            raise ValueError("新しい名前が空")
        # 名前は 1 段ぶん。`/` を打たれても階層は増やさない（移動ではない）
        new_name = sanitize_filename(typed.replace("/", "-"))
        target = source.parent / new_name
        if target == source:
            return source
        if target.exists():
            raise FileExistsError(target)
        self._writable_folder(target)  # 予約フォルダの名前は使わせない
        source.rename(target)
        # **フォルダ名もパスの一部。** 中のノートのうち id を持たないものは
        # 鍵が変わるので、版の置き場も一緒に付け替える
        before = source.relative_to(self.root).as_posix()
        after = target.relative_to(self.root).as_posix()
        for note_path in sorted(target.rglob("*.md")):
            moved = note_path.relative_to(self.root).as_posix()
            self._follow_history(before + moved[len(after) :], note_path)
        return target

    def delete_folder(self, folder: str) -> Path:
        """フォルダを消す（ユーザー要望）。消した場所を返す。

        **ノートが 1 つでも入っていたら消さない**（`ValueError`）。
        フォルダの削除にゴミ箱は無いので、中身ごと消える操作は用意
        しない。空のフォルダ（中が空フォルダだけ、も含む）だけを消す。
        macOS が置く `.DS_Store` は空の判定で無視する。
        """
        cleaned = self._folder_relative(folder)
        if not cleaned:
            raise ValueError("フォルダの名前が空")
        target = self._writable_folder(self.root / cleaned)
        if not target.is_dir():
            raise ValueError(f"フォルダが無い: {folder}")

        leftovers = [
            entry for entry in target.rglob("*") if entry.is_file() and entry.name != _IGNORED_FILE
        ]
        if leftovers:
            raise ValueError(f"中にノートが残っている: {folder}")
        shutil.rmtree(target)
        return target

    def folders(self) -> list[str]:
        """vault の中のフォルダ（vault からの相対・名前順）。

        **ディスクから引く。** 索引（ノートのパス）から作ると空フォルダが
        見えず、「作ったのに出てこない」になる。除くものは `scan()` と
        同じ（予約フォルダ・隠しフォルダ・外へ出るリンク）。
        """
        if not self.root.is_dir():
            return []
        found: list[str] = []
        self._walk_folders(self.root, frozenset({self.root.resolve()}), found)
        return sorted(found)

    def _walk_folders(self, directory: Path, ancestors: frozenset[Path], found: list[str]) -> None:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            if entry.is_symlink() and not self._inside(entry):
                continue
            real = entry.resolve()
            if real in ancestors:
                continue  # 祖先へ戻るリンク（`scan` と同じ理由）
            found.append(entry.relative_to(self.root).as_posix())
            self._walk_folders(entry, ancestors | {real}, found)

    def _folder_relative(self, folder: str) -> str:
        """受け取ったフォルダ名を vault からの相対へ整える。

        **生の名前で先に弾く。** `sanitize_filename` は先頭のドットを
        剥ぐので、後で調べると `.trash` が `trash` に化けてすり抜ける。
        """
        raw_parts = [part.strip() for part in folder.split("/") if part.strip()]
        if any(part == ".." for part in raw_parts):
            raise ValueError(f"vault の外には出られない: {folder}")
        if raw_parts and (raw_parts[0] in SKIP_DIRS or raw_parts[0].startswith(".")):
            raise ValueError(f"予約フォルダは使えない: {folder}")
        return "/".join(sanitize_filename(part) for part in raw_parts)

    def move_note(self, path: Path, folder: str) -> Path:
        """ノートをフォルダへ移す（K-3 / ADR-0024）。移した先を返す。

        `folder` は vault からの相対（`仕事/2026`）。空文字は直下。
        **無いフォルダはここで作られる**（「新しいフォルダ」の入口は
        移動だけ。空フォルダは索引由来のツリーに見えないため）。

        **本文は書き換えない（R1）。** 添付リンクは vault ルート基準で
        解決するので、どこへ動いても表示と書き出しは壊れない。
        移動で空になった元のフォルダは掃除する。
        """
        if not self._inside(path):
            raise ValueError(f"保管フォルダの外: {path}")
        cleaned = self._folder_relative(folder)
        destination = self._writable_folder(self.root / cleaned if cleaned else self.root)
        destination.mkdir(parents=True, exist_ok=True)

        target = unique_path(destination, path.stem, path.suffix)
        if target.parent == path.parent:
            return path  # 同じ場所。動かす意味が無い
        before = path.relative_to(self.root).as_posix()
        path.rename(target)
        self._follow_history(before, target)
        # **空になっても元のフォルダは残す**（ユーザー決定 / ADR-0024 追記 2）。
        # フォルダは作るもの・管理するものなので、最後のノートを移した
        # だけで消えると「勝手に無くなった」になる。消すのは
        # `delete_folder`（サイドバーの右クリック）だけ
        return target

    def _prune_empty_dirs(self, start: Path, *, boundary: Path) -> None:
        """空になったフォルダを `boundary` の手前まで遡って消す（K-5）。

        **ゴミ箱の中だけで使う。** ユーザーに見えるフォルダは空でも
        残す（ADR-0024 追記 2）。ゴミ箱の階層は復元のための裏側なので、
        空の殻を残さない。**完全に空のときだけ**消す。
        """
        edge = boundary.resolve()
        probe = start
        while probe.resolve() != edge and self._inside(probe):
            try:
                relative = probe.resolve().relative_to(edge)
            except (OSError, ValueError):
                return
            if not relative.parts:
                return
            try:
                next(probe.iterdir())
                return  # 空ではない
            except StopIteration:
                pass
            except OSError:
                return
            probe.rmdir()
            probe = probe.parent

    def rename(self, path: Path, title: str) -> Path:
        """タイトル変更に合わせてファイル名を変える。

        旧名は `.trash` に残さない（spec §7.1）。リネームは削除ではないため、
        ゴミ箱に増えていくとユーザーが混乱する。

        **元のフォルダに留める**（K-1）。手で作ったサブフォルダに置いた
        ノートが、名前を変えただけで vault 直下へ出ていた。分類したのに
        箱から飛び出す。同名の衝突も**同じフォルダの中だけ**を見る
        （別のフォルダの同名は別のノート）。
        """
        if not self._inside(path):
            # 旧実装は宛先を root 固定で組んでいて構造的に外へ書けなかった。
            # K-1 で path.parent 由来になったぶん、保証を明示する
            raise ValueError(f"保管フォルダの外: {path}")
        folder = path.parent
        stem = sanitize_filename(title)
        if folder / f"{stem}.md" == path:
            return path  # 同じ名前。動かす意味が無い
        # **当人を衝突相手にしない**（S-3）。APFS は大文字小文字を区別しない
        # ので、`Meeting` → `meeting` は「既に在る」ように見えて `-2` が付いた
        target = unique_path(folder, stem, ignoring=path)
        before = path.relative_to(self.root).as_posix()
        path.replace(target)
        self._follow_history(before, target)
        return target

    def _follow_history(self, before: str, after: Path) -> None:
        """版の置き場を新しいパスへ付け替える（コードレビュー指摘 2026-08-24）。

        `id` を持つノートは動いても鍵が変わらない（ADR-0023）。**パスから
        鍵を作っているノートだけ**が対象で、置き場の名前を変えないと
        それまでの版が「別のノートのもの」になって見えなくなる。

        `before` は動かす前の vault からの相対パス。失敗しても保存や移動は
        止めない（版は付随物。ADR-0023 の扱いと同じ）。
        """
        try:
            note = self.read(after)
        except OSError:
            return
        if note.id is not None:
            return
        try:
            history.rekey(
                self.managed_dir / "history",
                path_key(before),
                path_key(note.relative_to(self.root)),
            )
        except OSError:
            logger.warning("版の置き場を移せなかった: %s", after, exc_info=True)

    def _writable_folder(self, folder: Path) -> Path:
        """ノートを作ってよいフォルダとして受け取る。駄目なら `ValueError`。

        **`_inside()` とは別物。** あちらは走査中のリンクを辿るかどうかの
        判定（真偽）で、こちらは書き込み先の受け取り（駄目なら止める）。

        予約フォルダ（.trash / .OboeGaki / templates / attachments）も
        弾く（コードレビュー指摘）。生きたノートがそこへ入ると、走査
        （scan）から見えない迷子になる。
        """
        resolved = Path(folder).expanduser()
        if not self._inside(resolved):
            raise ValueError(f"保管フォルダの外には作れない: {folder}")
        try:
            relative = resolved.resolve().relative_to(self.root.resolve())
        except ValueError:
            relative = Path()
        if relative.parts and relative.parts[0] in SKIP_DIRS:
            raise ValueError(f"予約フォルダには作れない: {folder}")
        return resolved

    def trash(self, path: Path) -> Path:
        """`.trash` へ移す（spec §7.6）。同名があればタイムスタンプを付ける。

        **階層を保って入れる**（K-5）。ゴミ箱を平らにすると「どこに
        いたか」を誰も覚えておらず、戻すと全部 vault 直下に出ていた。
        .trash/ の中に同じ階層を作れば、ファイル自身が場所を覚えている
        （真実をファイル側に置く。R1 の精神）。
        """
        relative = self._relative_to(path, self.root, "保管フォルダの外は捨てられない")
        if relative.parts and relative.parts[0] == TRASH_DIR:
            # 既にゴミ箱の中。動かすと .trash/.trash/ へ入れ子になり、
            # restore() が trash_dir 相対の .trash/x.md を root へ結合する
            # ため二度と戻せなくなる（ゴミ箱表示中のドラッグで踏む。
            # コードレビュー指摘 2026-08-31）。望みの状態は既に満ちている
            return path
        target = self.trash_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = target.parent / f"{path.stem}-{stamp}{path.suffix}"
        path.replace(target)
        # `purge_trash` の期限は「捨ててから」数える。rename は mtime を
        # 変えないので、ここで刻み直さないと古いノートが即座に消える。
        os.utime(target)
        return target

    def _relative_to(self, path: Path, boundary: Path, message: str) -> Path:
        """`boundary` から見た位置。**外なら動かさずに止める**（レビュー指摘）。

        `delete_permanently` には境界の検査があったのに、捨てる・戻すには
        無かった。無いと、呼び出し側の誤りや**これから足す機能が
        ユーザーの任意のファイルを黙って移動できてしまう**。

        字句上の判定ではなく実体で見る（`.trash/../大事.md` を通さない）。
        """
        try:
            return path.resolve().relative_to(boundary.resolve())
        except (OSError, ValueError) as error:
            raise ValueError(f"{message}: {path}") from error

    def restore(self, path: Path) -> Path:
        """ゴミ箱から**元のフォルダへ**戻す（K-5）。

        .trash/ の中の位置がそのまま元の位置。フォルダが消えていたら
        作り直す（捨てる前には在ったのだから、戻すのに要る）。
        K-5 より前の平らなゴミ箱（.trash 直下）は今まで通り直下へ。
        """
        relative = self._relative_to(path, self.trash_dir, "ゴミ箱の中だけ戻せる")
        destination = self.root / relative.parent
        destination.mkdir(parents=True, exist_ok=True)
        target = unique_path(destination, path.stem, path.suffix)
        path.replace(target)
        # ゴミ箱の中に空の殻を残さない
        self._prune_empty_dirs(path.parent, boundary=self.trash_dir)
        return target

    # --------------------------------------------------------------- 片づけ

    def unused_attachments(self) -> list[Path]:
        """どのノートからも指されていない添付（E-5）。名前順。

        **広く数える。** 数え漏らしはそのまま画像の消失になるので、
        ゴミ箱の中のノート（戻したときに絵が要る）も、雛形も、
        サブフォルダのノートも見る。読めないファイルは飛ばす
        （1 つのせいで片づけられなくなるほうが困る）。

        `attachments/` 直下のファイルだけを対象にする。人が自分で作った
        サブフォルダと隠しファイル（`.DS_Store`）は**こちらの持ち物では
        ないので触らない**。
        """
        if not self.attachments_dir.is_dir():
            return []

        used: set[str] = set()
        for path in self._all_markdown():
            try:
                used |= attachment_names(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                logger.warning("読めないので参照を数えられなかった: %s", path)

        return sorted(
            (
                path
                for path in self.attachments_dir.iterdir()
                if path.is_file() and not path.name.startswith(".") and path.name not in used
            ),
            key=lambda path: path.name,
        )

    def _all_markdown(self) -> Iterator[Path]:
        """参照を数える対象。**走査（`scan`）より広い。**

        `scan()` はノート一覧のためのもので、ゴミ箱と雛形を外している。
        こちらは「消してよいか」の判定なので、そこも見る必要がある。
        """
        yield from self.scan()
        for directory in (self.trash_dir, self.templates_dir):
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES:
                    yield path

    def trash_attachments(self, paths: list[Path]) -> list[Path]:
        """添付をゴミ箱へ移す（E-5）。移した先を返す。

        **消さない。** 判定は「本文に名前が出てこない」という消極的なもので、
        取りこぼせば使用中の画像を片づけてしまう。30 日のあいだは
        `.trash/` から戻せる（`purge_trash` が期限を見る）。

        **`attachments/` の中のものしか動かさない。** パスは呼び出し側から
        来るので、ここでもう一度確かめる（ノートを片づけてしまわないため）。
        """
        moved: list[Path] = []
        for path in paths:
            if path.parent != self.attachments_dir or not path.is_file():
                logger.warning("添付ではないので動かさない: %s", path)
                continue
            moved.append(self.trash(path))
        return moved

    # ------------------------------------------------------------- テンプレート

    def templates(self) -> list[Path]:
        """`templates/` にある雛形（E-4）。名前順。

        **走査（`scan`）からは外してある。** 雛形はノートではないので、
        一覧に出ると本物のノートに混ざる（`attachments/` と同じ扱い）。
        """
        if not self.templates_dir.is_dir():
            return []
        return sorted(
            path
            for path in self.templates_dir.iterdir()
            if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES
        )

    def register_template(self, path: Path, name: str, *, overwrite: bool = False) -> Path:
        """ノートを雛形として登録する（ユーザー要望）。置いた場所を返す。

        **front matter は持ち込まない。** `id` や日時は管理情報で、
        雛形から作るノートには `create` が新しく振る。プレースホルダ
        （`{{date}}` 等）は本文の一部なのでそのまま残る。

        同名の雛形があるときは `overwrite` を明示しない限り
        `FileExistsError`。呼び出し側（UI）が上書き確認を出す。
        """
        if not self._inside(path):
            raise ValueError(f"保管フォルダの外: {path}")
        body = frontmatter.split(path.read_text(encoding="utf-8")).body
        # 見出しは {{title}} に差し替える（同梱の雛形と同じ流儀）。元の
        # 題名のままだと、この雛形から作るノートが全部その題名になる
        body = with_title(body, "{{title}}")
        self.ensure_layout()
        target = self.templates_dir / f"{sanitize_filename(name)}.md"
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        save_atomic(target, body)
        return target

    def delete_template(self, path: Path) -> None:
        """テンプレートを消す（ユーザー要望）。

        `templates/` の中のファイルだけを受ける。ノート本体を巻き込まない。
        """
        if not self._inside_templates(path):
            raise ValueError(f"テンプレートではないパス: {path}")
        path.unlink(missing_ok=True)

    def create_from_template(
        self,
        path: Path,
        *,
        title: str | None = None,
        now: datetime | None = None,
        folder: str | None = None,
    ) -> NewNote:
        """雛形から新しいノートを作る（E-4）。

        **雛形の front matter は持ち込まない。** 写すと `id` が重なり、
        索引の上では 2 つのノートが同じものになる（片方が消えたように見える）。

        題名を省いたときは雛形の名前を使う。「議事録」から作ったノートが
        「無題」になるより、あとで直すぶんだけ手が少ない。
        """
        name = title or path.stem
        filled = self.expand_template(path, title=name, now=now)
        note = self.create(name, filled.text, folder=folder)
        return NewNote(note, self._cursor_in(note, filled))

    def expand_template(
        self,
        path: Path,
        *,
        title: str,
        now: datetime | None = None,
    ) -> Expanded:
        """雛形を読んで印を埋め、本文として使える形にする。

        **新規作成と差し込み（U-6）で同じ支度を通す**（レビュー指摘
        2026-08-31）。片方だけ `expand` を直に呼ぶと、front matter が
        本文へ紛れ込み、表の桁も揃わないまま入る。

        - front matter は外す（写すと `id` が重なる）
        - 表の桁を揃える（雛形が揃っていなくても、入る本文は揃える）
        """
        if not self._inside_templates(path):
            # パスは手で編集できる。外のファイルをノートに変えさせない
            raise ValueError(f"テンプレートではないパス: {path}")
        body = frontmatter.split(path.read_text(encoding="utf-8")).body
        filled = expand(body, now=now or datetime.now(), title=title)
        return _with_aligned_tables(filled)

    def daily_note(self, day: datetime | None = None, *, template: str = DAILY_TEMPLATE) -> NewNote:
        """今日のノートを開く。無ければ作る（E-4）。

        **同じ日に何度呼んでも同じノートを返す。** 2 つできると、どちらに
        書いたか分からなくなる。`.md` は vault 直下に置く。日付でフォルダを
        切らないのは spec §7.1（分類はタグで行う）に従うため。
        """
        when = day or datetime.now()
        path = self.root / f"{sanitize_filename(daily_title(when))}.md"
        if path.is_file():
            # 既にあるものへ印を埋め直さない。書いた内容が唯一の真実（R1）
            return NewNote(self.read(path))

        source = self.templates_dir / template
        body = (
            frontmatter.split(source.read_text(encoding="utf-8")).body
            if source.is_file()
            else f"# {daily_title(when)}\n\n"
        )
        filled = _with_aligned_tables(expand(body, now=when, title=daily_title(when)))
        note = self.create(daily_title(when), filled.text)
        return NewNote(note, self._cursor_in(note, filled))

    def _inside_templates(self, path: Path) -> bool:
        try:
            return path.resolve().is_relative_to(self.templates_dir.resolve())
        except OSError:
            return False

    def _cursor_in(self, note: Note, filled: Expanded) -> int | None:
        """差し込み後の位置を、ファイルの先頭から数え直す。

        `create()` が front matter を前に足すぶんだけ後ろへずれる。
        マーカーを隠しても文字は実在するので（R4）、この位置がそのまま
        エディタのキャレット位置になる。
        """
        if filled.cursor is None:
            return None
        return len(note.text) - len(filled.text) + filled.cursor

    # ----------------------------------------------------------------- 初回

    def is_empty(self) -> bool:
        return next(iter(self.scan()), None) is None

    def seed_manual(self) -> Note | None:
        """初回だけ使い方ノートを置く。置いたノートを返す。置かなければ None。

        条件は「vault が空」かつ「まだ置いたことがない」。印を管理フォルダに
        残すのは、**ユーザーが消したマニュアルを起動のたびに復活させない**ため。
        印は消えてもよい（R9 と同じ扱い。最悪もう一度置かれるだけ）。
        """
        marker = self.managed_dir / SEED_MARKER
        if marker.exists() or not self.is_empty():
            return None

        note = self.place_manual()
        if note is None:
            return None

        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(_now(), encoding="utf-8")
        return note

    def place_manual(self) -> Note | None:
        """使い方ノートを**今の内容で**置く。置いたノートを返す。

        アプリが新しくなって説明が増えても、既に置いたノートは古いまま
        残る（印があるので `seed_manual()` は二度と置かない）。ここを
        ヘルプメニューから呼べるようにして、最新の説明を出せる道を残す。

        **既にあるノートは消さない。** 書き足したメモごと消えては困るので、
        別のファイルとして置く（`unique_path` が名前をずらす）。

        **印は触らない。** 置き直しは初回扱いに戻すことではない。戻すと、
        ユーザーが消したマニュアルが次の起動で勝手に復活する。
        """
        text = _read_resource(MANUAL_RESOURCE)
        if text is None:
            return None
        return self.create(MANUAL_TITLE, text)

    def seed_templates(self) -> list[Path]:
        """まだ置いたことのない既定の雛形を置く（E-4）。置いたパスを返す。

        **印には置いた名前を残す。** 「一度置いたら二度と置き直さない」を
        守りつつ、**あとから増えた雛形は届く**ようにするため。日時だけを
        書いていたときは、印があるだけで新しい雛形が永久に現れなかった
        （`PowerPoint下書き` を足して気づいた。ユーザー報告）。

        名前で覚えているので、**手で消した雛形は復活しない**。
        **既にある名前は上書きしない**（手で直した雛形を消さない）。
        """
        marker = self.managed_dir / TEMPLATES_MARKER
        known = self._seeded_templates(marker)

        placed: list[Path] = []
        for name in DEFAULT_TEMPLATES:
            if name in known:
                continue
            known.add(name)
            target = self.templates_dir / name
            text = _read_resource(f"{TEMPLATES_RESOURCE}/{name}")
            if text is None or target.exists():
                continue
            save_atomic(target, text)
            placed.append(target)

        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("\n".join(sorted(known)) + "\n", encoding="utf-8")
        return placed

    def _seeded_templates(self, marker: Path) -> set[str]:
        """これまでに置いた雛形の名前。

        印が無ければ空。**日時しか書いていない古い印**のときは、そのとき
        置かれていたもの（`LEGACY_TEMPLATES`）を置いた扱いにする。
        """
        try:
            content = marker.read_text(encoding="utf-8")
        except OSError:
            return set()

        names = {line.strip() for line in content.split("\n") if line.strip().endswith(".md")}
        return names or set(LEGACY_TEMPLATES)

    def empty_trash(self) -> list[Path]:
        """ゴミ箱の中身を今すぐ全部消す（G-3）。消したものを返す。

        **期限を待たずに消したいことがある。** 見られたくないノートを
        捨てたとき、30 日残り続けるのは捨てたことにならない。

        添付も `.trash` に入る（E-5）ので一緒に消える。呼ぶ前に確認を
        取るのは UI 側の仕事。ここは黙って消す。
        """
        if not self.trash_dir.is_dir():
            return []

        removed: list[Path] = []
        for entry in sorted(self.trash_dir.iterdir()):
            if entry.is_dir():
                # Finder で手で入れられたフォルダ。「空にする」と言った以上、
                # 残すほうが嘘になる（自動の purge_trash は今まで通り触らない）
                shutil.rmtree(entry, ignore_errors=True)
                removed.append(entry)
            elif entry.is_file():
                entry.unlink()
                removed.append(entry)
        return removed

    def delete_permanently(self, path: Path) -> None:
        """ゴミ箱の中の 1 件を完全に消す（G-3）。

        **ゴミ箱の外は消さない。** 保管フォルダのノートを直に消す道を
        作ると、押し間違いが取り返しのつかない結果になる。渡し間違いは
        黙って無視せず `ValueError` で止める（呼び出し側の誤りのため）。

        既に無いファイルは何もしない（続けて押したときに落ちない）。
        """
        # 字句上の判定（`self.trash_dir in path.parents`）は
        # `.trash/../メモ.md` を通してしまう。実体で見る
        #
        # **直下に限らない。** K-5 でゴミ箱は階層を保つようになったので、
        # `仕事/会議.md` は `.trash/仕事/会議.md` に入る。親だけを比べると
        # サブフォルダから捨てたノートが 1 件も消せなくなる
        resolved = path.resolve()
        trash = self.trash_dir.resolve()
        if resolved == trash or not resolved.is_relative_to(trash):
            raise ValueError(f"ゴミ箱の外は消せない: {path}")
        path.unlink(missing_ok=True)
        # 空の殻を残さない（`restore` / `purge_trash` と同じ後始末）
        self._prune_empty_dirs(path.parent, boundary=self.trash_dir)

    def sweep_temp_files(self, *, max_age_seconds: float = TEMP_SWEEP_AGE_SECONDS) -> list[Path]:
        """クラッシュで残った一時ファイル（`*.tmp`）を消す（H-1 層 1）。起動時に呼ぶ。

        **新しいものは残す。** 別マシンが同期越しに同じ vault を書いている
        最中かもしれない。書き込みはミリ秒で終わるので、1 時間残っている
        `.tmp` はクラッシュの残骸で確定してよい。旧形式（`名前.md.tmp`
        固定名）の残骸も一緒に拾う。
        """
        deadline = time.time() - max_age_seconds
        removed: list[Path] = []
        for entry in sorted(self.root.rglob(f"*{TEMP_SUFFIX}")):
            try:
                if entry.is_file() and entry.stat().st_mtime < deadline:
                    entry.unlink()
                    removed.append(entry)
            except OSError:
                continue  # 掃除は保守作業。1 件の失敗で起動を止めない
        return removed

    def purge_trash(self, days: int = DEFAULT_TRASH_DAYS) -> list[Path]:
        """期限を過ぎたゴミ箱の中身を消す（spec §7.6）。起動時に呼ぶ。"""
        if not self.trash_dir.is_dir():
            return []

        deadline = time.time() - days * 24 * 3600
        removed: list[Path] = []
        for entry in sorted(self.trash_dir.rglob("*")):
            try:
                if not entry.is_file():
                    continue
                if entry.stat().st_mtime < deadline:
                    entry.unlink()
                    removed.append(entry)
                    self._prune_empty_dirs(entry.parent, boundary=self.trash_dir)
            except OSError:
                # **1 件の不調で掃除ごと投げ出さない**（`sweep_temp_files` と
                # 同じ作法。S-2）。同期の下では走査と `stat()` の間に
                # ファイルが消える——iCloud / Dropbox / 別マシンが同じ vault を
                # 触っていれば普通に起きる。抜けさせると呼び出し元
                # （`_prepare_vault`）が**「保管フォルダを開けない」に化かす**
                continue
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
