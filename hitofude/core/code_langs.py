"""コードフェンスの言語補完（ユーザー要望）。

候補の源は Pygments の別名一覧。色付け（`code_tokens.tokenize`）と同じ
`get_lexer_by_name` の名前空間なので、**補完に出た名前は必ず色が付く**。

`core/` にあるので PySide6 に依存しない（R3）。発火位置の判定と絞り込みは
純関数で、エディタはこれを呼ぶだけ。
"""

import re
from functools import cache

from pygments.lexers import get_all_lexers

# フェンス開始行の打ちかけ。行頭の ``` 以降に言語トークンが続き、
# キャレット（= 文字列の終わり）がトークンの末尾にあるときだけ発火する。
# 何も打っていない ``` では出さない（Enter を奪うと素のフェンスが作れない）
_TYPING_RE = re.compile(r"^`{3,}([A-Za-z0-9_+#.-]+)$")

# 先頭に出す、よく使う言語。920 個を機械的な順で出すと目で探せない。
# ここに無いものは後ろにアルファベット順で続く
_COMMON = (
    "python",
    "javascript",
    "typescript",
    "html",
    "css",
    "json",
    "yaml",
    "toml",
    "bash",
    "sh",
    "zsh",
    "sql",
    "go",
    "rust",
    "swift",
    "kotlin",
    "java",
    "c",
    "cpp",
    "csharp",
    "ruby",
    "php",
    "markdown",
    "diff",
    "dockerfile",
    "ini",
    "xml",
    "makefile",
    "text",
)


@cache
def known_langs() -> tuple[str, ...]:
    """指定できる言語名（別名を含む）。初回だけ Pygments から読む。

    `get_all_lexers()` は数十 ms かかるので、打鍵のたびに呼んではいけない。
    """
    aliases = {alias for _name, entries, _files, _mimes in get_all_lexers() for alias in entries}
    order = {name: index for index, name in enumerate(_COMMON)}
    return tuple(sorted(aliases, key=lambda name: (order.get(name, len(order)), name)))


def prefix_at(line: str, column: int) -> str | None:
    """フェンス開始行で打ちかけの言語名。発火しない位置なら None。

    キャレットは言語トークンの**末尾**にあること（続きが空か、
    `:ファイル名` の始まりであること）。途中で出すと、確定したときに
    後ろ半分が残って `pythonthon` になる。
    """
    found = _TYPING_RE.match(line[:column])
    if found is None:
        return None
    rest = line[column:]
    if rest and not rest.startswith(":"):
        return None
    return found.group(1)


def matches(prefix: str) -> list[str]:
    """前方一致で候補を絞る。大文字小文字は区別しない。

    タグ補完（tags.matches）と同じく、**打ったものと同じだけの候補は
    返さない**。選ぶものが無いのに一覧が出ていると、Enter が確定なのか
    改行なのか分からなくなる。
    """
    lowered = prefix.lower()
    found = [name for name in known_langs() if name.startswith(lowered)]
    if found == [prefix]:
        return []
    return found
