"""テーマ定義のテスト（タスク 0-B-1 / spec §5.3）。"""

import dataclasses

import pytest

from hitofude.theme import DARK, LIGHT, ThemeColors, ThemeMode, colors_for


def test_ThemeColorsはイミュータブルである() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        LIGHT.background = "#000000"  # type: ignore[misc]


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=["light", "dark"])
def test_全ての色フィールドが16進表記で埋まっている(theme: ThemeColors) -> None:
    for field in dataclasses.fields(theme):
        value = getattr(theme, field.name)
        if field.name == "is_dark":
            continue
        assert isinstance(value, str), field.name
        assert value.startswith("#"), f"{field.name}={value}"
        assert len(value) in (7, 9), f"{field.name}={value}"


def test_ライトとダークで全ての色が異なる() -> None:
    """片方を書き忘れて同じ値がコピーされている事故を防ぐ。"""
    same = [
        field.name
        for field in dataclasses.fields(ThemeColors)
        if field.name != "is_dark" and getattr(LIGHT, field.name) == getattr(DARK, field.name)
    ]
    assert not same, f"{same} がライト/ダークで同値"


def test_is_darkフラグが正しい() -> None:
    assert LIGHT.is_dark is False
    assert DARK.is_dark is True


@pytest.mark.parametrize(
    ("mode", "system_is_dark", "expected"),
    [
        (ThemeMode.LIGHT, False, LIGHT),
        (ThemeMode.LIGHT, True, LIGHT),
        (ThemeMode.DARK, False, DARK),
        (ThemeMode.DARK, True, DARK),
        (ThemeMode.SYSTEM, False, LIGHT),
        (ThemeMode.SYSTEM, True, DARK),
    ],
)
def test_colors_forはモードとシステム設定から配色を決める(
    mode: ThemeMode, system_is_dark: bool, expected: ThemeColors
) -> None:
    assert colors_for(mode, system_is_dark=system_is_dark) is expected


def test_ThemeModeは設定値として文字列で往復できる() -> None:
    """QSettings に保存するため（spec §4）。"""
    for mode in ThemeMode:
        assert ThemeMode(mode.value) is mode
