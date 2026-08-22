"""関連するノートを並べる（L-3）。

**LLM に選ばせない。** 関係の根拠は既に索引の中にある（同じタグ・
`[[…]]` の指し合い・題名の語）。モデルに選ばせると **なぜ関係するのか
確かめられず**、待たされ、Ollama を入れていない人には何も出ない。
索引から引けば即座に出て、**理由も一緒に出せる**。

ここは並べ方だけの純関数（R3）。索引を引くのは呼ぶ側。
"""

from dataclasses import dataclass

LINK = 3
"""`[[…]]` で指している／指されている。**書いた人が手で結んだ**関係なので
いちばん強い。"""

SHARED_TAG = 2
"""同じタグ。これも手で付けたもの。"""

TEXT = 1
"""題名の語が本文に出てくる。**偶然もある**ので弱く見る。"""

DEFAULT_LIMIT = 8
"""画面に入らない数を出さない。上から数件で足りる。"""


@dataclass(frozen=True, slots=True)
class Signal:
    """「このノートが関係する」1 つの根拠。"""

    key: str
    """ノートを見分ける印（相対パスを想定）。"""

    reason: str
    """**そのまま画面に出す。** 出た理由が読めないと確かめようがない。"""

    weight: int


@dataclass(frozen=True, slots=True)
class Related:
    key: str
    reasons: tuple[str, ...]
    score: int


def rank(signals: list[Signal], *, exclude: str, limit: int = DEFAULT_LIMIT) -> list[Related]:
    """信号を束ねて強い順に並べる。**自分は外す。**

    同じ強さなら渡された順のまま（索引は更新順で返すので、新しいものが
    上に来る）。
    """
    scores: dict[str, int] = {}
    reasons: dict[str, list[str]] = {}
    for signal in signals:
        if signal.key == exclude:
            continue
        scores[signal.key] = scores.get(signal.key, 0) + signal.weight
        found = reasons.setdefault(signal.key, [])
        if signal.reason not in found:
            found.append(signal.reason)

    order = list(scores)  # dict は挿入順を保つ。同点はこの順で残る
    order.sort(key=lambda key: -scores[key])
    return [
        Related(key=key, reasons=tuple(reasons[key]), score=scores[key]) for key in order[:limit]
    ]
