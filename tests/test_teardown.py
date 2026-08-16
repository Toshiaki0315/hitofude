"""テストが**終わったあと**に落ちないこと（exit 139 の回帰）。

全件通せば「合格」に見えるが、プロセスの終了コードは 139（SIGSEGV）に
なっていた。原因は本文でも UI でもなく、**終了処理の順番**にある。

Python 側で作った `QMimeData` をクリップボードに載せたまま終了すると、
Qt の後片付け（C++ の静的デストラクタ）が、既に終了した Python
インタプリタへ触りに行って落ちる。`tests/conftest.py` の
`_release_clipboard` が終了前に空にしている。

**中で pytest を動かして終了コードを見る。** 落ちるのはプロセスが
終わる瞬間なので、同じプロセスの中からは観測できない。
"""

import subprocess
import sys

import pytest


@pytest.mark.gui
def test_書き出しのテストは終了コード0で終わる() -> None:
    """`copy_html` を呼ぶテスト。放っておくと**必ず** 139 で終わる。"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/editor/test_exporter.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"終了コード {result.returncode}\n{result.stdout[-2000:]}"
