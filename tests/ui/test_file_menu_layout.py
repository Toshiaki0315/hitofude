"""「ファイル」の並びを整える（ユーザー要望 2026-08-25）。

**20 項目・区切り 7 本まで太っていた**（検索 7 / 編集 9 / 表示 13 / ヘルプ 3）。
中身も混ざっていて、たまにしか走らせないメンテナンス（同期・索引の作り直し・
添付の片づけ・テンプレートの削除・モデルを降ろす）が、毎日使う
新規・保存と同じ高さに並んでいた。

**新しい階層は作らない。** メニューバーの本数は増やさず、`書き出す` と
同じくサブメニューに畳む（2026-08-24 に「形式が 4 つ直下に並ぶと
メニューが伸びる」で決めた作法をそのまま使う）。
"""

import pytest

pytestmark = pytest.mark.gui


def rows(menu) -> list[str]:
    """並びをそのまま。区切りは `─`。"""
    return ["─" if a.isSeparator() else a.text() for a in menu.actions()]


def labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


class TestSlimmer:
    def test_ファイルが短くなる(self, window) -> None:
        """**他のメニューと同じくらいに。** 20 項目は探せない。

        今は 15 行（うち 2 つは畳んだ入口）。この数字は目標ではなく
        **また太らないための歯止め**——足したくなったら、まず畳めないかを
        考える。
        """
        assert len(labels(window.menus["ファイル"])) <= 15

    def test_区切りを増やしすぎない(self, window) -> None:
        """区切りが多いと、かえって塊が読めない。"""
        found = rows(window.menus["ファイル"])
        assert found.count("─") <= 6

    def test_区切りが連続しない(self, window) -> None:
        """畳んだあとに空の塊が残っていないこと。"""
        found = rows(window.menus["ファイル"])
        assert "──" not in "".join("─" if r == "─" else "x" for r in found).replace("x", " ")

    def test_先頭と末尾は区切りでない(self, window) -> None:
        found = rows(window.menus["ファイル"])
        assert found[0] != "─"
        assert found[-1] != "─"


class TestMaintenance:
    """たまに走らせるメンテナンスは 1 つに畳む。"""

    def test_メンテナンスがサブメニューにある(self, window) -> None:
        assert "メンテナンス" in window.menus

    def test_中身がそろっている(self, window) -> None:
        found = labels(window.menus["メンテナンス"])
        assert set(found) == {
            "最新の情報に同期",
            "索引を作り直す",
            "使っていない添付を片づける…",
            "テンプレートを削除…",
            "モデルを降ろす",
        }

    def test_ファイルの直下からは消える(self, window) -> None:
        """**畳んだのに元にも残す、をしない**（同じ項目が 2 か所にあると迷う）。"""
        found = labels(window.menus["ファイル"])
        for label in ("索引を作り直す", "使っていない添付を片づける…", "モデルを降ろす"):
            assert label not in found

    def test_押せることは変わらない(self, window) -> None:
        """畳んでも動く。**台帳は 1 つ**（歯車もテストもここを引く）。"""
        for label in ("最新の情報に同期", "索引を作り直す", "モデルを降ろす"):
            assert label in window.menu_actions


class TestExport:
    def test_HTML_をコピーは書き出すの中(self, window) -> None:
        """**これも書き出し**（行き先がクリップボードなだけ）。"""
        assert "HTML をコピー" in labels(window.menus["書き出す"])

    def test_ファイルの直下からは消える(self, window) -> None:
        assert "HTML をコピー" not in labels(window.menus["ファイル"])

    def test_書き出す形は残っている(self, window) -> None:
        found = labels(window.menus["書き出す"])
        assert {"Markdown…", "HTML…", "PDF…", "PowerPoint…"} <= set(found)


class TestEverydayFirst:
    """**毎日使うものを上に。** 探す時間はここで決まる。"""

    def test_新規が一番上(self, window) -> None:
        assert labels(window.menus["ファイル"])[0] == "新規ノート"

    def test_保存がメンテナンスより上(self, window) -> None:
        found = rows(window.menus["ファイル"])
        assert found.index("保存") < found.index("メンテナンス")

    def test_設定は一番下(self, window) -> None:
        """macOS の慣習（アプリメニューへ移されるが、並びは末尾に置く）。"""
        assert labels(window.menus["ファイル"])[-1] == "設定…"


EXPECTED = frozenset(
    {
        "新規ノート",
        "テンプレートから新規…",
        "テンプレートを削除…",
        "今日のノート",
        "前の日のノート",
        "次の日のノート",
        "保存",
        "版の履歴…",
        "お気に入り",
        "ゴミ箱へ移動",
        "最新の情報に同期",
        "索引を作り直す",
        "モデルを降ろす",
        "読み込む…",
        "Markdown…",
        "HTML…",
        "PDF…",
        "PowerPoint…",
        "HTML をコピー",
        "ブラウザで確認",
        "印刷…",
        "使っていない添付を片づける…",
        "設定…",
    }
)


class TestNothingLost:
    """**畳むだけ。** 消したり増やしたりしない。"""

    def test_項目は全部どこかにある(self, window) -> None:
        found: set[str] = set()
        for title in ("ファイル", "書き出す", "メンテナンス"):
            found |= set(labels(window.menus[title]))
        found -= {"書き出す", "メンテナンス"}  # 畳んだ入口そのもの
        assert found == EXPECTED
