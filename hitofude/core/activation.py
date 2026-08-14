"""`Cmd+クリック` で何を起こすか（D-1 / D-2）。

仕様書 §5.2 が約束していた「リンクは `Cmd+クリック` で既定ブラウザを開く」
「タグはクリックで絞り込む」を実現するための判定。

**開く先はここで絞る。** 本文は手で編集できるので、`javascript:` や
`file:` を書いておいて踏ませることができてしまう。判定を UI 側に散らすと
抜け道ができるため、1 か所に閉じ込める。

`core/` にあるので PySide6 に依存しない（R3）。
"""

from dataclasses import dataclass
from enum import Enum, auto

from hitofude.core.models import InlineSpan, SpanType

# 開いてよいスキーム。**増やすときは理由を書くこと。**
# `file:` は保管フォルダの外を開けてしまい、`javascript:` / `data:` は
# 本文に仕込んだものが動く
ALLOWED_SCHEMES = ("http://", "https://", "mailto:")

_LINK_TYPES = frozenset({SpanType.LINK_TEXT, SpanType.LINK_URL, SpanType.AUTOLINK})


class ActivationKind(Enum):
    LINK = auto()
    """既定のブラウザで開く。"""

    TAG = auto()
    """そのタグで一覧を絞り込む。"""


@dataclass(frozen=True, slots=True)
class Activation:
    kind: ActivationKind
    payload: str
    """`LINK` なら URL、`TAG` なら正規化したタグ名。"""


def activation_at(spans: list[InlineSpan], column: int) -> Activation | None:
    """その位置で `Cmd+クリック` したときの動作。何も無ければ None。

    範囲は `[start, end)`。終端は次の文字なので当たらない。
    """
    for span in spans:
        if not span.start <= column < span.end:
            continue
        if span.type is SpanType.TAG:
            return Activation(ActivationKind.TAG, span.payload)
        if span.type in _LINK_TYPES and _is_openable(span.payload):
            return Activation(ActivationKind.LINK, span.payload)
    return None


def _is_openable(url: str) -> bool:
    """外へ開いてよい URL か。

    相対パス（`attachments/…`）も開かない。vault の中の参照であって、
    ブラウザへ渡すものではない。
    """
    lowered = url.strip().lower()
    return lowered.startswith(ALLOWED_SCHEMES)
