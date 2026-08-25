"""表のフォントが引けることの門番（2026-08-25）。

表は BIZ UDGothic で描く（ADR-0003:「全角＝半角×2」の前提）。この
フォントが無い環境では、表の検査 4 件が**桁ずれという分かりにくい形**で
落ちる（CI で 12 push 気づかれなかった）。原因がフォントなら、ここが
先に名指しで落ちる。

- 手元: フォントを入れる（macOS は Google Fonts の BIZ UDGothic / SIL OFL）
- CI: `HITOFUDE_FONT_DIR` の TTF を conftest がプロセス内で登録する
"""

import pytest
from PySide6.QtGui import QFont, QFontInfo

from hitofude.editor.painter_overlay import TABLE_FAMILIES

pytestmark = pytest.mark.gui


def test_表のフォントが引ける(qapp) -> None:
    font = QFont()
    font.setFamilies(TABLE_FAMILIES)
    resolved = QFontInfo(font).family()
    assert resolved == TABLE_FAMILIES[0], (
        f"表のフォントが {resolved} に落ちている。BIZ UDGothic を入れるか、"
        "CI なら HITOFUDE_FONT_DIR が TTF を指しているか確かめること"
    )


def test_全角は半角のちょうど2倍(qapp) -> None:
    """ADR-0003 の前提そのもの。フォントが替わると桁の計算が全部狂う。"""
    from PySide6.QtGui import QFontMetricsF

    font = QFont()
    font.setFamilies(TABLE_FAMILIES)
    font.setPointSizeF(15.0)
    metrics = QFontMetricsF(font)
    assert metrics.horizontalAdvance("あ") == pytest.approx(metrics.horizontalAdvance("0") * 2)
