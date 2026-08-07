"""性能計測用フィクスチャ `tests/fixtures/large.md` を生成する（spec §10）。

出力は**決定的**（乱数シード固定）。生成物をリポジトリにコミットしているのは、
性能の実測値を時期やマシンをまたいで比較するため。生成側を変えると過去の
計測値と比較できなくなるので、変更するときは基準値も取り直すこと。

    uv run python scripts/gen_large_fixture.py
"""

import random
import re
from pathlib import Path

TARGET_WORDS = 10_000
SEED = 20260808

OUTPUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "large.md"

_SENTENCES = [
    "書くという行為は、考えを外に出して初めて形が定まる。",
    "エディタは書く速度を落としてはいけない。",
    "**強調**は文の途中で唐突に現れることが多い。",
    "設計上の判断はあとから理由を思い出せる形で残す。",
    "The quick brown fox jumps over the lazy dog near the river bank.",
    "入力遅延が 16ms を超えると、指の動きと画面がずれて感じられる。",
    "`toPlainText()` の結果がそのまま保存内容になる。",
    "往復変換を挟まない設計は、データ破損を構造的に防ぐ。",
    "*斜体*と~~取り消し~~を同じ段落に混ぜても破綻しないこと。",
    "Rendering must stay incremental; a full rehighlight breaks the frame budget.",
    "朝の光が机の上に落ちて、昨日の続きを促している。",
    "タグは #work のように書き、#work/会議 で階層にする。",
]

_CODE = [
    ("python", ["def scan(text: str) -> list[InlineSpan]:", "    return []"]),
    ("sql", ["SELECT title FROM notes", "WHERE trashed = 0;"]),
    ("sh", ["# コメント行", "uv run pytest -q"]),
]


def _count_words(text: str) -> int:
    """英数字は空白区切り、CJK は 2 文字で 1 語として概算する。"""
    latin = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk = len(re.findall(r"[぀-ヿ一-鿿]", text))
    return latin + cjk // 2


def _blocks(rng: random.Random, index: int) -> list[str]:
    kind = index % 7
    if kind == 0:
        return [f"## セクション {index}", "", rng.choice(_SENTENCES), ""]
    if kind == 1:
        return [rng.choice(_SENTENCES) + rng.choice(_SENTENCES), ""]
    if kind == 2:
        return [f"- {rng.choice(_SENTENCES)}" for _ in range(3)] + [""]
    if kind == 3:
        return [f"{n}. {rng.choice(_SENTENCES)}" for n in range(1, 4)] + [""]
    if kind == 4:
        lang, body = rng.choice(_CODE)
        return [f"```{lang}", *body, "```", ""]
    if kind == 5:
        return ["> " + rng.choice(_SENTENCES), "", "- [ ] やること", "- [x] 済み", ""]
    return [
        "| 項目 | 値 |",
        "|---|---|",
        f"| 行 {index} | {rng.randint(1, 999)} |",
        "",
    ]


def main() -> None:
    rng = random.Random(SEED)
    lines = ["---", "id: 01J9XQ2F8K7M3N5PLARGE", "pinned: false", "---", "", "# 大きなノート", ""]

    index = 0
    while _count_words("\n".join(lines)) < TARGET_WORDS:
        lines.extend(_blocks(rng, index))
        index += 1

    text = "\n".join(lines) + "\n"
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"{OUTPUT}: {_count_words(text):,} 語 / {len(text.splitlines()):,} 行 / {len(text):,} 文字"
    )


if __name__ == "__main__":
    main()
