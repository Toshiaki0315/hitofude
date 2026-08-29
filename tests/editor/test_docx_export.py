"""Word への書き出し（U-5。ユーザー要望 2026-08-29）。

**提出物が Word 指定**の場面は日本の実務で多く、PDF では代替できない。
Bear・Typora・iA Writer にはある。

**ざっくり作って手で整える前提**（PowerPoint への書き出しと同じ方針）。
凝った体裁は狙わず、見出し・段落・箇条書き・表・コードが Word の
スタイルに乗っていればよい。

書き出したものを **python-docx で読み返して**確かめる。作れただけでは
中身の保証にならない。
"""

import pytest
from docx import Document

from hitofude.editor.docx_export import write_docx

pytestmark = []

NOTE = """# 会議メモ

決めたことを **太字** と *斜体* と `コード` で書く。

## 次にやること

- 見積もりを出す
- 日程を決める

1. まず確認
2. つぎに連絡

> 引用した一言

```python
print(1)
```

| 項目 | 担当 |
| --- | --- |
| 見積もり | 山田 |
| 日程 | 佐藤 |
"""


@pytest.fixture
def written(tmp_path):
    target = tmp_path / "会議メモ.docx"
    write_docx(target, NOTE)
    return Document(str(target))


def texts(document) -> list[str]:
    return [p.text for p in document.paragraphs]


class TestStructure:
    def test_見出しがスタイルに乗る(self, written) -> None:
        found = next(p for p in written.paragraphs if p.text == "会議メモ")
        assert found.style.name.startswith("Heading")

    def test_見出しの深さが伝わる(self, written) -> None:
        top = next(p for p in written.paragraphs if p.text == "会議メモ")
        second = next(p for p in written.paragraphs if p.text == "次にやること")
        assert top.style.name != second.style.name

    def test_段落が出る(self, written) -> None:
        assert any("決めたこと" in text for text in texts(written))

    def test_箇条書きがスタイルに乗る(self, written) -> None:
        found = next(p for p in written.paragraphs if p.text == "見積もりを出す")
        assert "List" in found.style.name

    def test_番号付きも出る(self, written) -> None:
        assert any("まず確認" in text for text in texts(written))

    def test_引用がスタイルに乗る(self, written) -> None:
        found = next(p for p in written.paragraphs if "引用した一言" in p.text)
        assert found.style.name in {"Quote", "Intense Quote"}

    def test_表が表になる(self, written) -> None:
        """**表を段落にしない。** Word の表として出す。"""
        assert written.tables
        table = written.tables[0]
        assert table.cell(0, 0).text == "項目"
        assert table.cell(1, 1).text == "山田"

    def test_コードは等幅(self, written) -> None:
        found = next(p for p in written.paragraphs if "print(1)" in p.text)
        assert found.runs and found.runs[0].font.name


class TestInline:
    """文中の装飾。**記号は残さない**（`**太字**` ではなく太字）。"""

    def test_太字になる(self, written) -> None:
        paragraph = next(p for p in written.paragraphs if "決めたこと" in p.text)
        assert any(run.bold and run.text == "太字" for run in paragraph.runs)

    def test_斜体になる(self, written) -> None:
        paragraph = next(p for p in written.paragraphs if "決めたこと" in p.text)
        assert any(run.italic and run.text == "斜体" for run in paragraph.runs)

    def test_記号が残らない(self, written) -> None:
        paragraph = next(p for p in written.paragraphs if "決めたこと" in p.text)
        assert "**" not in paragraph.text
        assert "`" not in paragraph.text


class TestQuiet:
    def test_front_matterは出さない(self, tmp_path) -> None:
        target = tmp_path / "a.docx"
        write_docx(target, "---\ncreated: 2026-08-29\n---\n\n# 題\n\n本文\n")
        assert not any("created" in text for text in texts(Document(str(target))))

    def test_空でも書ける(self, tmp_path) -> None:
        target = tmp_path / "b.docx"
        write_docx(target, "")
        assert target.is_file()


class TestTaskList:
    """チェックの状態を落とさない（レビュー指摘 2026-08-30）。

    `- [x] 済み` のマーカーごと削っていたので、**済んだかどうかが
    消えて**ただの箇条書きになっていた。記号は `core/html` と揃える
    （書き出し先が違っても同じ印）。
    """

    @pytest.fixture
    def tasks(self, tmp_path):
        target = tmp_path / "tasks.docx"
        write_docx(target, "# やること\n\n- [ ] まだ\n- [x] 済み\n")
        return Document(str(target))

    def test_未了の印が出る(self, tasks) -> None:
        assert any("☐" in text and "まだ" in text for text in texts(tasks))

    def test_済みの印が出る(self, tasks) -> None:
        assert any("☑" in text and "済み" in text for text in texts(tasks))

    def test_ふつうの箇条書きには付かない(self, tmp_path) -> None:
        target = tmp_path / "plain.docx"
        write_docx(target, "# 一覧\n\n- ただの項目\n")
        assert not any("☐" in text for text in texts(Document(str(target))))


class TestInlineMarkup:
    """記号を生のまま出さない（レビュー指摘 2026-08-30）。"""

    @pytest.fixture
    def written(self, tmp_path):
        target = tmp_path / "inline.docx"
        write_docx(
            target,
            "# 見本\n\n[Qiita](https://qiita.com) と [[会議メモ]] と ~~取り消し~~ を書く。\n",
        )
        return Document(str(target))

    def test_リンクは題名だけ出す(self, written) -> None:
        paragraph = next(p for p in written.paragraphs if "Qiita" in p.text)
        assert "https://qiita.com" not in paragraph.text
        assert "](" not in paragraph.text

    def test_ノートのリンクも記号を外す(self, written) -> None:
        paragraph = next(p for p in written.paragraphs if "会議メモ" in p.text)
        assert "[[" not in paragraph.text

    def test_打ち消し線になる(self, written) -> None:
        paragraph = next(p for p in written.paragraphs if "取り消し" in p.text)
        assert any(run.font.strike and run.text == "取り消し" for run in paragraph.runs)
        assert "~~" not in paragraph.text
