"""テンプレートの差し込み（E-4）。

議事録や日報の雛形から新しいノートを作る。日付や題名は作った瞬間に
埋まってほしいので、`{{date}}` のような印を置いて差し替える。

**`core/` にあるので日時を渡す。** `datetime.now()` を中で呼ぶと、
テストが実行した瞬間に依存して再現しなくなる（CLAUDE.md §5 の純関数）。
"""

from datetime import datetime

import pytest

from hitofude.core.template import DATE_FORMAT, daily_title, expand

NOW = datetime(2026, 8, 14, 9, 5)


class TestDate:
    def test_日付が入る(self) -> None:
        assert expand("{{date}}", now=NOW).text == "2026-08-14"

    def test_書式を指定できる(self) -> None:
        assert expand("{{date:%Y年%m月%d日}}", now=NOW).text == "2026年08月14日"

    def test_時刻が入る(self) -> None:
        assert expand("{{time}}", now=NOW).text == "09:05"

    def test_時刻の書式も指定できる(self) -> None:
        assert expand("{{time:%H時%M分}}", now=NOW).text == "09時05分"

    def test_同じ印が何度でも入る(self) -> None:
        assert expand("{{date}} と {{date}}", now=NOW).text == "2026-08-14 と 2026-08-14"

    def test_前後の文字を巻き込まない(self) -> None:
        assert expand("# {{date}} の記録", now=NOW).text == "# 2026-08-14 の記録"


class TestTitle:
    def test_題名が入る(self) -> None:
        assert expand("# {{title}}", now=NOW, title="定例会議").text == "# 定例会議"

    def test_題名を渡さなければ空になる(self) -> None:
        assert expand("# {{title}}", now=NOW).text == "# "


class TestCursor:
    """`{{cursor}}` は書き始める場所。印そのものは残さない。"""

    def test_印は消える(self) -> None:
        assert expand("本文\n{{cursor}}", now=NOW).text == "本文\n"

    def test_位置を返す(self) -> None:
        assert expand("本文\n{{cursor}}", now=NOW).cursor == 3

    def test_無ければNone(self) -> None:
        assert expand("本文", now=NOW).cursor is None

    def test_差し込みのあとの位置になる(self) -> None:
        """`{{date}}` が伸びたぶんだけ後ろにずれる。"""
        found = expand("{{date}} {{cursor}}", now=NOW)
        assert found.text == "2026-08-14 "
        assert found.cursor == len(found.text)

    def test_2つ書いても最初のところ(self) -> None:
        found = expand("あ{{cursor}}い{{cursor}}う", now=NOW)
        assert found.text == "あいう"
        assert found.cursor == 1


class TestUnknown:
    """知らない印は**そのまま残す**。

    消すと、書いた人には理由の分からない欠落になる。残っていれば
    「これは効かない」と目で分かる。R1（ソースが真実）と同じ考え方。
    """

    @pytest.mark.parametrize("text", ["{{author}}", "{{ }}", "{{date", "date}}", "{{}}"])
    def test_そのまま残る(self, text: str) -> None:
        assert expand(text, now=NOW).text == text

    def test_知らない印はカーソルに影響しない(self) -> None:
        assert expand("{{author}}", now=NOW).cursor is None


class TestPlain:
    def test_印が無ければそのまま(self) -> None:
        text = "# 議事録\n\n- 決めたこと\n"
        assert expand(text, now=NOW).text == text

    def test_空でも壊れない(self) -> None:
        assert expand("", now=NOW).text == ""

    def test_元の文字列を変えない(self) -> None:
        text = "{{date}}"
        expand(text, now=NOW)
        assert text == "{{date}}"

    def test_空白を挟んでも効く(self) -> None:
        assert expand("{{ date }}", now=NOW).text == "2026-08-14"


class TestDaily:
    def test_日付が題名になる(self) -> None:
        assert daily_title(NOW) == "2026-08-14"

    def test_書式は日付の既定と同じ(self) -> None:
        """ファイル名にも一覧にも出るので、並べたときに揃う形にする。"""
        assert daily_title(NOW) == NOW.strftime(DATE_FORMAT)
