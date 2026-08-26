"""版の履歴（提案 6 / ADR-0023）。

保存のたびに全文を 1 ファイルとして残し、「昨日の状態に戻す」を可能にする。
**差分にしない**（壊れたときに何も戻せなくなる）。**id で分ける**
（題名は変わるが id は変わらない）。

ここは Qt を知らない層。**どこから呼ぶかは UI の仕事**。
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hitofude.storage import history


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / ".hitofude" / "history"


NOTE_ID = "01M0DY2PZ0B6K8QH6683FSKECF"
NOW = datetime(2026, 8, 20, 10, 0, 0)


class TestKeep:
    def test_残せる(self, root) -> None:
        saved = history.keep(root, NOTE_ID, "# 会議メモ\n\n本文\n", now=NOW)
        assert saved is not None
        assert saved.read_text(encoding="utf-8") == "# 会議メモ\n\n本文\n"

    def test_素のmdとして読める(self, root) -> None:
        """**アプリが無くても Finder から開ける**（R1 の精神）。"""
        saved = history.keep(root, NOTE_ID, "# メモ\n", now=NOW)
        assert saved.suffix == ".md"

    def test_idで分ける(self, root) -> None:
        """題名（ファイル名）は変わるが、id は変わらない。"""
        saved = history.keep(root, NOTE_ID, "# メモ\n", now=NOW)
        assert saved.parent.name == NOTE_ID

    def test_日時が名前になる(self, root) -> None:
        saved = history.keep(root, NOTE_ID, "# メモ\n", now=NOW)
        assert saved.stem.startswith("2026-08-20T10-00-00")

    def test_空の本文は残さない(self, root) -> None:
        """新規ノートを開いただけで版が増えない。"""
        assert history.keep(root, NOTE_ID, "   \n", now=NOW) is None


class TestInterval:
    """**間引く。** 自動保存は打ち終わって 0.8 秒で走るので、1 版/保存に
    すると 1 時間の執筆で数百版になる。"""

    def test_間隔が空いていなければ残さない(self, root) -> None:
        history.keep(root, NOTE_ID, "# 一版目\n", now=NOW)
        soon = NOW + timedelta(minutes=1)
        assert history.keep(root, NOTE_ID, "# 二版目\n", now=soon) is None

    def test_間隔が空けば残す(self, root) -> None:
        history.keep(root, NOTE_ID, "# 一版目\n", now=NOW)
        later = NOW + timedelta(minutes=history.DEFAULT_INTERVAL_MINUTES)
        assert history.keep(root, NOTE_ID, "# 二版目\n", now=later) is not None

    def test_同じ内容なら残さない(self, root) -> None:
        """**打っていないのに版が増えない。** 開き直しただけの保存もある。"""
        history.keep(root, NOTE_ID, "# 同じ\n", now=NOW)
        later = NOW + timedelta(hours=1)
        assert history.keep(root, NOTE_ID, "# 同じ\n", now=later) is None

    def test_必ず残すこともできる(self, root) -> None:
        """戻す直前は間隔に関係なく残す（戻す操作も取り消せるように）。"""
        history.keep(root, NOTE_ID, "# 一版目\n", now=NOW)
        soon = NOW + timedelta(seconds=10)
        assert history.keep(root, NOTE_ID, "# 二版目\n", now=soon, force=True) is not None


class TestVersions:
    def test_新しい順に並ぶ(self, root) -> None:
        # **既定の間引きに引っかからない間隔で置く。** ここで見たいのは並び
        for minutes, text in ((0, "# 一\n"), (60, "# 二\n"), (120, "# 三\n")):
            history.keep(root, NOTE_ID, text, now=NOW + timedelta(minutes=minutes))

        found = history.versions(root, NOTE_ID)
        assert [version.saved_at.hour for version in found] == [12, 11, 10]

    def test_中身が読める(self, root) -> None:
        history.keep(root, NOTE_ID, "# 中身\n", now=NOW)
        version = history.versions(root, NOTE_ID)[0]
        assert version.read() == "# 中身\n"

    def test_題名が分かる(self, root) -> None:
        """一覧に「そのときの題名」を出せると、どれか見当が付く。"""
        history.keep(root, NOTE_ID, "# その時の題名\n\n本文\n", now=NOW)
        assert history.versions(root, NOTE_ID)[0].title == "その時の題名"

    def test_無ければ空(self, root) -> None:
        assert history.versions(root, NOTE_ID) == []


class TestPrune:
    def test_多すぎる版を捨てる(self, root) -> None:
        for minutes in range(history.MAX_VERSIONS + 10):
            history.keep(root, NOTE_ID, f"# {minutes}\n", now=NOW + timedelta(hours=minutes))

        history.prune(root, now=NOW + timedelta(hours=history.MAX_VERSIONS + 10))
        assert len(history.versions(root, NOTE_ID)) == history.MAX_VERSIONS

    def test_古い版から捨てる(self, root) -> None:
        for minutes in range(history.MAX_VERSIONS + 1):
            history.keep(root, NOTE_ID, f"# {minutes}\n", now=NOW + timedelta(hours=minutes))

        history.prune(root, now=NOW + timedelta(hours=history.MAX_VERSIONS + 1))
        remaining = [version.read() for version in history.versions(root, NOTE_ID)]
        assert "# 0\n" not in remaining

    def test_古すぎる版を捨てる(self, root) -> None:
        history.keep(root, NOTE_ID, "# 大昔\n", now=NOW)
        history.prune(root, now=NOW + timedelta(days=history.MAX_DAYS + 1))
        assert history.versions(root, NOTE_ID) == []

    def test_新しい版は残す(self, root) -> None:
        history.keep(root, NOTE_ID, "# 最近\n", now=NOW)
        history.prune(root, now=NOW + timedelta(days=1))
        assert len(history.versions(root, NOTE_ID)) == 1

    def test_無くても壊れない(self, root) -> None:
        history.prune(root, now=NOW)


class TestSize:
    def test_使っている容量が分かる(self, root) -> None:
        """**容量は増える。** 見えないところで太らせない。"""
        history.keep(root, NOTE_ID, "あ" * 1000, now=NOW)
        assert history.total_bytes(root) > 1000


class TestLazyReads:
    """保存・整理の道で版の中身を読まない（コードレビュー指摘）。

    50 版 × 50k 字 ≈ 6.3MB（ADR-0023 の実測）を自動保存のたびに全読み
    していた。題名は一覧（ダイアログ）を開くときだけ読めばよい。
    """

    def test_一覧の組み立ては中身を読まない(self, tmp_path, monkeypatch) -> None:
        from hitofude.storage import history

        history.keep(tmp_path, "note", "# 題\n本文", now=datetime(2026, 8, 20, 10, 0))
        reads = []
        monkeypatch.setattr(history, "_title_of", lambda path: reads.append(path) or "題")
        found = history.versions(tmp_path, "note")
        assert len(found) == 1
        assert reads == []  # versions() だけでは読まない
        assert found[0].title == "題"
        assert len(reads) == 1  # 触ったときに初めて読む

    def test_間引きの判定は前の版を読まない(self, tmp_path, monkeypatch) -> None:
        from hitofude.storage import history

        history.keep(tmp_path, "note", "一版目", now=datetime(2026, 8, 20, 10, 0))
        reads = []
        original = history.Version.read
        monkeypatch.setattr(
            history.Version, "read", lambda self: reads.append(self.path) or original(self)
        )
        # 5 分未満 → 時刻だけで捨てられる。中身の比較は要らない
        kept = history.keep(tmp_path, "note", "二版目", now=datetime(2026, 8, 20, 10, 1))
        assert kept is None
        assert reads == []

    def test_整理も中身を読まない(self, tmp_path, monkeypatch) -> None:
        from hitofude.storage import history

        history.keep(tmp_path, "note", "古い版", now=datetime(2026, 1, 1, 10, 0))
        reads = []
        monkeypatch.setattr(history, "_title_of", lambda path: reads.append(path) or "x")
        removed = history.prune(tmp_path, now=datetime(2026, 8, 20, 10, 0))
        assert len(removed) == 1  # 30 日超は消える
        assert reads == []


class TestChosenInterval:
    """間引く間隔を選べるようにする（ユーザー要望 2026-08-24）。

    既定の 5 分は「打ちながら数百版にならない」ための下限だったが、
    どれくらい細かく残したいかは書く人によって違う。
    """

    def test_選んだ間隔まで待つ(self, root) -> None:
        history.keep(root, NOTE_ID, "# 一版目\n", now=NOW)
        after = NOW + timedelta(minutes=20)
        assert history.keep(root, NOTE_ID, "# 二版目\n", now=after, interval_minutes=30) is None
        assert history.keep(root, NOTE_ID, "# 二版目\n", now=after, interval_minutes=15) is not None

    def test_なしなら残さない(self, root) -> None:
        """「なし」は `Cmd+S` を押したときだけ残す（ユーザーの選択）。"""
        assert history.keep(root, NOTE_ID, "# 初版\n", now=NOW, interval_minutes=0) is None

    def test_なしでも指示されたら残す(self, root) -> None:
        saved = history.keep(root, NOTE_ID, "# 初版\n", now=NOW, interval_minutes=0, force=True)
        assert saved is not None

    def test_選べる間隔は5つ(self) -> None:
        assert history.INTERVAL_CHOICES == (0, 15, 30, 60, 120)


class TestRekey:
    """鍵が変わったときに置き場を付け替える（コードレビュー指摘 2026-08-24）。

    front matter の無いノートは鍵がパスなので、移動・改名で鍵が変わる。
    """

    def test_置き場を移す(self, root) -> None:
        history.keep(root, "path:外から.md", "# 外から\n", now=NOW)
        moved = history.rekey(root, "path:外から.md", "path:作業/外から.md")
        assert moved is not None
        assert len(history.versions(root, "path:作業/外から.md")) == 1
        assert history.versions(root, "path:外から.md") == []

    def test_同じ鍵なら何もしない(self, root) -> None:
        history.keep(root, "path:同じ.md", "# 同じ\n", now=NOW)
        assert history.rekey(root, "path:同じ.md", "path:同じ.md") is None

    def test_版が無ければ何もしない(self, root) -> None:
        assert history.rekey(root, "path:無い.md", "path:先.md") is None

    def test_行き先にも版があれば混ぜる(self, root) -> None:
        """**どちらも捨てない。** 同じ名前のノートを消して作り直した後など。"""
        history.keep(root, "path:元.md", "# 元\n", now=NOW)
        history.keep(root, "path:先.md", "# 先\n", now=NOW + timedelta(hours=2))
        history.rekey(root, "path:元.md", "path:先.md")
        assert len(history.versions(root, "path:先.md")) == 2
        assert history.versions(root, "path:元.md") == []


class TestUnreadable:
    """読めない置き場（ユーザー報告 2026-08-26）。

    `.app` を初めて開くと macOS が書類フォルダの許可を尋ねる。**許可しない**と
    `iterdir()` が PermissionError を投げ、掃除の途中でアプリごと落ちていた
    （py2app の "Launch error"）。掃除は片付けであって、**起動を止めてよい
    理由にはならない**。
    """

    def test_権限が無くても落ちない(self, tmp_path, monkeypatch) -> None:
        root = tmp_path / "history"
        (root / "note").mkdir(parents=True)

        def denied(self):
            raise PermissionError(1, "Operation not permitted", str(self))

        monkeypatch.setattr(Path, "iterdir", denied)
        assert history.prune(root, now=datetime(2026, 8, 26, 12, 0)) == []
