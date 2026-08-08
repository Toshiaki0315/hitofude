"""保管フォルダの外を指す参照を弾く（spec §7.1）。

本文も設定ファイルも**手で編集できる**。`![](../../../etc/passwd)` と
書かれても、保管フォルダの外を読みに行かない。

同じ判定が `config.py` / `editor/exporter.py` / `editor/image_cache.py` に
別々の実装で 3 つあり、`config` だけ `resolve()` を通しておらず
**シンボリックリンク経由の脱出を見ていなかった**。安全に関わる規則の実装が
複数あると、1 つ直しても他が残る。ここが唯一の実装。
"""

from pathlib import Path
from urllib.parse import unquote

# 取りに行かないスキーム。描画や書き出しのたびに通信しない
REMOTE_SCHEMES = ("http:", "https:", "data:")


def relative_inside(base: Path | None, reference: str | Path) -> Path | None:
    """`base` の中を指す相対パスならそれを返す。外なら `None`。

    **存在は問わない。** まだ作られていない保存先にも使う。
    `..` だけでなく**シンボリックリンクによる脱出も見る**ため、
    実際に解決してから範囲を確かめる。
    """
    if base is None or not reference:
        return None

    candidate = Path(reference)
    if candidate.is_absolute():
        return None

    root = Path(base).resolve()
    if not (root / candidate).resolve().is_relative_to(root):
        return None
    return candidate


def resolve_inside(base: Path | None, reference: str | Path) -> Path | None:
    """`base` の中の実ファイルへ解決する。無ければ `None`。"""
    relative = relative_inside(base, reference)
    if relative is None:
        return None

    resolved = (Path(base).resolve() / relative).resolve()
    return resolved if resolved.is_file() else None


def resolve_reference(base: Path | None, reference: str) -> Path | None:
    """本文に書かれた参照（`![](…)` のパス）を実ファイルへ解決する。

    `http(s)` と `data:` は `None`。パーセント符号化は戻し、`file://` は剥がす。
    """
    if not reference or reference.startswith(REMOTE_SCHEMES):
        return None
    return resolve_inside(base, unquote(reference.removeprefix("file://")))
