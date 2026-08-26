"""テキスト変換コマンド（spec §5.4, §5.5-4, §5.5-5）。

`Cmd+B` などのトグル、リンク挿入、見出しレベルの増減、チェックボックス切替。

すべて**純関数**で、テキストと選択範囲から `Replacement` を返すだけ。
`QTextCursor` は呼び出し側が扱う。トグルは「既に囲まれていれば外す」という
分岐が本体なので、GUI 越しではなくここで網羅的に検査する。
"""

import re
from dataclasses import dataclass

from hitofude.core.models import MAX_HEADING_LEVEL, BlockInfo, BlockType
from hitofude.core.table import HEADER_PLACEHOLDER, new_table

# spec §5.5-4: 選択状態でこれらを押すと選択範囲を囲む
AUTO_PAIRS = {"*": "*", "`": "`", "[": "]", "(": ")", '"': '"'}

# ツールバーの「見出し」ボタンが回る深さ。H4〜H6 は `Cmd+Ctrl+↑↓` で届く
TOOLBAR_MAX_HEADING_LEVEL = 3

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


def insert_table(text: str, start: int, end: int, *, rows: int, columns: int) -> Replacement:
    """キャレットの位置に空の表を差し込む（ユーザー要望 2026-08-26）。

    `rows` は**見出しを除いた**本体の行数。表はブロックなので必ず行頭から
    始め、書きかけの行があればその下に置く（**選択していた文字は消さない**）。
    前後に空行を挟むのは、段落にくっついた `|` の行を GFM が表と認めない
    ため。後ろの空行は「表の続きから書ける場所」も兼ねる。
    """
    caret = max(start, end)  # 選択があっても消さない。その後ろへ置く
    head = text[:caret]
    lines = new_table(rows, columns)

    before = "" if not head or head.endswith("\n\n") else "\n" if head.endswith("\n") else "\n\n"
    body = before + "\n".join(lines) + "\n\n"
    # 最初の見出しを選んでおく。打てばそのまま置き換わる
    label = f"{HEADER_PLACEHOLDER}1"
    select_start = caret + len(before) + lines[0].index(label)
    return Replacement(caret, caret, body, select_start, select_start + len(label))


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


def cycle_heading(line: str) -> str:
    """段落 → H1 → H2 → H3 → 段落 と一周させる（B-1 のツールバー）。

    `shift_heading` は上げ下げの 2 方向で、ボタン 1 つには収まらない。
    押すたびに深くなるだけにすると **H6 で行き止まり**になって戻せない。

    H4〜H6 はツールバーからは出さない（`Cmd+Ctrl+↑↓` で届く）。手で打った
    H4 以下でここを押したときは段落へ戻す。行き止まりを作らないため。
    """
    heading = _HEADING_RE.match(line)
    current = len(heading.group("hashes")) if heading else 0
    body = line[heading.end() :] if heading else line

    level = current + 1 if current < TOOLBAR_MAX_HEADING_LEVEL else 0
    return f"{'#' * level} {body}" if level else body


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


# ------------------------------------------------------- 行単位のトグル（B-1）
#
# ツールバーのボタンは**複数行を選んで押す**のが普通なので、1 行を受ける
# `toggle_checkbox` とは別に、行の並びを受けて並びを返す形にする。
#
# 3 つに共通の約束（`TestLineTogglesShareRules` が固定している）:
#
# - **全部付いていれば外す。一部だけなら揃える。** 半端な状態で押したときに
#   外れると、揃えたかった側の意図と正反対になる
# - 行数を変えない。入力を書き換えない
# - 字下げは保つ

_INDENT_RE = re.compile(r"^[ \t]*")
_ORDERED_RE = re.compile(r"^(?P<indent>[ \t]*)\d{1,9}[.)][ \t]+")
_UNORDERED_RE = re.compile(r"^(?P<indent>[ \t]*)[-*+][ \t]+")
_QUOTE_RE = re.compile(r"^> ?")


def toggle_bullet(lines: list[str]) -> list[str]:
    """箇条書きにする / 外す。番号付きからは乗り換える。"""
    return _toggle_list(lines, numbered=False)


def toggle_ordered(lines: list[str]) -> list[str]:
    """番号付きにする / 外す。番号は 1 から振り直す。"""
    return _toggle_list(lines, numbered=True)


def _toggle_list(lines: list[str], *, numbered: bool) -> list[str]:
    """リスト記号の付け外し。

    **空行は触らない。** `- ` だけの行が増えても書き手の役に立たない。
    ただし空行しか無いとき（何も書いていない行で押したとき）は付ける。
    「これから書く」という意思なので、そこで何も起きないほうが困る。
    """
    wanted = _ORDERED_RE if numbered else _UNORDERED_RE
    targets = [index for index, line in enumerate(lines) if line.strip()] or list(range(len(lines)))
    removing = all(wanted.match(lines[index]) for index in targets)

    result = list(lines)
    number = 0
    for index in targets:
        line = lines[index]
        # 付けるときは、今の記号（`- ` でも `1. ` でも）を落としてから付け直す。
        # 落とさないと `- 1. りんご` のような入れ子ができる
        stripped, indent = _without_list_marker(line)
        if removing:
            result[index] = stripped
            continue
        number += 1
        marker = f"{number}. " if numbered else "- "
        result[index] = f"{indent}{marker}{stripped.lstrip()}"
    return result


def _without_list_marker(line: str) -> tuple[str, str]:
    """リスト記号を外した行と、その行の字下げ。

    チェックボックスは記号の一部として扱わない。`- [ ] 買う` から `- ` だけ
    外すと `[ ] 買う` が残る。**残す**のが正しい。チェックを消したいなら
    チェックボックスのトグルで消せる。
    """
    indent = _INDENT_RE.match(line).group()
    for pattern in (_ORDERED_RE, _UNORDERED_RE):
        found = pattern.match(line)
        if found is not None:
            return line[found.end() :], indent
    return line[len(indent) :], indent


def toggle_quote(lines: list[str]) -> list[str]:
    """引用にする / 外す。

    **空行も引用にする。** 引用の中の空行が引用から抜けると、そこで引用が
    途切れて別々の引用になる。リストが空行を飛ばすのとは逆だが、Markdown の
    仕様がそうなっている以上こちらが正しい。

    ただし**付いているかの判定には空行を入れない。** 入れると、空行を挟んだ
    引用を選んで押したときに「付いていない」と見なされ、外したいのに一段
    深くなる。

    **このボタンでは入れ子を作れない**（全部引用なら外れる）。3 つのボタンで
    手応えを揃えるほうを採った。深くしたいときは `>` を打てばよい。
    """
    targets = [line for line in lines if line.strip()] or lines
    if all(_QUOTE_RE.match(line) for line in targets):
        return [_QUOTE_RE.sub("", line, count=1) for line in lines]
    # 既に引用の行はそのまま。押すたびに深くなると、揃えたかった意図と食い違う
    return [line if _QUOTE_RE.match(line) else f"> {line}" if line else "> " for line in lines]
