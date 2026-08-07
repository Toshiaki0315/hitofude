"""テキスト変換コマンド（spec §5.4, §5.5-4, §5.5-5）。

`Cmd+B` などのトグル、リンク挿入、見出しレベルの増減、チェックボックス切替。

すべて**純関数**で、テキストと選択範囲から `Replacement` を返すだけ。
`QTextCursor` は呼び出し側が扱う。トグルは「既に囲まれていれば外す」という
分岐が本体なので、GUI 越しではなくここで網羅的に検査する。
"""

import re
from dataclasses import dataclass

from hitofude.core.models import MAX_HEADING_LEVEL, BlockInfo, BlockType

# spec §5.5-4: 選択状態でこれらを押すと選択範囲を囲む
AUTO_PAIRS = {"*": "*", "`": "`", "[": "]", "(": ")", '"': '"'}

_URL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9+.\-]*://\S+\s*$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+")
_TASK_RE = re.compile(r"^(?P<prefix>[ \t]*[-*+][ \t]+)\[(?P<state>[ xX])\][ \t]+")
_BULLET_RE = re.compile(r"^(?P<prefix>[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)")


@dataclass(frozen=True, slots=True)
class Replacement:
    """`[start, end)` を `text` で置き換え、そのあと `[select_start, select_end)` を選ぶ。"""

    start: int
    end: int
    text: str
    select_start: int
    select_end: int


def is_url(text: str) -> bool:
    """クリップボードの中身が URL とみなせるか（spec §5.5-5）。"""
    return bool(_URL_RE.match(text))


def toggle_wrap(text: str, start: int, end: int, marker: str) -> Replacement:
    """選択範囲を `marker` で囲む。既に囲まれていれば外す（spec §5.4）。

    「外す」を実装しないと、間違えて押したときに戻す手段が
    `Cmd+Z` しかなくなる。仕様書が「必ず実装」としている理由。
    """
    width = len(marker)

    if start == end:
        # 選択が無いときは記号だけ置いて、間にキャレットを入れる
        return Replacement(start, start, marker * 2, start + width, start + width)

    selected = text[start:end]

    # マーカーが選択の外側にある（`**強調**` の `強調` だけを選んだ状態）
    if text[max(0, start - width) : start] == marker and text[end : end + width] == marker:
        return Replacement(start - width, end + width, selected, start - width, end - width)

    # マーカーが選択の内側にある（`**強調**` ごと選んだ状態）
    if len(selected) >= width * 2 and selected.startswith(marker) and selected.endswith(marker):
        inner = selected[width:-width]
        return Replacement(start, end, inner, start, start + len(inner))

    return Replacement(start, end, f"{marker}{selected}{marker}", start + width, end + width)


def insert_link(text: str, start: int, end: int, url: str = "") -> Replacement:
    """選択文字を `[選択](url)` にする（spec §5.4 の `Cmd+K`）。

    URL が空なら `()` の中にキャレットを置く。URL があればリンク全体の後ろへ。
    """
    label = text[start:end]
    body = f"[{label}]({url})"
    # URL が無いときは `[label](` の直後、あるときはリンク全体の後ろ
    caret = start + (len(body) if url else len(label) + 3)
    return Replacement(start, end, body, caret, caret)


def shift_heading(line: str, delta: int) -> str | None:
    """見出しレベルを増減する（spec §5.4 の `Cmd+Ctrl+↑/↓`）。

    `delta` が負なら `#` が減って見出しが**大きく**なる。段落は `delta > 0` で
    見出しになり、H1 でさらに上げると段落へ戻る。変化しないときは None。
    """
    heading = _HEADING_RE.match(line)
    current = len(heading.group("hashes")) if heading else 0
    body = line[heading.end() :] if heading else line

    level = current + delta
    if level == current or level < 0 or level > MAX_HEADING_LEVEL:
        return None
    if level == 0:
        return body
    return f"{'#' * level} {body}"


def toggle_checkbox(line: str, info: BlockInfo | None) -> str | None:
    """チェックボックスを切り替える（spec §5.4 の `Cmd+Shift+T`）。

    - タスク項目なら `[ ]` と `[x]` を往復する
    - ただのリスト項目ならチェックボックスを付ける
    - それ以外の行はリスト項目に変えたうえで付ける
    """
    task = _TASK_RE.match(line)
    if task is not None:
        state = "x" if task.group("state") == " " else " "
        return f"{task.group('prefix')}[{state}] {line[task.end() :]}"

    bullet = _BULLET_RE.match(line)
    if bullet is not None:
        return f"{bullet.group('prefix')}[ ] {line[bullet.end() :]}"

    if info is not None and info.type in (BlockType.HEADING, BlockType.CODE_FENCE_BODY):
        return None  # 見出しやコードをタスクにするのは事故でしかない
    return f"- [ ] {line}"
