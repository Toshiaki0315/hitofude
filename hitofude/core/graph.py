"""リンクの図（M-2 / 仮身ネットワーク）。

BTRON の「あるファイルを起点としたリンク構造」を写したもの。
**ここは Qt も索引も知らない**（R3）——題名と行き先の対応を渡すだけで、
座標まで出す。Qt 無しで形を検証できる。

**絞らないと開けない。** 素朴な力学モデルは点の数の 2 乗で効き、実測で
200 点 359ms・1,000 点 9.2 秒（TASKS.md の M-2）。5,000 ノートの vault を
丸ごと描く道は無いので、**起点からの深さで絞る**——絞り方は記事のほうが
持っていた（「何段階先まで表示するか指定できる」）。
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from hitofude.core.wikilink import normalize

MAX_NODES = 200
"""描く点の上限。実測 359ms（60 回）で、開いたときの 1 回なら待てる。"""

DEFAULT_DEPTH = 2
"""既定の深さ。1 だと隣しか見えず、3 だと一気に増える。"""

STEPS = 60
"""力学モデルを回す回数。増やすほど整うが 2 乗で効く。"""


@dataclass(frozen=True, slots=True)
class Node:
    title: str
    """画面に出す題名。**最初に見つかった書き方**を使う。"""

    exists: bool
    """索引にあるか。無いもの（`[[まだ無いノート]]`）は中抜きで描く。"""

    depth: int
    """起点からの距離。起点は 0。"""


@dataclass(frozen=True, slots=True)
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    """`(指すほう, 指されるほう)` を `nodes` の番号で。**向きを保つ。**"""

    dropped: int = 0
    """上限で落とした点の数。**黙って減らさない**ために持つ。"""


def _key(title: str) -> str:
    """照合用の形。`resolve`（E-6）と同じく空白を詰めて大小を無視する。"""
    return normalize(title).casefold()


def build(
    start: str,
    links: Mapping[str, Sequence[str]],
    *,
    depth: int = DEFAULT_DEPTH,
    limit: int = MAX_NODES,
) -> Graph:
    """起点から `depth` 段まで辿った図を作る。

    `links` は「ノートの題名 → そのノートが指している題名」。ここに鍵が
    無い題名は**まだ無いノート**として扱う（点にはする）。

    **指されている側も辿る。** 片方向だけだと「誰が参照しているか」が
    図から消える。それはバックリンクの帯（E-6）が既に見せている関係で、
    図にだけ無いと辻褄が合わない。
    """
    # **入ってくる線を先に集める。** 逆引きが無いと、辿るたびに全件を
    # 舐めることになる（点の数 × 全ノートで、深いほど効く）
    outgoing: dict[str, list[tuple[str, str]]] = {}
    incoming: dict[str, list[tuple[str, str]]] = {}
    display: dict[str, str] = {}
    for source, targets in links.items():
        source_key = _key(source)
        display.setdefault(source_key, normalize(source))
        for target in targets:
            target_key = _key(target)
            display.setdefault(target_key, normalize(target))
            outgoing.setdefault(source_key, []).append((target_key, source_key))
            incoming.setdefault(target_key, []).append((source_key, source_key))

    exists = {_key(title) for title in links}
    start_key = _key(start)
    display.setdefault(start_key, normalize(start))

    # **幅優先。** 近いものから決まるので、上限で切るときに遠いほうが落ちる
    depths: dict[str, int] = {start_key: 0}
    order: list[str] = [start_key]
    frontier = [start_key]
    for step in range(1, depth + 1):
        following: list[str] = []
        for current in frontier:
            neighbours = [target for target, _ in outgoing.get(current, [])]
            neighbours += [source for source, _ in incoming.get(current, [])]
            # **並べてから足す。** 渡された順で図が変わると見比べられない
            for neighbour in sorted(set(neighbours)):
                if neighbour in depths:
                    continue
                depths[neighbour] = step
                order.append(neighbour)
                following.append(neighbour)
        frontier = following

    kept = order[:limit]
    index = {key: number for number, key in enumerate(kept)}
    nodes = [Node(title=display[key], exists=key in exists, depth=depths[key]) for key in kept]

    edges: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for source_key in kept:
        for target_key, _ in outgoing.get(source_key, []):
            if target_key not in index or target_key == source_key:
                continue
            pair = (index[source_key], index[target_key])
            if pair in seen:
                continue
            seen.add(pair)
            edges.append(pair)

    return Graph(nodes=nodes, edges=edges, dropped=len(order) - len(kept))


def layout(found: Graph, *, steps: int = STEPS) -> list[tuple[float, float]]:
    """点の置き場を決める（0〜1 の枠に収めて返す）。

    素朴な力学モデル——**離れようとする力**（全部の組）と、線で結ばれた
    ものを**引き寄せる力**。

    **乱数を使わない。** 最初の置き場は円周に等間隔で置く。開くたびに形が
    変わると、前に見た図と比べられない（同じ入力なら同じ結果になることを
    テストで固定している）。
    """
    count = len(found.nodes)
    if count == 0:
        return []
    if count == 1:
        return [(0.5, 0.5)]

    places = [
        (
            0.5 + 0.4 * math.cos(2 * math.pi * number / count),
            0.5 + 0.4 * math.sin(2 * math.pi * number / count),
        )
        for number in range(count)
    ]
    ideal = 1.0 / math.sqrt(count)

    for step in range(steps):
        push = [[0.0, 0.0] for _ in range(count)]
        for one in range(count):
            x1, y1 = places[one]
            for other in range(one + 1, count):
                dx = x1 - places[other][0]
                dy = y1 - places[other][1]
                square = dx * dx + dy * dy or 1e-9
                force = ideal * ideal / square
                push[one][0] += dx * force
                push[one][1] += dy * force
                push[other][0] -= dx * force
                push[other][1] -= dy * force
        for source, target in found.edges:
            dx = places[source][0] - places[target][0]
            dy = places[source][1] - places[target][1]
            span = math.hypot(dx, dy) or 1e-9
            force = span / ideal
            push[source][0] -= dx / span * force
            push[source][1] -= dy / span * force
            push[target][0] += dx / span * force
            push[target][1] += dy / span * force
        # **だんだん動かなくする。** 最後まで同じ勢いだと収まらず揺れ続ける
        allowed = 0.1 * (1 - step / steps)
        for number in range(count):
            dx, dy = push[number]
            span = math.hypot(dx, dy) or 1e-9
            step_size = min(span, allowed)
            places[number] = (
                places[number][0] + dx / span * step_size,
                places[number][1] + dy / span * step_size,
            )

    return _fit(places)


def _fit(places: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """0〜1 の枠に収め直す。**縦横の比を保つ**（伸ばすと関係が歪んで見える）。"""
    xs = [x for x, _ in places]
    ys = [y for _, y in places]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    left = (min(xs) + max(xs)) / 2 - span / 2
    top = (min(ys) + max(ys)) / 2 - span / 2
    return [((x - left) / span, (y - top) / span) for x, y in places]
