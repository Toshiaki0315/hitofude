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

import logging
import re

from latex2mathml.converter import convert as latex_to_mathml
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin

from hitofude.core import frontmatter
from hitofude.core.models import DEFAULT_NOTE_KIND, NOTE_KINDS, UNKNOWN_NOTE_KIND

logger = logging.getLogger(__name__)

# エディタ（`core/block_parser.py`）と同じ設定にする。**片方だけ機能を足さない。**
# 画面で表として解釈されたものが書き出しでは段落、のような食い違いを作らない
#
# 違うのは `html` だけ。**commonmark プリセットは既定で `html: True`**（実測）で、
# 本文の `<script>` がそのまま出力に通る。書き出した HTML は他人に渡るので、
# ここは明示的に切ってエスケープさせる。`setMarkdown()` も通していなかったので
# 振る舞いとしても変わらない
_MD = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

# --------------------------------------------------------- Qiita 記法（B-3）

# 種類の定義は `core/models.py` にある。**画面と同じものを使う。**
# 片方だけ寄せ方を変えると、画面は灰色なのに書き出しは青、という
# 食い違いが起きる（B-2 で作らないと決めたもの）
_NOTE_TOKENS = 2
"""`note` と種類で 2 語まで。`:::note warn extra` は囲みにしない。"""


def _validate_note(params: str, markup: str) -> bool:
    """`:::note` の行として受けるか。`markup` は使わないがプラグインが渡す。"""
    parts = params.strip().split()
    return bool(parts) and parts[0] == "note" and len(parts) <= _NOTE_TOKENS


def _note_kind(info: str) -> str:
    """`:::note warn` の `warn`。省略は `info`、知らない綴りは別扱い。"""
    parts = info.strip().split()
    if len(parts) <= 1:
        return DEFAULT_NOTE_KIND
    return parts[1] if parts[1] in NOTE_KINDS else UNKNOWN_NOTE_KIND


def _render_note(self, tokens, index, options, env) -> str:
    token = tokens[index]
    if token.nesting != 1:
        return "</div>\n"
    return f'<div class="note note-{_note_kind(token.info)}">\n'


def _render_math_inline(self, tokens, index, options, env) -> str:
    content = tokens[index].content
    # **かな・漢字が入っていたら数式ではない。** `$` は日本語の文章にも出てくる
    # （値段）ので、`価格は $100 と $200 です。定価 100$ から $200 まで。` の
    # ように 2 つ目の開きと 1 つ目の閉じが組になり、間の日本語ごと式になる
    # （実際にブラウザで見て見つけた）。数式に日本語は出てこない
    as_source = env.get(_MATH_AS_SOURCE, False) or bool(_CJK_RE.search(content))
    return _math(content, block=False, as_source=as_source)


def _render_math_block(self, tokens, index, options, env) -> str:
    return _math(tokens[index].content, block=True, as_source=env.get(_MATH_AS_SOURCE, False))


def _math(latex: str, *, block: bool, as_source: bool = False) -> str:
    """LaTeX を MathML にする（B-5）。

    **JavaScript は同梱しない。** KaTeX / MathJax を入れると書き出した
    1 ファイルごとに 1MB 以上増え、開くたびに走る。MathML なら今のブラウザが
    そのまま組んでくれて、「外部リソースを参照しない」という `to_html` の
    約束も保てる。

    解釈できない式は**文字のまま返す**。式ひとつのために本文を失わない。
    """
    marker = "$$" if block else "$"
    if as_source:
        return escapeHtml(f"{marker}{latex.strip()}{marker}")
    try:
        return latex_to_mathml(latex.strip(), display="block" if block else "inline")
    except Exception:  # latex2mathml は独自の例外を投げる
        logger.warning("数式を解釈できなかった: %r", latex)
        return escapeHtml(f"{marker}{latex}{marker}")


def _render_fence(self, tokens, index, options, env) -> str:
    """` ```js:index.js ` のファイル名を見出しとして出す。

    **言語のクラスは言語だけにする。** `language-js:index.js` のままだと
    色分けの仕組みが言語を見つけられない。
    """
    token = tokens[index]
    lang, separator, name = token.info.strip().partition(":")
    if not separator:
        return RendererHTML.fence(self, tokens, index, options, env)

    token.info = lang
    body = RendererHTML.fence(self, tokens, index, options, env)
    label = f'<div class="code-name">{escapeHtml(name)}</div>' if name else ""
    return f'<div class="code-block">{label}{body}</div>\n'


# 数式（B-5）。**記号の内側の空白と、前後の数字を許さない。**
# 許すと `価格は $100 と $200 です。` が数式になる（実測。日本語の文章として
# 普通に出てくる形）。ここが緩いとふつうの文章が壊れる
_MD.use(dollarmath_plugin, allow_space=False, allow_digits=False)
_MD.use(container_plugin, name="note", validate=_validate_note, render=_render_note)
_MD.use(footnote_plugin)
# `renderer.rules` に直接入れると `self` が渡らない（実測）。
# `add_render_rule` はメソッドとして束ねるので、既定の描画を呼び直せる
_MD.add_render_rule("fence", _render_fence)
_MD.add_render_rule("math_inline", _render_math_inline)
_MD.add_render_rule("math_block", _render_math_block)

# `- [ ] やること` の頭。`setMarkdown()` は `<li class="unchecked">` にして
# **記号を消していた**ので、スタイルを当てない限り印が出なかった（実測）
_TASK_RE = re.compile(r"^\[(?P<state>[ xX])\][ \t]+")
_CHECKED, _UNCHECKED = "☑", "☐"

# 数式を LaTeX のまま出すかを描画規則へ渡す鍵（`env` 経由。B-5）
_MATH_AS_SOURCE = "hitofude_math_as_source"

# かな・漢字。これを含むインライン数式は取り違え（`_render_math_inline`）
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿々〆、。]")


def render(text: str, *, math_as_source: bool = False) -> str:
    """Markdown の本文を HTML にする。front matter は落とす。

    `id` や `modified` はこのアプリの管理情報で、読む人には意味がない。

    `math_as_source` は数式を MathML にせず、書いたままの LaTeX で出す。
    **PDF 用**（Qt のリッチテキストは MathML を解さず、`$E = mc^2$` を
    `E=mc2` に、`\\frac{a}{b}` を `ab` にしてしまう。実測）。黙って
    間違った式を出すくらいなら、書いたままを見せるほうがよい（ADR-0009）。
    """
    # **`env` を解析と描画で共有する。** 脚注はここに定義を溜めるので、
    # 空の辞書を渡し直すと注釈の本文だけ消える（実際に踏んだ）
    env: dict = {_MATH_AS_SOURCE: math_as_source}
    tokens = _MD.parse(frontmatter.split(text).body, env)
    _mark_tasks(tokens)
    return _MD.renderer.render(tokens, _MD.options, env)


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
