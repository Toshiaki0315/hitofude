"""ローカルLLM に読ませる（L-1 / [ADR-0025](../../docs/adr/0025-local-llm.md)）。

Ollama（別プロセス）へ HTTP で頼む。**ここは Qt を知らない**（R3）し、
ネイティブ拡張も持たない。通信の口は差し替えられるので、テストで
モデルを動かさずに振る舞いを固定できる。

**送り先は `127.0.0.1` に固定する。** 外へ出さないことがこの機能の前提で、
設定でも変えられないようにしてある（ADR-0025 の 3）。
"""

import base64
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from itertools import chain

from hitofude.core import frontmatter

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
"""**変えられない。** 設定に出すと「うっかり外に出す」道ができる。

ポートだけは設定から変えられる（`OLLAMA_HOST` で別のポートにしている人が
いる）。**相手の機械は変えられない**（ADR-0025 の 3）。
"""

DEFAULT_PORT = 11434


def endpoint(port: int = DEFAULT_PORT) -> str:
    """送り先。**`127.0.0.1` から動かせない。**"""
    return f"http://{HOST}:{port}"


DEFAULT_MODEL = "gemma3:4b"
"""実測で要約 1 本 12.8 秒（M4 / 32GB）。1b は日本語が壊れる（docs/ollama.md）。"""

CONTEXT_TOKENS = 8192
"""既定（多くのモデルで 4k）だと**長いノートが黙って切り捨てられる**。"""

CONTEXT_CHOICES = (4096, 8192, 16384, 32768)
"""設定で選べる長さ。**広げるほどメモリを食う**（docs/ollama.md）。"""

TIMEOUT_SECONDS = 120.0
"""12b 級に長いノートを読ませても届く長さ。"""

PROBE_TIMEOUT_SECONDS = 3.0
"""居るかどうかを確かめるだけの待ち時間。

**生成と同じだけ待たない。** `available()` / `models()` は起動時・
`Cmd+,`・`Cmd+6` から GUI スレッドで呼ばれる。繋がらない相手
（docs/ollama.md の SSH トンネルが半分開いている等）で 120 秒待つと、
窓がそのあいだ固まる。居るなら即答が返る問い合わせなので短くてよい。
"""

CHAR_LIMIT = 12000
"""本文をここまでにする。日本語 4,000 字 ≈ 2,000 トークンの実測から、
8k の文脈に指示と答えのぶんを残して収まる量（ADR-0025）。"""

TRUNCATED = "\n\n（ここから先は長いので渡していません）"

SOURCE_LIMIT = 5
"""質問に答えさせるとき、材料にするノートの数（L-2）。

多く渡すほど当たりは増えるが、**8k の文脈からあふれると黙って切れる**。
5 本 × 2,000 字で 1 万字、日本語で約 5,000 トークン。指示と答えのぶんが残る。
"""

SOURCE_CHARS = 2000
"""1 本あたりに渡す字数（L-2）。"""


class Task(Enum):
    SUMMARY = "summary"
    REVIEW = "review"


class NotRunning(RuntimeError):
    """Ollama が動いていない。**押してから断らない**ための合図でもある。"""


class TimedOut(RuntimeError):
    """待ち時間の内に返ってこなかった（ユーザー報告 2026-08-24）。

    **「繋がらない」と混ぜない。** 大きいモデルは読み込みだけで数分
    かかる（実測: gemma4:26b で最初の 1 行まで 391.9 秒）。切ったのを
    「動いているか確かめてください」と案内すると、動いているのに
    動いていないと言われて原因に辿り着けない。
    """


# **渡したものだけを見させる。** 知らないことを足されると、どこまでが
# ノートに書いてあった話か分からなくなる（NotebookLM 的な使い方の肝）
_COMMON = (
    "あなたは日本語で答える編集者です。**渡されたノート以外の知識を使わず**、"
    "書かれていないことは「ノートには書かれていません」と答えてください。"
)

_INSTRUCTIONS = {
    Task.SUMMARY: "次のノートの要点を、日本語の箇条書き 3〜5 行にまとめてください。",
    Task.REVIEW: (
        "次のノートを読んで、直すとよい点を日本語で挙げてください。"
        "曖昧な表現・矛盾・抜けている前提を中心に、**どの部分についてかが"
        "分かるように**箇条書きで書いてください。"
        "**本文は書き換えず、指摘だけ**を返してください。"
    ),
}


def build_prompt(task: Task, text: str) -> str | None:
    """ノートの本文から頼み事を組み立てる。空なら `None`。

    **front matter は渡さない。** 書く人の画面に見えていないものを
    渡すと、答えに `id:` の話が混ざる（ADR-0013 と同じ理由）。
    """
    body = frontmatter.split(text).body.strip()
    if not body:
        return None
    return f"{_COMMON}\n\n{_INSTRUCTIONS[task]}\n\n---\n{fit(body)}\n---"


def fit(body: str, *, limit: int = CHAR_LIMIT) -> str:
    """長すぎる本文を切る。**切ったことを伝える。**

    先頭を残す（見出しと書き出しに要点が寄る）。黙って切ると、答えが
    尻切れになった理由が読む側から分からない。
    """
    if len(body) <= limit:
        return body
    return body[:limit] + TRUNCATED


_QUESTION = (
    "あなたは日本語で答える調べ物の助手です。**次の抜粋だけを使って**質問に"
    "答えてください。抜粋に書かれていないことは推測せず、"
    "「ノートには書かれていません」と答えてください。"
    "どのノートに基づくかを本文中で題名で示してください。"
)


def build_question_prompt(question: str, sources: list[tuple[str, str]]) -> str | None:
    """vault 全体への質問（L-2）。材料は**呼ぶ側が選んで渡す**。

    **モデルに探させない。** 探す道具（索引）はこちらにあり、どのノートを
    見たかを画面に出せるのはこちら側だけ。出典を作文させない。
    """
    asked = question.strip()
    if not asked or not sources:
        return None
    excerpts = "\n\n".join(f"## {title}\n{body}" for title, body in sources)
    return f"{_QUESTION}\n\n---\n{excerpts}\n---\n\n質問: {asked}"


def pack(
    sources: list[tuple[str, str]], *, each: int = SOURCE_CHARS, most: int = SOURCE_LIMIT
) -> list[tuple[str, str]]:
    """渡す材料を抑える（L-2）。**本数も 1 本の長さも抑える。**"""
    return [(title, fit(body, limit=each)) for title, body in sources[:most]]


Transport = Callable[[str, dict | None, float], Iterable[bytes]]
"""`(url, payload, timeout)` → 行の並び。`payload` が `None` なら GET。"""


def _urlopen(url: str, payload: dict | None, timeout: float) -> Iterable[bytes]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        yield from response


@dataclass(slots=True)
class LocalLLM:
    """Ollama への口。**中身の判断はしない**（プロンプトは `build_prompt`）。"""

    model: str = DEFAULT_MODEL
    port: int = DEFAULT_PORT
    context: int = CONTEXT_TOKENS
    timeout: float = TIMEOUT_SECONDS
    """応答待ち時間（秒）。設定で変えられる（大きいモデルほど要る）。"""

    transport: Transport = field(default=_urlopen)

    def available(self) -> bool:
        """使える状態か。**押す前に分かる**ようにするための口（G-3 と同じ作法）。"""
        try:
            self._tags()
        except (NotRunning, TimedOut):
            return False
        return True

    def is_loaded(self) -> bool:
        """今そのモデルがメモリに載っているか（読み込み中かを知らせるため）。

        載っていなければ、最初の 1 行まで数分かかることがある。
        分からないとき（繋がらない・答えが読めない）は False。
        """
        try:
            found = self._ps()
        except (NotRunning, TimedOut):
            return False
        return any(str(entry.get("name", "")) == self.model for entry in found.get("models", []))

    def _ps(self) -> dict:
        for line in self._request("/api/ps", None, timeout=PROBE_TIMEOUT_SECONDS):
            found = _parse(line)
            if found is not None:
                return found
        return {}

    def models(self) -> list[str]:
        """入っているモデルの名前。動いていなければ空。"""
        try:
            found = self._tags()
        except (NotRunning, TimedOut):
            return []
        return [str(entry.get("name", "")) for entry in found.get("models", [])]

    def generate(
        self,
        prompt: str,
        *,
        images: Sequence[bytes] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> str:
        """答えを受け取る。**届いたぶんから知らせる。**

        最初の 1 文字まで数秒かかる（読み込みだけで実測 3.6 秒）ので、
        書き終わるのを待ってから出すと固まったように見える。

        `images` は画像の中身そのまま（Ollama へは base64 で渡す）。
        文字の読み取り（ADR-0027）がここを通る。**渡さなければ枠ごと
        載せない** — 空の `images` を付けると読み方が変わるモデルがある。
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {"num_ctx": self.context},
        }
        if images:
            payload["images"] = [base64.b64encode(image).decode("ascii") for image in images]
        parts: list[str] = []
        for line in self._request("/api/generate", payload):
            if should_stop is not None and should_stop():
                break
            found = _parse(line)
            if found is None:
                continue
            chunk = str(found.get("response", ""))
            if chunk:
                parts.append(chunk)
                if on_chunk is not None:
                    on_chunk(chunk)
            if found.get("done"):
                break
        return "".join(parts)

    # ------------------------------------------------------------------ 内部

    def _tags(self) -> dict:
        for line in self._request("/api/tags", None, timeout=PROBE_TIMEOUT_SECONDS):
            found = _parse(line)
            if found is not None:
                return found
        return {}

    def _request(
        self, path: str, payload: dict | None, *, timeout: float | None = None
    ) -> Iterable[bytes]:
        """行の並びを返す。繋がらなければ `NotRunning`。

        **1 行目を読むまで待つ。** `_urlopen` は生成器なので、呼んだだけでは
        中身が走らない。ここで `try` に包んでも空振りし、`URLError` が素の
        まま `available()` を突き抜けていた（起動時と `Cmd+,` から呼ぶので、
        Ollama を止めているだけでアプリが落ちた）。最初の 1 行を先に
        取り出して、繋がらないことをこの場で確かめる。
        """
        url = f"{endpoint(self.port)}{path}"
        timeout = self.timeout if timeout is None else timeout
        try:
            found = iter(self.transport(url, payload, timeout))
            first = next(found, None)
        except TimeoutError as error:
            # **時間切れは「繋がらない」ではない。** TimeoutError は
            # OSError の子なので、下の except より先に見る
            logger.info("Ollama が %s 秒で返さなかった: %s", timeout, error)
            raise TimedOut(str(error)) from error
        except (OSError, urllib.error.URLError) as error:
            logger.info("Ollama に繋がらない: %s", error)
            raise NotRunning(str(error)) from error
        return found if first is None else chain([first], found)


def _parse(line: bytes | str) -> dict | None:
    """1 行の JSON。**壊れた行で止めない**（残りが読めるなら読む）。"""
    try:
        found = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return found if isinstance(found, dict) else None
