"""覚書（OboeGaki） — ライブプレビュー型 Markdown エディタ。

旧名は Hitofude（ユーザー決定 2026-08-27 に改名）。表示は「覚書」、
ファイル名・フォルダ名・ID 系は「OboeGaki」。Python パッケージ名
`hitofude` はユーザーに見えないので据え置き（ADR-0032）。
"""

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "覚書"
ORG_NAME = "OboeGaki"
# setup.py の CFBundleIdentifier と揃える。QSettings の保存先もこれで決まる。
ORG_DOMAIN = "app.oboegaki.editor"

# 旧名（引っ越し用）。初回起動時に旧 → 新へ写す・改名する
LEGACY_ORG_NAME = "Hitofude"
LEGACY_ORG_DOMAIN = "app.hitofude.editor"

try:
    __version__ = version("hitofude")
except PackageNotFoundError:  # pragma: no cover - インストールせずソースから動かした場合
    __version__ = "0.0.0+dev"

__all__ = [
    "APP_NAME",
    "LEGACY_ORG_DOMAIN",
    "LEGACY_ORG_NAME",
    "ORG_DOMAIN",
    "ORG_NAME",
    "__version__",
]
