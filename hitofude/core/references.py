"""本文が指している添付の名前を集める（E-5）。

未使用の添付を片づけるための判断材料。**取りこぼすと画像が消える**ので、
ここだけは他の走査と考え方が違う。

- **書き方を数え上げない。** `![](…)` も `[…](…)` も生の `<img src>` も
  参照型リンクも、すべて `attachments/名前` という並びを含む。その並びを
  拾えば、書き方を列挙しなくても届く（列挙は必ず漏れる）
- **コードブロックの中も数える。** タグやリンクの走査と違い、ここで
  答えるのは「本当に使っているか」ではなく「**消しても安全か**」。
  迷ったら残すのが正しい

`core/` にあるので PySide6 に依存しない（R3）。
"""

import re
from urllib.parse import unquote

# `attachments/` に続く、パスとして続きうる文字の並び。
# 記法の閉じ（`)` `"` `'` `>` `]`）と空白、クエリ・アンカーで切る
_REFERENCE_RE = re.compile(r"attachments/(?P<path>[^)\s\"'>\]<?#]+)")


def attachment_names(text: str) -> set[str]:
    """本文に出てくる添付のファイル名。

    パーセント符号化は戻す（`%E5%9B%B3.png` → `図.png`）。書かれたパスに
    フォルダが付いていても**末尾の名前だけ**を見る。添付は
    `attachments/` 直下にあり、名前で一意に決まる。
    """
    found: set[str] = set()
    for match in _REFERENCE_RE.finditer(text):
        name = unquote(match.group("path")).rsplit("/", 1)[-1]
        if name and name not in (".", ".."):
            found.add(name)
    return found
