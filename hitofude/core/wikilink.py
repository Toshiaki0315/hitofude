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

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(name: str) -> str:
    """比較のために名前を揃える。

    規則は `storage/vault.sanitize_filename()` と同じにする。**ファイル名が
    その規則で作られる**ので、揃えないと「書いた名前では見つからない
    ノート」ができる。NFC に寄せるのは、macOS のファイル名が分解された形
    （`か` + 濁点）で来ることがあるため。
    """
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", name)).strip()


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
