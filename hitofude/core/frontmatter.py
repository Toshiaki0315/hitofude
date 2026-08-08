"""YAML front matter の分離と再結合（spec §7.2）。

front matter は**任意**。Qt は front matter をパースしない（公式明記）ため自前で扱う。

設計上の最重要方針: **メタデータが壊れていても本文は必ず返す**。
front matter は付随情報にすぎず、それを理由にノートが開けなくなるのは
ローカルファイルにプレーンテキストで保存する意味（G3）を損なう。
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

# 1 行目がちょうど `---` で始まり、行頭の `---` で閉じられている場合だけ front matter。
# 閉じ区切りが無いものは「ただの水平線で始まる本文」として扱う。
_FRONT_MATTER_RE = re.compile(
    r"\A---[ \t]*\n(?P<yaml>.*?)^---[ \t]*(?:\n|\Z)",
    re.DOTALL | re.MULTILINE,
)

_BOM = "﻿"

_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


def _without_timestamps(resolvers: dict[str, list[tuple[str, object]]]) -> dict:
    return {
        first: [(tag, regexp) for tag, regexp in entries if tag != _TIMESTAMP_TAG]
        for first, entries in resolvers.items()
    }


class _Loader(yaml.SafeLoader):
    """ISO 8601 の日時を `datetime` に変換しないローダ。

    変換してしまうと `join()` で書き戻したときにタイムゾーン表記が
    `+09:00` から `+09:00` 以外の形へ揺れ、**保存のたびにファイルの diff が出る**。
    これは §3.3 で `toMarkdown()` を却下した理由 4 とまったく同じ事故なので、
    front matter でも同様に避ける。`created` / `modified` は文字列のまま扱う。
    """


class _Dumper(yaml.SafeDumper):
    """`_Loader` と対称。日時に見える文字列を引用符で囲まない。"""


_Loader.yaml_implicit_resolvers = _without_timestamps(yaml.SafeLoader.yaml_implicit_resolvers)
_Dumper.yaml_implicit_resolvers = _without_timestamps(yaml.SafeDumper.yaml_implicit_resolvers)


@dataclass(frozen=True, slots=True)
class FrontMatter:
    """`split()` の結果。"""

    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    body_offset: int = 0
    """**正規化後**のテキストにおける本文の開始位置。

    ハイライタが「本文の N 文字目」を元テキストの位置へ戻すのに使う。
    正規化（CRLF → LF、BOM 除去）は読み込み時に行われる前提。
    """

    present: bool = False
    """front matter の区切り自体が存在したか。"""

    invalid: bool = False
    """区切りはあったが YAML として解釈できなかったか。"""

    def get(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)


def _normalize(text: str) -> str:
    """改行を LF に統一し、BOM を落とす（spec §7.2）。"""
    if text.startswith(_BOM):
        text = text[len(_BOM) :]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def body_offset(text: str) -> int:
    """本文の開始位置だけを返す。front matter が無ければ 0。

    `split()` と同じ値を返すが、**YAML を読まない**。エディタが打鍵のたびに
    「カーソルが front matter の中にいないか」を確かめるのに使うため、
    `yaml.load()` まで走らせられない。
    """
    match = _FRONT_MATTER_RE.match(_normalize(text))
    return match.end() if match else 0


def split(text: str) -> FrontMatter:
    """テキストを front matter と本文に分ける。

    front matter が無い・閉じられていない・YAML として壊れている、
    のいずれの場合でも例外を投げず、本文を保ったまま返す。
    """
    normalized = _normalize(text)
    match = _FRONT_MATTER_RE.match(normalized)
    if match is None:
        return FrontMatter(meta={}, body=normalized, body_offset=0)

    body_offset = match.end()
    body = normalized[body_offset:]
    raw = match.group("yaml")

    if not raw.strip():
        # `---` が 2 行続くだけの空の front matter。壊れてはいない。
        return FrontMatter(meta={}, body=body, body_offset=body_offset, present=True)

    try:
        loaded = yaml.load(raw, Loader=_Loader)
    except yaml.YAMLError:
        return FrontMatter(meta={}, body=body, body_offset=body_offset, present=True, invalid=True)

    if not isinstance(loaded, dict):
        # リストやスカラは front matter として意味を成さない
        return FrontMatter(meta={}, body=body, body_offset=body_offset, present=True, invalid=True)

    return FrontMatter(meta=loaded, body=body, body_offset=body_offset, present=True)


def join(meta: Mapping[str, Any], body: str) -> str:
    """メタデータと本文を 1 つのテキストに戻す。

    `split()` の逆変換。往復でファイルが書き換わらないことが要件（G3）。
    """
    if not meta:
        return body

    dumped = yaml.dump(
        dict(meta),
        Dumper=_Dumper,
        allow_unicode=True,  # 日本語が タ になるとユーザーが読めない
        sort_keys=False,  # 書いた順を保つ。並べ替えると無意味な diff が出る
        default_flow_style=False,
    )
    return f"---\n{dumped}---\n{body}"
