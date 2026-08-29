"""日本語の文体を見る（U-4。ユーザー要望 2026-08-29）。

iA Writer の Style Check（決まり文句・冗長表現の指摘）の日本語版。
**指摘するだけで、直さない**——書き手の言葉を機械が上書きしない。

**形態素解析は使わない。** 品詞で見ると辞書と実行時間が要るうえ、
外すと的外れな指摘になる。**言い回しの辞書**に絞れば、当たるものだけを
確実に当てられる。外れを出さないことを取る——1 つの誤検出が、以後
全部の指摘を無視させる。

GUI 非依存（R3）。正規表現はモジュールで組む（§6.6）。
"""

import re
from dataclasses import dataclass
from enum import Enum, auto

from hitofude.core import frontmatter
from hitofude.core.fences import FenceGate


class Kind(Enum):
    REDUNDANT = auto()
    """冗長な言い回し（`することができる` → `できる`）。"""

    DOUBLE_NEGATIVE = auto()
    """二重否定。読み手が肯定否定を数える羽目になる。"""

    TAUTOLOGY = auto()
    """重ね言葉（`頭痛が痛い` の類）。"""

    PARTICLE_RUN = auto()
    """同じ助詞が続く（`私の友人の家の庭`）。係り先が読み取りにくい。"""

    LONG_SENTENCE = auto()
    """1 文が長い。"""


@dataclass(frozen=True, slots=True)
class Finding:
    start: int
    """本文の先頭からの位置（Python の文字単位）。"""

    length: int
    kind: Kind
    message: str
    """**どう書けるか**を出す。何が悪いかだけ言われても動けない。"""

    @property
    def end(self) -> int:
        return self.start + self.length


MAX_SENTENCE = 100
"""1 文の上限（字）。

**厳しくしない。** 日本語の実用文は 60〜80 字が読みやすいとされるが、
そこで切ると技術文書は指摘だらけになる。**明らかに長いものだけ**に
当てて、指摘そのものが無視されないようにする。
"""

PARTICLE_RUN_MIN = 3
"""同じ助詞が続いてよい回数。2 つ（`私の友人の家`）はふつうに書く。"""

# (正規表現, 種類, 言い換え) の並び。**言い回しの辞書**で、品詞は見ない
_RULES: list[tuple[re.Pattern[str], Kind, str]] = [
    (re.compile(r"することができ(る|ます|ない|ません)"), Kind.REDUNDANT, "「できます」で足ります"),
    (re.compile(r"することが可能"), Kind.REDUNDANT, "「できます」で足ります"),
    (re.compile(r"という点において"), Kind.REDUNDANT, "「という点で」で足ります"),
    (re.compile(r"を行うことができ"), Kind.REDUNDANT, "動詞そのもので言えます"),
    (re.compile(r"なくはない"), Kind.DOUBLE_NEGATIVE, "二重否定です。言い切れませんか"),
    (re.compile(r"ないことはない"), Kind.DOUBLE_NEGATIVE, "二重否定です。言い切れませんか"),
    (re.compile(r"なくもない"), Kind.DOUBLE_NEGATIVE, "二重否定です。言い切れませんか"),
    (re.compile(r"まず最初に"), Kind.TAUTOLOGY, "「まず」か「最初に」のどちらかで足ります"),
    (re.compile(r"違和感を感じ"), Kind.TAUTOLOGY, "「違和感を覚え」と書けます"),
    (re.compile(r"今の現状"), Kind.TAUTOLOGY, "「現状」で足ります"),
    (re.compile(r"一番最(適|初|後)"), Kind.TAUTOLOGY, "「最—」だけで足ります"),
    (re.compile(r"あらかじめ予(約|定)"), Kind.TAUTOLOGY, "「予—」だけで足ります"),
    (re.compile(r"後(で|から)後悔"), Kind.TAUTOLOGY, "「後悔」だけで足ります"),
    (re.compile(r"返事を返"), Kind.TAUTOLOGY, "「返事をし」と書けます"),
]

PARTICLE_UNIT_MAX = 6
"""`の` の前に置ける語の長さ（字）。

**長い塊を数えない。** 上限が無いと、節をまたいで
`本文の上のボタンからも付けられます（次の` のような並びを 1 つの
連なりと見なす（実測: 使い方ノートで 21 件。ほとんどが誤検出）。
"""

_PARTICLE_RUN = re.compile(
    rf"(?:[^\s。、の]{{0,{PARTICLE_UNIT_MAX - 1}}}[^\s。、のこそあど]の){{{PARTICLE_RUN_MIN},}}"
)
"""`の` を挟んだ**短い語**が続く並び。句読点と空白は跨がない。

**こそあど（`その` `この`）は数えない。** そこの `の` は連体詞の
一部で、「〜の〜の〜」の連なりではない（実測で `前の行の字下げが
その` を拾っていた）。

**代わりに取りこぼす。** 文字単位の否定なので、`いとこの` `そこの`
`かどの` のように**かなで終わる語**の連なりも数えない（レビュー指摘
2026-08-29）。単語として弾く形（`(?![こそあど]の)`）も試したが、
語の長さが可変なぶん `字下げがその` を 1 語として飲み込み、**直した
はずの誤検出が戻った**（実測）。形態素解析を使わない以上どちらかは
諦めることになり、**外れを出さないほう**を取る。"""

_NOT_PROSE = re.compile(r"^\s*(\||[-=_*]{3,}\s*$|>\s*\||#{1,6}\s*$)")
"""文章ではない行。**表の行と区切り線**は文として数えない。

`docs/TASKS.md` に当てたら 193 件出て、**ほとんどが表**だった（実測）。
`| --- | ---- |` を「1 文が長い」と言われても直しようがない。
"""

_SENTENCE_END = re.compile(r"[。！？]")


def _sentences(text: str, offset: int) -> list[tuple[int, str]]:
    """`(本文中の位置, 文)`。句点で切る。**行の長さでは数えない**——
    短い文が並んでいるだけなら読みにくくはない。
    """
    found: list[tuple[int, str]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        found.append((offset + start, text[start : match.end()]))
        start = match.end()
    if text[start:].strip():
        found.append((offset + start, text[start:]))
    return found


def _body_lines(text: str) -> list[tuple[int, str]]:
    """コードの中を除いた行（`(本文中の位置, 行)`）。

    **コード例の日本語は文章ではない。** 数え方を `wikilink._body_lines`
    と揃える（同じ `FenceGate` を使う）——別に書くと「リンクは拾うのに
    文体は見ない」のような食い違いが出る。
    """
    found: list[tuple[int, str]] = []
    gate = FenceGate()
    offset = len(text) - len(frontmatter.split(text).body)
    for line in frontmatter.split(text).body.split("\n"):
        if not gate.crosses(line) and not gate.inside and not _NOT_PROSE.match(line):
            found.append((offset, line))
        offset += len(line) + 1
    return found


def check(text: str) -> list[Finding]:
    """本文を見て、気づいたところを返す。**直さない。**"""
    found: list[Finding] = []
    for offset, line in _body_lines(text):
        for pattern, kind, message in _RULES:
            for match in pattern.finditer(line):
                found.append(
                    Finding(
                        start=offset + match.start(),
                        length=match.end() - match.start(),
                        kind=kind,
                        message=message,
                    )
                )
        for match in _PARTICLE_RUN.finditer(line):
            found.append(
                Finding(
                    start=offset + match.start(),
                    length=match.end() - match.start(),
                    kind=Kind.PARTICLE_RUN,
                    message="「の」が続いています。区切れませんか",
                )
            )
        for start, sentence in _sentences(line, offset):
            body = sentence.strip()
            if len(body) > MAX_SENTENCE:
                found.append(
                    Finding(
                        start=start,
                        length=len(sentence),
                        kind=Kind.LONG_SENTENCE,
                        message=f"1 文が {len(body)} 字あります。切れませんか",
                    )
                )
    found.sort(key=lambda item: (item.start, item.length))
    return found
