"""受け取り途中で切れたときの扱い（レビュー指摘 2026-08-29）。

`_request` が包んでいるのは**1 行目だけ**。2 行目以降で相手が落ちたり
接続が切れたりすると、素の `OSError` がそのまま上がっていた。

**届いたぶんは捨てない。** 断片は既に画面へ流している（`on_chunk`）ので、
そこで例外にすると「出ていた字が消えて失敗だけ残る」ことになる。
"""

import pytest

from hitofude.core.llm import LocalLLM


def stream(*lines, error=None):
    """途中で切れる相手。"""

    def transport(url, payload, timeout):
        yield from lines
        if error is not None:
            raise error

    return transport


class TestBrokenStream:
    def test_途中で切れても例外にしない(self) -> None:
        llm = LocalLLM(transport=stream('{"response":"こんに"}'.encode(), error=OSError("切れた")))
        assert llm.generate("問い") == "こんに"

    def test_届いたぶんを返す(self) -> None:
        llm = LocalLLM(
            transport=stream(
                '{"response":"あ"}'.encode(),
                '{"response":"い"}'.encode(),
                error=ConnectionResetError("切れた"),
            )
        )
        assert llm.generate("問い") == "あい"

    def test_流したぶんはそのまま(self) -> None:
        """**画面に出た字を消さない。**"""
        got: list[str] = []
        llm = LocalLLM(transport=stream('{"response":"あ"}'.encode(), error=OSError("切れた")))
        llm.generate("問い", on_chunk=got.append)
        assert got == ["あ"]

    def test_最初から繋がらないのは今までどおり(self) -> None:
        """**直しすぎない。** 1 行目で落ちるのは「動いていない」。"""
        from hitofude.core.llm import NotRunning

        def dead(url, payload, timeout):
            raise OSError("繋がらない")
            yield  # pragma: no cover

        with pytest.raises(NotRunning):
            LocalLLM(transport=dead).generate("問い")
