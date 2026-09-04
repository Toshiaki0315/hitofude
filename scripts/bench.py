"""性能の受け入れ基準（CLAUDE.md §7 / spec §6.6）を 1 コマンドで実測する。

    uv run python scripts/bench.py            # 3 基準を測って表で出す
    uv run python scripts/bench.py --strict   # 基準を超えたら exit 1
    uv run python scripts/bench.py --rebuild  # ダミー vault を作り直す

| 指標 | 基準 |
|---|---|
| キー入力 → 画面反映 | 95 パーセンタイル < 16ms（10,000 語のノート） |
| 全文検索 | < 200ms（5,000 ノートの vault） |
| 起動 → ウィンドウ表示 | < 1.5 秒 |

**大きな変更のあとに回す。** 性能は静かに壊れる——`QApplication.
setStyleSheet()` を 1 行足しただけでテストが 5 秒 → 53 秒になった実例が
ある（2026-08-24）。使い捨てスクリプトを毎回書かないための置き場。

- 打鍵は `tests/fixtures/large.md`（10,000 語・決定的）へ 'a' を 200 回
- 検索は `gen_dummy_vault.build()` の 5,000 ノート（決定的・使い回す）
- 起動は**子プロセス**で測る。同じプロセスで 2 度目の窓を作ると import と
  フォント列挙が温まっていて、実際の起動より 2 桁速く出る
"""

import argparse
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LARGE_NOTE = ROOT / "tests" / "fixtures" / "large.md"
BENCH_VAULT = Path(tempfile.gettempdir()) / "HitofudeBenchVault"

TYPING_BUDGET_MS = 16.0
SEARCH_BUDGET_MS = 200.0
STARTUP_BUDGET_MS = 1500.0

KEYSTROKES = 200
SEARCH_ROUNDS = 20


def bench_startup() -> float:
    """起動 → ウィンドウ表示（ms）。子プロセス 3 回の中央値。

    1 回だと OS のファイルキャッシュに左右される（冷えた初回だけ
    +600ms 出た実測がある）。使っているうちの起動感に近いのは温まった値。
    """
    return statistics.median(_startup_once() for _ in range(3))


def _startup_once() -> float:
    program = (
        "import sys, tempfile, time, os\n"
        "from pathlib import Path\n"
        "started = time.perf_counter()\n"
        "from PySide6.QtCore import QSettings, Qt\n"
        "from hitofude.app import create_application\n"
        "from hitofude.config import Config\n"
        "from hitofude.ui.main_window import MainWindow\n"
        "app = create_application([])\n"
        "tmp = Path(tempfile.mkdtemp())\n"
        "(tmp / 'Documents').mkdir()\n"
        "os.environ['HOME'] = str(tmp)\n"
        "config = Config(QSettings(str(tmp / 'b.ini'), QSettings.Format.IniFormat))\n"
        "config.vault_path = tmp / 'Notes'\n"
        "window = MainWindow(config)\n"
        "window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)\n"
        "window.show()\n"
        "app.processEvents()\n"
        "print((time.perf_counter() - started) * 1000)\n"
        "window.close()\n"
    )
    found = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True, cwd=ROOT
    )
    return float(found.stdout.strip().splitlines()[-1])


def bench_typing() -> float:
    """10,000 語のノートでの打鍵 95 パーセンタイル（ms）。"""
    import os

    from PySide6.QtCore import QEvent, QSettings, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    from hitofude.config import Config
    from hitofude.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Documents").mkdir()
    os.environ["HOME"] = str(tmp)
    config = Config(QSettings(str(tmp / "b.ini"), QSettings.Format.IniFormat))
    config.vault_path = tmp / "Notes"
    window = MainWindow(config)
    window.resize(1100, 720)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()

    note = window.vault.create("計測", LARGE_NOTE.read_text(encoding="utf-8"))
    window.vault_index.upsert_note(note, window.vault.root)
    window.refresh()
    window.open_note(note.path)
    app.processEvents()

    editor = window.editor
    editor.setFocus()
    times: list[float] = []
    for _ in range(KEYSTROKES):
        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a")
        started = time.perf_counter()
        app.sendEvent(editor, press)
        app.processEvents()
        times.append((time.perf_counter() - started) * 1000)
    window.close()
    return statistics.quantiles(times, n=20)[18]  # 95 パーセンタイル


def bench_search(*, rebuild: bool) -> float:
    """5,000 ノートの全文検索の中央値（ms）。vault は決定的なので使い回す。"""
    from gen_dummy_vault import DEFAULT_NOTES, build

    from hitofude.storage.index_db import INDEX_FILE, IndexDb
    from hitofude.storage.vault import Vault

    if rebuild or not BENCH_VAULT.is_dir():
        print(f"（ダミー vault を作っています… {BENCH_VAULT}）", flush=True)
        build(BENCH_VAULT, DEFAULT_NOTES)

    vault = Vault(BENCH_VAULT)
    db = IndexDb(vault.managed_dir / INDEX_FILE)
    try:
        db.sync(vault)
        samples: list[float] = []
        for _ in range(SEARCH_ROUNDS):
            started = time.perf_counter()
            db.search("予算について")
            samples.append((time.perf_counter() - started) * 1000)
        return statistics.median(samples)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="基準を超えたら exit 1")
    parser.add_argument("--rebuild", action="store_true", help="ダミー vault を作り直す")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    rows = [
        ("起動 → ウィンドウ表示", bench_startup(), STARTUP_BUDGET_MS),
        ("打鍵 95%（10,000 語）", bench_typing(), TYPING_BUDGET_MS),
        ("全文検索（5,000 ノート）", bench_search(rebuild=args.rebuild), SEARCH_BUDGET_MS),
    ]

    print()
    print(f"{'指標':<28}{'実測':>10}{'基準':>10}  判定")
    over = False
    for label, measured, budget in rows:
        passed = measured < budget
        over = over or not passed
        print(f"{label:<28}{measured:>8.1f}ms{budget:>8.0f}ms  {'○' if passed else '×'}")
    print()
    return 1 if (args.strict and over) else 0


if __name__ == "__main__":
    raise SystemExit(main())
