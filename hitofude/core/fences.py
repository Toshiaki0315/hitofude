"""コードフェンスの開閉を行ごとに追う門番（レビュー 2026-08-25）。

同じ状態機械が `tags` と `wikilink`（2 か所）に 3 回書かれていた。
開閉の規則（CommonMark）はここに 1 つだけ置く:

- 前置の空白 3 つまでを許した ``` か ~~~ で開く
- **同じ文字**の、**同じ長さ以上**の区切りで閉じる
- 区切りの行そのものはコードでも本文でもない（どの利用者も飛ばす）

`block_parser.classify_line` はこれより多くのこと（言語名・行の種類）を
返す別物で、`highlightBlock` 用。全文を歩くだけの利用者はこちらで足りる。
"""

import re

_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")


class FenceGate:
    """フェンスの中に居るかどうかを覚える。1 回の走査に 1 つ作る。"""

    def __init__(self) -> None:
        self._fence: str | None = None

    def crosses(self, line: str) -> bool:
        """この行がフェンスの区切りなら状態を進めて True。"""
        found = _FENCE_RE.match(line)
        if found is None:
            return False
        marker = found.group("fence")
        if self._fence is None:
            self._fence = marker
        elif marker[0] == self._fence[0] and len(marker) >= len(self._fence):
            self._fence = None
        return True

    @property
    def inside(self) -> bool:
        """今フェンスの中か（区切り行を読んだ直後は「開いた後」の状態）。"""
        return self._fence is not None
