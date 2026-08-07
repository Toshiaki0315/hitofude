"""ゴールデンテストのスナップショットを再生成する（spec §10）。

    uv run python scripts/update_golden.py

**生成した差分は必ず目で確認すること。** 落ちたテストを更新で黙らせると、
意図しない装飾の変化を捕まえるというこのテストの目的が失われる。
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from tests.editor.golden import golden_path, snapshot  # noqa: E402

FIXTURES = ("basic", "japanese", "edge_cases")


def main() -> None:
    QApplication.instance() or QApplication([])
    fixtures_dir = ROOT / "tests" / "fixtures"
    (fixtures_dir / "golden").mkdir(exist_ok=True)

    for name in FIXTURES:
        source = (fixtures_dir / f"{name}.md").read_text(encoding="utf-8")
        target = golden_path(fixtures_dir, name)
        payload = json.dumps(snapshot(source), ensure_ascii=False, indent=2) + "\n"
        target.write_text(payload, encoding="utf-8", newline="\n")
        print(f"{target.relative_to(ROOT)}: {len(payload.splitlines()):,} 行")


if __name__ == "__main__":
    main()
