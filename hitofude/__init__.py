"""Hitofude — ライブプレビュー型 Markdown エディタ。"""

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "Hitofude"
ORG_NAME = "Hitofude"
# spec §8.1 の CFBundleIdentifier と揃える。QSettings の保存先もこれで決まる。
ORG_DOMAIN = "app.hitofude.editor"

try:
    __version__ = version("hitofude")
except PackageNotFoundError:  # pragma: no cover - インストールせずソースから動かした場合
    __version__ = "0.0.0+dev"

__all__ = ["APP_NAME", "ORG_DOMAIN", "ORG_NAME", "__version__"]
