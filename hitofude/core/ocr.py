"""画像を文字にする（[ADR-0027](../../docs/adr/0027-ocr.md)）。

読み手は 2 つ。**既定は macOS**（実測 0.85 秒・誤りゼロ）で、手元の LLM は
大きなモデルを積める人向け（`gemma3:4b` は 17.3 秒かけて読み違えた）。

**ここは Qt を知らない**（R3）。外の道具（同梱の実行ファイル・Ollama）は
差し替えられるので、テストで実物を動かさない。
"""

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60.0
"""1 枚あたりの上限。実測 0.85 秒なので、届かないなら何かが違う。"""

TOOL_NAME = "hitofude-ocr"
"""同梱する実行ファイル（Swift + Vision。63KB）。"""

PROMPT = (
    "この画像に書かれている文字を、**そのまま**書き起こしてください。"
    "説明・要約・訳は不要です。文字が無ければ何も書かないでください。"
)


def tool_path() -> Path:
    """同梱した道具の場所。`.app` の中でも開発中でも同じ場所を指す。"""
    return Path(__file__).resolve().parent.parent / "resources" / "bin" / TOOL_NAME


class Engine(Enum):
    MAC = "mac"
    LLM = "llm"


DEFAULT_ENGINE = Engine.MAC
"""**速くて正確なほうを既定にする**（ADR-0027 の実測）。"""


class Unavailable(RuntimeError):
    """読み取れなかった。**押してから断らない**ための合図でもある。"""


Runner = Callable[[list[str], float], str]
"""`(コマンド, 待ちの上限)` → 出てきた文字。"""


def _run(args: list[str], timeout: float) -> str:
    found = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    return found.stdout


@dataclass(slots=True)
class MacEngine:
    """macOS の Vision に読ませる（同梱の実行ファイル経由）。

    **pyobjc は使わない。** 30MB 入るうえ、実測では結果が返らなかった
    （ADR-0027）。Swift の実行ファイルは 63KB で、そのまま動く。
    """

    tool: Path
    runner: Runner = field(default=_run)

    def available(self) -> bool:
        """道具があるか。**無ければ機能ごと畳む**（G-3 と同じ作法）。"""
        return self.tool.is_file()

    def read(self, image: Path) -> str:
        try:
            found = self.runner([str(self.tool), str(image)], TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("読み取れなかった: %s", error)
            raise Unavailable(str(error)) from error
        return tidy(found)


@dataclass(slots=True)
class LlmEngine:
    """手元の LLM に読ませる（画像を読めるモデルが要る）。

    **モデルは設定のものを使う。** 画像を見られないモデルを選ぶと、空か
    説明が返る。そのときは読み取れなかったものとして扱う。
    """

    client: object

    def available(self) -> bool:
        return bool(getattr(self.client, "available", lambda: False)())

    def read(self, image: Path) -> str:
        found = tidy(self.client.generate(PROMPT, images=[image.read_bytes()]))
        if not found:
            raise Unavailable("何も読み取れませんでした")
        return found


# 空行 3 つ以上。**行の中の空白は触らない**（表や字下げが崩れる）
_BLANK_RUN = re.compile(r"\n{3,}")


def tidy(text: str) -> str:
    """読み取った文字をノートに入れる前の手当て。**勝手に整形しない。**"""
    return _BLANK_RUN.sub("\n\n", text.strip())
