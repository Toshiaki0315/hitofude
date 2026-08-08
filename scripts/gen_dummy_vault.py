"""性能確認用のダミー vault を作る（spec §9 Phase 5, §6.6）。

    uv run python scripts/gen_dummy_vault.py --notes 5000 --out /tmp/DummyVault

5,000 ノートの vault でノート一覧のスクロールと全文検索を実測するために使う。
出力は決定的（乱数シード固定）なので、時期をまたいで同じ条件で測れる。
"""

import argparse
import random
import shutil
import time
from pathlib import Path

from hitofude.core.document import new_id
from hitofude.storage.index_db import IndexDb
from hitofude.storage.vault import Vault

SEED = 20260808
DEFAULT_NOTES = 5000

_TITLES = ["会議メモ", "読書メモ", "設計メモ", "調査ログ", "買い物リスト", "日報", "アイデア"]
_TAGS = ["work/会議", "work/企画", "work/調査", "private/読書", "private/家事", "idea"]
_SENTENCES = [
    "来期の**予算**について話した。",
    "第 3 章まで読んだ。要点は 3 つ。",
    "`toPlainText()` の結果がそのまま保存内容になる。",
    "入力遅延が 16ms を超えると指の動きと画面がずれて感じられる。",
    "The quick brown fox jumps over the lazy dog.",
    "人事の件は来週あらためて確認する。",
    "経費の精算を月末までに出すこと。",
    "- [ ] 資料を作る",
    "> 引用したい一文があった。",
]


def build(root: Path, count: int) -> None:
    if root.exists():
        shutil.rmtree(root)

    rng = random.Random(SEED)
    vault = Vault(root)
    vault.ensure_layout()

    for index in range(count):
        title = f"{rng.choice(_TITLES)}{index:05d}"
        body = "\n\n".join(rng.choice(_SENTENCES) for _ in range(rng.randint(3, 12)))
        tag = rng.choice(_TAGS)
        text = (
            f"---\nid: {new_id()}\npinned: {'true' if index % 200 == 0 else 'false'}\n---\n\n"
            f"# {title}\n\n{body}\n\n#{tag}\n"
        )
        (root / f"{title}.md").write_text(text, encoding="utf-8", newline="\n")


def measure(root: Path) -> None:
    vault = Vault(root)
    db = IndexDb(vault.managed_dir / "index.sqlite")
    try:
        started = time.perf_counter()
        result = db.sync(vault)
        print(
            f"索引構築        : {(time.perf_counter() - started) * 1000:8.0f} ms（{result.changed:,} 件）"
        )

        started = time.perf_counter()
        db.sync(vault)
        print(f"差分同期（無変更）: {(time.perf_counter() - started) * 1000:8.0f} ms")

        for label, call in (
            ("全文検索 6 文字", lambda: db.search("予算について")),
            ("全文検索 2 文字", lambda: db.search("人事")),
            ("タグ絞り込み", lambda: db.notes_with_tag("work")),
            ("タグツリー集計", db.tag_tree),
            ("一覧 50 件", lambda: db.notes(limit=50)),
        ):
            samples = []
            for _ in range(20):
                started = time.perf_counter()
                rows = call()
                samples.append((time.perf_counter() - started) * 1000)
            samples.sort()
            median = samples[len(samples) // 2]
            worst = samples[-1]
            verdict = "OK" if worst < 200 else "超過"
            print(
                f"{label:16}: {median:8.1f} ms（中央値）/ {worst:6.1f} ms（最大）"
                f" / {len(rows):,} 件  基準 <200ms {verdict}"
            )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=int, default=DEFAULT_NOTES, help="作るノート数")
    parser.add_argument("--out", type=Path, required=True, help="出力先ディレクトリ")
    parser.add_argument("--measure", action="store_true", help="作ったあとに実測する")
    args = parser.parse_args()

    started = time.perf_counter()
    build(args.out, args.notes)
    print(f"{args.notes:,} 件を {args.out} に生成: {(time.perf_counter() - started) * 1000:.0f} ms")

    if args.measure:
        measure(args.out)


if __name__ == "__main__":
    main()
