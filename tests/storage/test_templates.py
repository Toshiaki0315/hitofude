"""テンプレートと日次ノート（E-4）。

雛形は vault の `templates/` に置く**ただの `.md`**。独自形式は使わない
（R1）。Finder で足しても、アプリから使えることが要点。

日次ノートは vault 直下に `2026-08-14.md` として作る。**サブフォルダに
分けない**（spec §7.1「フォルダ階層で分類しない」）。同じ日に何度呼んでも
同じノートを開く、が要点。
"""

from datetime import datetime
from pathlib import Path

import pytest

from hitofude.core.document import Note
from hitofude.storage.vault import (
    DAILY_TEMPLATE,
    TEMPLATES_DIR,
    Vault,
)

NOW = datetime(2026, 8, 14, 9, 5)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    target = Vault(tmp_path / "HitofudeNotes")
    target.ensure_layout()
    return target


def put_template(vault: Vault, name: str, text: str) -> Path:
    path = vault.templates_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestListing:
    def test_置いた雛形が並ぶ(self, vault) -> None:
        put_template(vault, "議事録.md", "# {{title}}\n")
        assert [path.name for path in vault.templates()] == ["議事録.md"]

    def test_名前順に並ぶ(self, vault) -> None:
        for name in ("日報.md", "議事録.md"):
            put_template(vault, name, "x")
        assert [path.stem for path in vault.templates()] == sorted(["日報", "議事録"])

    def test_マークダウン以外は並ばない(self, vault) -> None:
        put_template(vault, "メモ.txt", "x")
        assert vault.templates() == []

    def test_フォルダが無くても壊れない(self, vault) -> None:
        assert vault.templates() == []

    def test_雛形はノートの一覧に出てこない(self, vault) -> None:
        """`attachments/` と同じ扱い。雛形は書くものであって読むものではない。"""
        put_template(vault, "議事録.md", "# 議事録\n")
        assert list(vault.scan()) == []

    def test_雛形があってもvaultは空とみなす(self, vault) -> None:
        """初回の使い方ノートが置かれなくなっては困る。"""
        put_template(vault, "議事録.md", "# 議事録\n")
        assert vault.is_empty() is True


class TestCreateFromTemplate:
    def test_ノートができる(self, vault) -> None:
        path = put_template(vault, "議事録.md", "# {{title}}\n\n## 決めたこと\n")
        created = vault.create_from_template(path, title="定例会議", now=NOW)
        assert created.note.path.is_file()
        assert created.note.path.name == "定例会議.md"

    def test_印が埋まる(self, vault) -> None:
        path = put_template(vault, "日報.md", "# {{date}} の日報\n")
        created = vault.create_from_template(path, title="日報", now=NOW)
        assert "# 2026-08-14 の日報" in created.note.text

    def test_front_matterが付く(self, vault) -> None:
        """他のノートと同じ扱いになること。"""
        path = put_template(vault, "議事録.md", "# 議事録\n")
        note = vault.create_from_template(path, title="議事録", now=NOW).note
        assert note.id is not None
        assert note.meta["created"]

    def test_雛形のfront_matterは持ち込まない(self, vault) -> None:
        """**雛形の `id` を写すと、2 つのノートが同じ ID になる。**

        索引はノートを ID で数えるので、写した瞬間に片方が消えたように見える。
        """
        path = put_template(vault, "議事録.md", "---\nid: FAKE123\n---\n\n# 議事録\n")
        note = vault.create_from_template(path, title="議事録", now=NOW).note
        assert "FAKE123" not in note.text
        assert note.id != "FAKE123"

    def test_題名を省くと雛形の名前になる(self, vault) -> None:
        path = put_template(vault, "議事録.md", "# {{title}}\n")
        created = vault.create_from_template(path, now=NOW)
        assert created.note.path.name == "議事録.md"
        assert "# 議事録" in created.note.text

    def test_キャレットの位置を返す(self, vault) -> None:
        path = put_template(vault, "議事録.md", "# 議事録\n\n{{cursor}}\n")
        created = vault.create_from_template(path, now=NOW)
        assert created.cursor is not None
        # front matter のぶんだけ後ろにある（本文の頭ではない）
        assert created.note.text[created.cursor :] == "\n"

    def test_印が無ければNone(self, vault) -> None:
        path = put_template(vault, "議事録.md", "# 議事録\n")
        assert vault.create_from_template(path, now=NOW).cursor is None

    def test_雛形は書き換わらない(self, vault) -> None:
        """R1: 差し込みは一方通行。"""
        path = put_template(vault, "日報.md", "# {{date}}\n")
        vault.create_from_template(path, now=NOW)
        assert path.read_text(encoding="utf-8") == "# {{date}}\n"

    def test_同じ雛形から2つ作れる(self, vault) -> None:
        path = put_template(vault, "議事録.md", "# 議事録\n")
        first = vault.create_from_template(path, now=NOW).note
        second = vault.create_from_template(path, now=NOW).note
        assert first.path != second.path
        assert first.id != second.id

    def test_保管フォルダの外の雛形は読まない(self, vault, tmp_path: Path) -> None:
        """**パスは手で編集できる。** 外のファイルをノートに変えさせない。"""
        outside = tmp_path / "秘密.md"
        outside.write_text("# 秘密\n", encoding="utf-8")
        with pytest.raises(ValueError):
            vault.create_from_template(outside, now=NOW)


class TestDailyNote:
    def test_日付が題名になる(self, vault) -> None:
        note = vault.daily_note(NOW).note
        assert note.path.name == "2026-08-14.md"

    def test_同じ日は同じノートを返す(self, vault) -> None:
        """**作り直さない。** 2 つできると、書いたほうが分からなくなる。"""
        first = vault.daily_note(NOW).note
        second = vault.daily_note(NOW).note
        assert first.path == second.path
        assert first.id == second.id

    def test_書いた内容を消さない(self, vault) -> None:
        note = vault.daily_note(NOW).note
        vault.write(note.path, note.text + "\n打った行\n")
        assert "打った行" in vault.daily_note(NOW).note.text

    def test_別の日は別のノート(self, vault) -> None:
        other = vault.daily_note(datetime(2026, 8, 15, 9, 0)).note
        assert other.path.name == "2026-08-15.md"

    def test_雛形があれば使う(self, vault) -> None:
        put_template(vault, DAILY_TEMPLATE, "# {{date}}\n\n## やること\n")
        assert "## やること" in vault.daily_note(NOW).note.text

    def test_雛形が無くても作れる(self, vault) -> None:
        """日付の見出しだけの素のノートになる。"""
        assert "# 2026-08-14" in vault.daily_note(NOW).note.text

    def test_一覧に出る(self, vault) -> None:
        """雛形と違い、日次ノートはふつうのノート。"""
        note = vault.daily_note(NOW).note
        assert note.path in list(vault.scan())

    def test_既にあるノートには印を埋め直さない(self, vault) -> None:
        put_template(vault, DAILY_TEMPLATE, "# {{date}}\n{{cursor}}\n")
        vault.daily_note(NOW)
        assert vault.daily_note(NOW).cursor is None


class TestSeedTemplates:
    """初回だけ既定の雛形を置く。使い方ノートと同じ考え方。"""

    def test_空のvaultに置かれる(self, vault) -> None:
        placed = vault.seed_templates()
        assert placed
        assert all(path.is_file() for path in placed)

    def test_日次の雛形が入っている(self, vault) -> None:
        vault.seed_templates()
        assert (vault.templates_dir / DAILY_TEMPLATE).is_file()

    def test_二度目は置かない(self, vault) -> None:
        vault.seed_templates()
        assert vault.seed_templates() == []

    def test_手で消した雛形を復活させない(self, vault) -> None:
        for path in vault.seed_templates():
            path.unlink()
        assert vault.seed_templates() == []

    def test_同じ名前の雛形を上書きしない(self, vault) -> None:
        put_template(vault, DAILY_TEMPLATE, "# 自分で書いた雛形\n")
        vault.seed_templates()
        text = (vault.templates_dir / DAILY_TEMPLATE).read_text(encoding="utf-8")
        assert text == "# 自分で書いた雛形\n"

    def test_置いた雛形はそのまま使える(self, vault) -> None:
        vault.seed_templates()
        for path in vault.templates():
            note = vault.create_from_template(path, now=NOW).note
            assert Note.read(note.path).text

    def test_雛形のフォルダは走査されない(self, vault) -> None:
        vault.seed_templates()
        assert list(vault.scan()) == []
        assert (vault.root / TEMPLATES_DIR).is_dir()


class TestAddingNewTemplates:
    """あとから増えた雛形が、既に使っている vault にも届く（ユーザー報告）。

    印（`templates-seeded`）は「一度置いたら二度と置き直さない」ためのもの
    だが、**印があるだけで新しい雛形まで置かれなくなっていた**。
    `PowerPoint下書き` を足しても、既存の保管フォルダには現れない。

    印に**置いた名前を記録する**ことにした。名前が無いものだけ置くので、
    新しい雛形は届き、**手で消したものは復活しない**（名前が残っている）。
    """

    def test_あとから増えた雛形が置かれる(self, vault) -> None:
        vault.seed_templates()
        (vault.templates_dir / "新しい雛形.md").unlink(missing_ok=True)

        # あとから既定が増えた状況を作る
        import hitofude.storage.vault as module

        original = module.DEFAULT_TEMPLATES
        module.DEFAULT_TEMPLATES = (*original, "議事録.md")
        try:
            again = vault.seed_templates()
        finally:
            module.DEFAULT_TEMPLATES = original
        assert again == []  # 既に置いた名前は増やさない

    def test_置いた名前を印に残す(self, vault) -> None:
        from hitofude.storage.vault import TEMPLATES_MARKER

        vault.seed_templates()
        marker = (vault.managed_dir / TEMPLATES_MARKER).read_text(encoding="utf-8")
        assert "日次.md" in marker
        assert "PowerPoint下書き.md" in marker

    def test_古い印でも新しい雛形だけ置く(self, vault) -> None:
        """更新前の印は日時しか持っていない。**そこに何が置かれたかは
        分かっている**ので、その分は置き直さない。"""
        from hitofude.storage.vault import TEMPLATES_MARKER

        marker = vault.managed_dir / TEMPLATES_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("2026-08-14T09:05:00+09:00", encoding="utf-8")

        placed = vault.seed_templates()
        assert [path.name for path in placed] == ["PowerPoint下書き.md"]

    def test_手で消した雛形は復活しない(self, vault) -> None:
        vault.seed_templates()
        (vault.templates_dir / "日報.md").unlink()
        assert vault.seed_templates() == []
        assert not (vault.templates_dir / "日報.md").exists()


class TestPowerPointTemplate:
    """PowerPoint の下書き用の雛形（ユーザー要望 / F-5）。

    表紙と各ページの形が入っているので、**書き出しの決まりを覚えなくても
    書き始められる**。
    """

    def test_置かれる(self, vault) -> None:
        vault.seed_templates()
        assert (vault.templates_dir / "PowerPoint下書き.md").is_file()

    def test_表紙と複数の枚がある(self, vault) -> None:
        vault.seed_templates()
        text = (vault.templates_dir / "PowerPoint下書き.md").read_text(encoding="utf-8")
        assert text.startswith("# ")
        assert text.count("\n## ") >= 3

    def test_印が埋まる(self, vault) -> None:
        vault.seed_templates()
        created = vault.create_from_template(
            vault.templates_dir / "PowerPoint下書き.md", title="社内提案", now=NOW
        )
        assert "# 社内提案" in created.note.text
        assert "{{" not in created.note.text

    def test_書き出すとスライドになる(self, vault, tmp_path: Path) -> None:
        """**雛形がそのまま通ること。** 書けても書き出せなければ意味がない。"""
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from hitofude.editor.pptx_export import write_pptx

        QApplication.instance() or QApplication([])
        vault.seed_templates()
        created = vault.create_from_template(
            vault.templates_dir / "PowerPoint下書き.md", title="社内提案", now=NOW
        )
        target = write_pptx(tmp_path / "提案.pptx", created.note.text, base_path=vault.root)

        from pptx import Presentation

        presentation = Presentation(str(target))
        assert len(presentation.slides) >= 5  # 表紙 + 各ページ
