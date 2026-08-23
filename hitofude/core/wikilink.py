"""`[[ノート名]]` の名前の扱い（E-6）。

ノート同士を繋ぐリンク。**CommonMark ではない**（`::ハイライト::` や
Qiita 記法と同じ立場）。他のアプリで開けばただの文字に見えるが、
ソースが真実（R1）なので何も失われない。

**ID ではなく名前で結ぶ。** このアプリのタイトルは本文の H1 から導かれ、
ファイル名がそれに追従する（ADR-0005）。`[[01J8XZ...]]` と書かれたノートは
人が読めないし、手で書けない。名前で結ぶ代償は「題名を変えるとリンクが
切れる」ことだが、切れたリンクは押した先で作り直せる（ADR-0011）。

`core/` にあるので PySide6 に依存しない（R3）。
"""

import re
import unicodedata
from collections.abc import Iterable

from hitofude.core import frontmatter
from hitofude.core.inline_scanner import scan
from hitofude.core.models import SpanType

_WHITESPACE_RE = re.compile(r"\s+")

# コードフェンスの開始/終了。前置の空白は 3 つまで（CommonMark）。
# `core/tags.py` と同じ規則。**タグと同じく、コードの中は数えない**
_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")


def normalize(name: str) -> str:
    """比較のために名前を揃える。

    規則は `storage/vault.sanitize_filename()` と同じにする。**ファイル名が
    その規則で作られる**ので、揃えないと「書いた名前では見つからない
    ノート」ができる。NFC に寄せるのは、macOS のファイル名が分解された形
    （`か` + 濁点）で来ることがあるため。
    """
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", name)).strip()


def links(text: str) -> list[str]:
    """本文が指しているノート名を、重複を除いて出現順に返す（E-6 ②）。

    **コードの中は数えない。** `` ```[[a]]``` `` はリンクではなく、コード例と
    してそう書いたもの（§6.5 規則 1 と同じ方針で、`tags.find_all()` も同じ形）。
    インラインコードは走査そのものが弾く（`scan()` がコードを先にマスクする）。

    front matter も見ない。`id` や `created` はアプリの管理情報で、
    リンクが書かれる場所ではない。
    """
    found: dict[str, None] = {}
    for line in _body_lines(text):
        for span in scan(line):
            if span.type is SpanType.WIKI_LINK:
                found.setdefault(normalize(span.payload), None)
    return list(found)


def _body_lines(text: str):
    """本文の行を順に。**コードの中と front matter は出さない。**

    `links()` と `relations()` で数え方がずれると、**図に出るのに索引には
    無いリンク**ができる。同じところから読む。
    """
    fence: str | None = None
    for line in frontmatter.split(text).body.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield line


MAX_RELATION = 12
"""続柄の長さの上限（M-3）。**関係の名前は短い**（参考文献・元ネタ・前提）。
長い一文は、たまたまコロンが入った地の文なので拾わない。"""

# 箇条書きの印。**地の文は見ない** — 「今日は: [[…]]」を続柄にしないため。
# チェックボックス（`- [ ] `）もここで一緒に落とす
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")

# 続柄と本文の区切り。**半角のコロンは後ろに空白を要る** — 無いと `10:30` の
# 「10」や `https://…` の「https」を続柄にしてしまう（実測しなくても分かる
# 誤りだが、日本語のノートでは時刻がよく出る）。全角は日本語で使われる形
# なので、後ろの空白を求めない
_RELATION_RE = re.compile(r"^(?P<name>[^\[\]\n]*?)\s*(?::\s|：)")


def _relation_of(line: str) -> str:
    """その行が付けている続柄（M-3）。無ければ空。

    **新しい記法は作らない。** 箇条書きの行の `:` より前を読むだけで、
    これはただの Markdown——他のエディタで開いても意味が通る。
    """
    bullet = _BULLET_RE.match(line)
    if bullet is None:
        return ""
    found = _RELATION_RE.match(line[bullet.end() :])
    if found is None:
        return ""
    name = _WHITESPACE_RE.sub(" ", found.group("name")).strip()
    return name if 0 < len(name) <= MAX_RELATION else ""


def relations(text: str) -> list[tuple[str, str]]:
    """指している先と、そこに付いた続柄の組（M-3）。続柄が無ければ空文字。

    **同じ相手を別の続柄で指せる**ので、組で重複を除く（索引の主キーも
    それに合わせてある）。数え方（コードの中は見ない・front matter は
    見ない）は `links()` と同じ。
    """
    found: dict[tuple[str, str], None] = {}
    for line in _body_lines(text):
        relation = _relation_of(line)
        for span in scan(line):
            if span.type is SpanType.WIKI_LINK:
                found.setdefault((normalize(span.payload), relation), None)
    return list(found)


def context_line(text: str, name: str) -> str:
    """`[[name]]` を書いている最初の行（E-6 ③）。無ければ空。

    バックリンクの一覧に「どこで指されているか」を出すためのもの。
    **ノートの冒頭（`preview`）では足りない。** 長いノートから指されている
    とき、冒頭を見ても関係が分からない。

    行はそのまま返す。マーカーを外すと、どう書かれているかが見えなくなる。
    """
    target = normalize(name)
    if not target:
        return ""

    fence: str | None = None
    for line in frontmatter.split(text).body.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            fence = (
                marker
                if fence is None
                else (None if marker[0] == fence[0] and len(marker) >= len(fence) else fence)
            )
            continue
        if fence is not None:
            continue
        for span in scan(line):
            if span.type is SpanType.WIKI_LINK and normalize(span.payload).casefold() == (
                target.casefold()
            ):
                return line.strip()
    return ""


def resolve(name: str, titles: Iterable[str]) -> str | None:
    """名前に対応するタイトルを返す。無ければ None。

    **完全一致を先に見る。** 大小を無視した一致は補助で、`ABC` と `abc` が
    両方あるときに打った通りのほうを選ぶ。
    """
    target = normalize(name)
    if not target:
        return None

    candidates = list(titles)
    for title in candidates:
        if normalize(title) == target:
            return title

    lowered = target.casefold()
    for title in candidates:
        if normalize(title).casefold() == lowered:
            return title
    return None
