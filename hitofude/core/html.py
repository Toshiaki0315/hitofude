"""Markdown → HTML（B-2 / ADR-0007）。

書き出し（HTML・PDF）はここを通る。**`QTextDocument.setMarkdown()` は使わない。**
あちらはコードフェンスの言語・生 HTML・脚注・`:::` を落とし、Mermaid（B-4）や
数式（B-5）や Qiita 記法（B-3）がそもそも成立しなかった（実測は ADR-0007）。

**エディタと同じ markdown-it-py を使う**（`core/block_parser.py` と同じ設定）。
同じパーサなら、画面で解釈された構造と書き出した構造が食い違わない。

`core/` にあるので PySide6 に依存しない（R3）。書き出しの中身をヘッドレスで
検査できる。ページの組み立て（`<html>`・スタイル・画像の埋め込み）と PDF は
Qt が要るので `editor/exporter.py` の側に残す。
"""

import re

from markdown_it import MarkdownIt

from hitofude.core import frontmatter

# エディタ（`core/block_parser.py`）と同じ設定にする。**片方だけ機能を足さない。**
# 画面で表として解釈されたものが書き出しでは段落、のような食い違いを作らない
#
# 違うのは `html` だけ。**commonmark プリセットは既定で `html: True`**（実測）で、
# 本文の `<script>` がそのまま出力に通る。書き出した HTML は他人に渡るので、
# ここは明示的に切ってエスケープさせる。`setMarkdown()` も通していなかったので
# 振る舞いとしても変わらない
_MD = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

# `- [ ] やること` の頭。`setMarkdown()` は `<li class="unchecked">` にして
# **記号を消していた**ので、スタイルを当てない限り印が出なかった（実測）
_TASK_RE = re.compile(r"^\[(?P<state>[ xX])\][ \t]+")
_CHECKED, _UNCHECKED = "☑", "☐"


def render(text: str) -> str:
    """Markdown の本文を HTML にする。front matter は落とす。

    `id` や `modified` はこのアプリの管理情報で、読む人には意味がない。
    """
    tokens = _MD.parse(frontmatter.split(text).body)
    _mark_tasks(tokens)
    return _MD.renderer.render(tokens, _MD.options, {})


def _mark_tasks(tokens) -> None:
    """リスト項目の `[ ]` / `[x]` を記号に置き換える。

    トークンを見て**リスト項目の先頭だけ**を対象にする。文字列を直に
    置換すると、段落の `[ ]` やコードブロックの中まで巻き込む。
    """
    for index, token in enumerate(tokens):
        if token.type != "inline" or index < 2:
            continue
        if tokens[index - 1].type != "paragraph_open":
            continue
        if tokens[index - 2].type != "list_item_open":
            continue

        found = _TASK_RE.match(token.content)
        if found is None:
            continue

        mark = _CHECKED if found.group("state") in "xX" else _UNCHECKED
        replaced = f"{mark} {token.content[found.end() :]}"
        token.content = replaced
        # 描画に使われるのは子トークンのほう。親だけ直しても出力は変わらない
        if token.children:
            first = token.children[0]
            first.content = _TASK_RE.sub(f"{mark} ", first.content, count=1)
