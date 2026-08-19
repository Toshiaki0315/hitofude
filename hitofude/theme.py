"""配色定義（spec §5.3）。

色は QPalette とシンタックスハイライタの両方へ流し込むため、Qt 型ではなく
16 進文字列で持つ。Phase 2（タスク 2-10）で装飾用の色を追加していく。
"""

from dataclasses import dataclass
from enum import Enum


class ThemeMode(Enum):
    """ユーザーが選ぶテーマ。値は QSettings に保存する文字列。"""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class ThemeColors:
    """1 テーマ分の配色。すべて `#RRGGBB` または `#AARRGGBB`。"""

    is_dark: bool
    background: str
    foreground: str
    muted_foreground: str
    accent: str
    selection_background: str
    code_background: str
    code_foreground: str
    quote_bar: str
    quote_foreground: str
    highlight_background: str
    tag_background: str
    tag_foreground: str
    rule: str
    search_highlight: str
    pin_mark: str
    note_info: str
    """`:::note info` の色（B-3）。背景の薄い緑に合わせた緑（ユーザー要望）。"""

    note_warn: str
    """`:::note warn` の色（B-3）。"""

    note_alert: str
    """`:::note alert` の色（B-3）。"""

    note_info_background: str
    """`:::note info` の背景（ユーザー要望）。薄い緑。"""

    note_warn_background: str
    """`:::note warn` の背景。薄い黄。"""

    note_alert_background: str
    """`:::note alert` の背景。薄い赤。"""


LIGHT = ThemeColors(
    is_dark=False,
    background="#FFFFFF",
    foreground="#1D1D1F",
    muted_foreground="#8A8A8E",
    accent="#D2553C",
    selection_background="#CCE2FF",
    code_background="#F0F0F2",  # spec §5.2
    code_foreground="#3A3A3C",
    quote_bar="#C7C7CC",
    quote_foreground="#6B6B70",  # spec §5.2: 60% グレー
    highlight_background="#FFF3A0",  # spec §5.2
    tag_background="#EDEDF0",
    tag_foreground="#5A5A60",
    rule="#E0E0E4",
    # 検索の下敷き。`::ハイライト::` と見分けが付く色にする
    search_highlight="#FFD79B",
    # ピン留めの印。強調色とは別にする（星と分かる金色）
    pin_mark="#E0A100",
    # `:::note` の囲み。3 つが**並んだときに見分けられる**こと（実際に並べて調整した）
    note_info="#2E9E5B",
    note_warn="#B26B00",
    note_alert="#C0392B",
    # 背景は薄く（ユーザー要望: info 薄い緑 / warn 薄い黄 / alert 薄い赤）。
    # 本文の黒が乗っても読める濃さに抑える
    note_info_background="#E8F5E9",
    note_warn_background="#FFF8E1",
    note_alert_background="#FDECEC",
)

DARK = ThemeColors(
    is_dark=True,
    background="#1C1C1E",
    foreground="#E8E8EA",
    muted_foreground="#7C7C84",
    accent="#FF7A5C",
    selection_background="#2F5480",
    code_background="#2A2A2E",
    code_foreground="#D6D6DA",
    quote_bar="#4A4A50",
    quote_foreground="#A0A0A8",
    highlight_background="#6B5D1F",
    tag_background="#3A3A42",
    tag_foreground="#C9C9D1",
    rule="#3C3C42",
    search_highlight="#7A5A28",
    pin_mark="#FFCC33",
    note_info="#7CC47F",
    note_warn="#E0A100",
    note_alert="#FF6B5E",
    # ダークでは沈んだ同系色。明るい色をそのまま使うと発光して見える
    note_info_background="#1E2B21",
    note_warn_background="#2E2913",
    note_alert_background="#33201F",
)


def colors_for(mode: ThemeMode, *, system_is_dark: bool = False) -> ThemeColors:
    """テーマモードと OS の設定から実際の配色を決める。

    `system_is_dark` は呼び出し側（`app.py`）が Qt から取得して渡す。
    このモジュールを GUI 非依存に保つため、ここでは Qt を参照しない。
    """
    match mode:
        case ThemeMode.LIGHT:
            return LIGHT
        case ThemeMode.DARK:
            return DARK
        case ThemeMode.SYSTEM:
            return DARK if system_is_dark else LIGHT
