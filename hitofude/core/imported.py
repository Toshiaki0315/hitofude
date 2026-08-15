"""取り込んだ文字を Markdown に整える（F-1）。

PowerPoint（F-3）と PDF（F-2）の両方がここを通る。**ざっくり整えて手で
直す**前提で、元の見た目の再現は狙わない。

判断の物差しは「**間違えたときにどちらが困るか**」で揃えてある。
消しすぎると本文が減って気づけないので、迷ったら残す。見出しの推定も
外れることがあるが、`##` が余分に付くのは目で見て直せる。

`core/` にあるので PySide6 に依存しない（R3）。
"""

import re
import unicodedata

# 見出しらしさの上限。これより長い行は、句点が無くても本文として扱う
MAX_HEADING_LENGTH = 30

# 折り返しの続きと見なす行の長さ（そのページでいちばん長い行に対する割合）。
# **PDF には空行が無い。** 段落の切れ目は「行が短いこと」でしか分からないので、
# ページの中で相対的に見る。これを入れないと 1 ページが 1 段落に潰れる（実測）
CONTINUATION_RATIO = 0.6

# 箇条書きに見える行頭記号。PDF も PowerPoint もこの手の記号で出てくる
BULLETS = "・•‣▪▫◦·※●○◆◇■□▶▸-–—*"

# ページ番号らしい行。**行まるごとが番号のときだけ**落とす。
# `2026`（年）や `12345` を消さないよう 3 桁までに絞る
_PAGE_NUMBER_RE = re.compile(
    r"""\A\s*(?:
        [-–—]\s*\d{1,3}\s*[-–—]      # - 3 -
      | \d{1,3}\s*/\s*\d{1,3}        # 3 / 12
      | [Pp]\.?\s*\d{1,3}            # P. 5
      | \d{1,3}\s*(?:ページ|頁)      # 6 ページ
      | \d{1,3}
    )\s*\Z""",
    re.VERBOSE,
)

# 落とす制御文字。PDF には改ページ（\x0c）や NUL が混ざる。
# 欧文 PDF の行末には soft hyphen が入り、残すと単語が割れる
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f­​﻿]")
_SPACES_RE = re.compile(r"[ \t]+")
_BULLET_RE = re.compile(rf"\A[{re.escape(BULLETS)}]\s*(?P<body>.*)\Z")
# 文の終わりに見える記号。見出しの判定に使う
_SENTENCE_END = "。．.！？!?、，,：:；;"
# 句点が無くても文だと分かる語尾。**日本語の見出しは体言止めが多い**ので、
# ここが効く（「本日の議題は予算です」を見出しにしない）
_SENTENCE_TAIL_RE = re.compile(r"(です|ます|でした|ました|だった|である|ください|なります)\Z")
# 行を詰めて繋いでよい文字（和文）。欧文は空白で繋ぐ
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿ａ-ｚＡ-Ｚ０-９、。「」（）]")


def normalize_text(text: str) -> str:
    """取り込んだ文字を揃える。

    **NFKC は飾りではない。** 自分で書き出した PDF を読み戻すと
    `本⽇`（U+2F47 KANGXI RADICAL SUN）が出てきて、**「本日」では検索に
    掛からない**（実測）。取り込んだ瞬間に揃えないと、あとから気づけない。

    行頭の空白も落とす。**4 つ以上あるとコードブロックになる**ので、
    元の字下げをそのまま持ち込むと本文が化ける。
    """
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = _CONTROL_RE.sub("", cleaned)
    lines = [_SPACES_RE.sub(" ", line).strip() for line in cleaned.split("\n")]
    return "\n".join(lines)


def is_page_number(line: str) -> bool:
    """その行がページ番号だけか。

    **迷ったら残す。** 消しすぎると本文が減り、読み手は減ったことに
    気づけない。`2026`（年）や `1. はじめに` は残す。
    """
    return bool(line.strip()) and _PAGE_NUMBER_RE.match(line) is not None


def looks_like_heading(line: str) -> bool:
    """その行が見出しらしいか。

    短くて、文の終わりの記号が無く、箇条書きでもないもの。**外れることが
    ある**が、`##` が余分に付くのは目で見て直せる（本文が消えるのと違う）。
    """
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_LENGTH:
        return False
    if _BULLET_RE.match(stripped) or is_page_number(stripped):
        return False
    if _SENTENCE_TAIL_RE.search(stripped):
        return False
    return stripped[-1] not in _SENTENCE_END


def to_markdown(pages: list[str], *, title: str = "") -> str:
    """ページごとの文字を 1 つの Markdown にする。

    **ページの頭が見出しらしければ `##` にする。** 講演の資料は 1 ページ
    = 1 枚のスライドで、その先頭行が題であることが多い。PowerPoint の
    取り込み（F-3）も同じ `##` 区切りにしてある。
    """
    parts: list[str] = [f"# {title}"] if title.strip() else []

    for page in pages:
        blocks = _page_blocks(normalize_text(page))
        parts.extend(blocks)

    body = "\n\n".join(parts)
    return f"{body}\n" if body else ""


def _page_blocks(page: str) -> list[str]:
    """1 ページぶんを、段落・箇条書き・見出しの並びにする。

    **行が続いているかは「長さ」で見る。** PDF は幅で折り返すので、
    途中の行はページの端まで伸び、段落の最後の行だけが短くなる。空行が
    無いぶん、これが唯一の手がかりになる。
    """
    lines = page.split("\n")
    limit = max((len(line) for line in lines if line), default=0) * CONTINUATION_RATIO
    blocks: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    heading_taken = False

    def flush() -> None:
        if paragraph:
            blocks.append(_join(paragraph))
            paragraph.clear()
        if bullets:
            blocks.append("\n".join(bullets))
            bullets.clear()

    for line in lines:
        if not line or is_page_number(line):
            flush()
            continue

        bullet = _BULLET_RE.match(line)
        if bullet is not None:
            if paragraph:
                flush()
            body = bullet.group("body").strip()
            if body:
                bullets.append(f"- {body}")
            continue

        if bullets:
            flush()

        if not heading_taken and not blocks and not paragraph and looks_like_heading(line):
            blocks.append(f"## {line}")
            heading_taken = True
            continue

        # 前の行が短い、または文として終わっていれば、そこで段落が切れている
        if paragraph and not _continues(paragraph[-1], limit):
            flush()
        paragraph.append(line)

    flush()
    return blocks


def _continues(line: str, limit: float) -> bool:
    """その行のあとに文章が続いているか。

    ページの端まで伸びていて、文の終わりの記号で終わっていないなら、
    次の行は折り返しの続き。**短い行は段落の終わり**（あるいは箇条書きや
    小見出しのような独立した 1 行）と見なす。
    """
    return len(line) >= limit and line[-1] not in _SENTENCE_END


def _join(lines: list[str]) -> str:
    """折り返された行を 1 つの段落に戻す。

    **和文は詰めて繋ぐ。** PDF は行ごとに切れて出るので、空白を挟むと
    文の途中に隙間ができる。欧文は単語が続くので空白で繋ぐ。
    """
    joined = lines[0]
    for line in lines[1:]:
        tail = joined[-1] if joined else ""
        separator = "" if _CJK_RE.match(tail) and _CJK_RE.match(line[0]) else " "
        joined += separator + line
    return joined
