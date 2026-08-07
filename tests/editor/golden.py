"""ハイライト結果のスナップショットを組み立てる（spec §10 のゴールデンテスト）。

書式そのものを比較すると差分が読めないので、**人が読める記述子**に落とす。
テストが落ちたとき、どの行のどの範囲がどう変わったのかが diff で分かる。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCharFormat, QTextDocument

from hitofude.editor.highlighter import HIDDEN_POINT_SIZE, MarkdownHighlighter

BASE_POINT_SIZE = 15.0
MONO_FAMILY = "TestMono"  # 実行環境のフォント事情に左右されないよう固定する


def describe(fmt: QTextCharFormat) -> str:
    """1 つの書式を短い記述子にする。"""
    tokens: list[str] = []
    size = fmt.fontPointSize()
    if size == HIDDEN_POINT_SIZE:
        # 実際の値も残す。`hidden` とだけ書くと、記述子が
        # HIDDEN_POINT_SIZE を参照している以上、定数を変えても比較の
        # 両側が同時に動いてしまい回帰を素通りさせる（実際に踏んだ）。
        tokens.append(f"hidden:{size:g}")
    elif size:
        tokens.append(f"size:{size:g}")
    if fmt.fontWeight() >= QFont.Weight.Bold:
        tokens.append("bold")
    if fmt.fontItalic():
        tokens.append("italic")
    if fmt.fontStrikeOut():
        tokens.append("strike")
    if fmt.underlineStyle() != QTextCharFormat.UnderlineStyle.NoUnderline:
        tokens.append("underline")
    if fmt.fontFamilies():
        tokens.append("mono")
    # 未設定のブラシは「黒・不透明」を返す。alpha で判定すると全ての範囲に
    # 色が付いているように見えてしまうので、ブラシの種類で判定する。
    if fmt.background().style() != Qt.BrushStyle.NoBrush:
        tokens.append(f"bg:{fmt.background().color().name()}")
    if fmt.foreground().style() != Qt.BrushStyle.NoBrush:
        tokens.append(f"fg:{fmt.foreground().color().name()}")
    return "+".join(tokens) or "plain"


def snapshot(text: str) -> list[dict]:
    """テキスト全体をハイライトし、行ごとの書式範囲を返す。"""
    document = QTextDocument()
    highlighter = MarkdownHighlighter(
        document, base_point_size=BASE_POINT_SIZE, mono_family=MONO_FAMILY
    )
    document.setPlainText(text)
    document.documentLayout().documentSize()

    result: list[dict] = []
    for number in range(document.blockCount()):
        block = document.findBlockByNumber(number)
        data = block.userData()
        ranges = [
            [entry.start, entry.length, describe(entry.format)]
            for entry in block.layout().formats()
        ]
        if not ranges and data is None:
            continue
        result.append(
            {
                "line": number,
                "text": block.text(),
                "block": data.info.type.name if data else None,
                "ranges": ranges,
            }
        )
    del highlighter
    return result


def golden_path(fixtures_dir: Path, name: str) -> Path:
    return fixtures_dir / "golden" / f"{name}.json"
