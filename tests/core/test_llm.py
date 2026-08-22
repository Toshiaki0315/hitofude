"""ローカルLLM に読ませる（L-1 / ADR-0025）。

**ここは Qt もネットワークも知らないままテストできる**（R3）。通信の口は
差し替えられるようにしてあり、テストでモデルを動かさない。

外へ出さないことがこの機能の前提なので、**送り先が `127.0.0.1` に
固定されていること**もここで固定する。
"""

import json

import pytest

from hitofude.core import llm

NOTE = """---
id: 01M0
created: 2026-08-22T10:00:00+09:00
---
# 会議メモ

来週の予算について話した。
"""


def responses(*chunks: str, done_extra: dict | None = None) -> list[bytes]:
    """Ollama が返す ndjson の行を作る。"""
    lines = [json.dumps({"response": chunk, "done": False}).encode() for chunk in chunks]
    tail = {"response": "", "done": True}
    tail.update(done_extra or {})
    lines.append(json.dumps(tail).encode())
    return lines


class FakeTransport:
    """繋がったことにする。送った中身を覚えておく。"""

    def __init__(self, lines: list[bytes] | None = None, tags: dict | None = None) -> None:
        self.lines = lines or []
        self.tags = tags if tags is not None else {"models": [{"name": "gemma3:4b"}]}
        self.urls: list[str] = []
        self.payloads: list[dict] = []

    def __call__(self, url: str, payload: dict | None, timeout: float):
        self.urls.append(url)
        if payload is not None:
            self.payloads.append(payload)
        if payload is None:
            return [json.dumps(self.tags).encode()]
        return self.lines


class Unreachable:
    """Ollama が動いていない。"""

    def __call__(self, url: str, payload: dict | None, timeout: float):
        raise OSError("Connection refused")


class TestPrompt:
    def test_本文が入る(self) -> None:
        found = llm.build_prompt(llm.Task.SUMMARY, NOTE)
        assert "来週の予算について話した。" in found

    def test_front_matterは入れない(self) -> None:
        """**書く人に見えていないものを渡さない**（ADR-0013 と同じ理由）。"""
        found = llm.build_prompt(llm.Task.SUMMARY, NOTE)
        assert "01M0" not in found
        assert "created:" not in found

    def test_要約とレビューで指示が違う(self) -> None:
        summary = llm.build_prompt(llm.Task.SUMMARY, NOTE)
        review = llm.build_prompt(llm.Task.REVIEW, NOTE)
        assert summary != review

    def test_渡した本文だけを見るよう言う(self) -> None:
        """**知らないことを足させない。** 出典の無い話が混ざると使えない。"""
        found = llm.build_prompt(llm.Task.SUMMARY, NOTE)
        assert "以外" in found or "だけ" in found

    def test_日本語で答えさせる(self) -> None:
        assert "日本語" in llm.build_prompt(llm.Task.SUMMARY, NOTE)

    def test_空の本文は組み立てない(self) -> None:
        assert llm.build_prompt(llm.Task.SUMMARY, "   \n") is None


class TestFit:
    """長いノートは切る。**黙って切らない。**"""

    def test_短ければそのまま(self) -> None:
        assert llm.fit("短い本文", limit=100) == "短い本文"

    def test_長ければ切る(self) -> None:
        found = llm.fit("あ" * 500, limit=100)
        assert len(found) < 500

    def test_切ったことを伝える(self) -> None:
        """切ったと分かれば、答えが尻切れでも理由が読める。"""
        assert llm.TRUNCATED in llm.fit("あ" * 500, limit=100)

    def test_先頭を残す(self) -> None:
        """見出しと書き出しに要点が寄る（アウトラインと同じ考え方）。"""
        assert llm.fit("# 題\n" + "あ" * 500, limit=100).startswith("# 題")


class TestGenerate:
    def test_流れてきたぶんを繋ぐ(self) -> None:
        transport = FakeTransport(responses("会議の", "要約"))
        client = llm.LocalLLM(transport=transport)
        assert client.generate("prompt") == "会議の要約"

    def test_届くたびに知らせる(self) -> None:
        """**最初の 1 文字まで数秒かかる。** 黙って待たせない。"""
        transport = FakeTransport(responses("会議の", "要約"))
        client = llm.LocalLLM(transport=transport)
        seen: list[str] = []
        client.generate("prompt", on_chunk=seen.append)
        assert seen == ["会議の", "要約"]

    def test_途中でやめられる(self) -> None:
        """押した人が待つのをやめたら、そこで止める。"""
        transport = FakeTransport(responses("一", "二", "三"))
        client = llm.LocalLLM(transport=transport)
        found = client.generate("prompt", should_stop=lambda: True)
        assert found == ""

    def test_壊れた行は飛ばす(self) -> None:
        transport = FakeTransport(["{壊れている".encode(), *responses("答え")])
        client = llm.LocalLLM(transport=transport)
        assert client.generate("prompt") == "答え"

    def test_繋がらなければ知らせる(self) -> None:
        client = llm.LocalLLM(transport=Unreachable())
        with pytest.raises(llm.NotRunning):
            client.generate("prompt")


class TestRequest:
    def test_送り先は127001に固定(self) -> None:
        """**外へ出さないことがこの機能の前提**（ADR-0025）。"""
        transport = FakeTransport(responses("答え"))
        llm.LocalLLM(transport=transport).generate("prompt")
        assert transport.urls[0].startswith("http://127.0.0.1:11434/")

    def test_モデルと文脈長を渡す(self) -> None:
        transport = FakeTransport(responses("答え"))
        llm.LocalLLM(model="gemma3:12b", transport=transport).generate("prompt")
        payload = transport.payloads[0]
        assert payload["model"] == "gemma3:12b"
        assert payload["options"]["num_ctx"] == llm.CONTEXT_TOKENS

    def test_流しながら受け取る(self) -> None:
        """`stream: False` だと**書き終わるまで何も出ない**（実測 12.8 秒）。"""
        transport = FakeTransport(responses("答え"))
        llm.LocalLLM(transport=transport).generate("prompt")
        assert transport.payloads[0]["stream"] is True


class TestAvailability:
    def test_動いていれば使える(self) -> None:
        client = llm.LocalLLM(transport=FakeTransport())
        assert client.available() is True

    def test_動いていなければ使えない(self) -> None:
        """**押してから断らない**（G-3 と同じ作法）。先に分かる口を持つ。"""
        client = llm.LocalLLM(transport=Unreachable())
        assert client.available() is False

    def test_入っているモデルが分かる(self) -> None:
        transport = FakeTransport(tags={"models": [{"name": "gemma3:4b"}, {"name": "qwen3:8b"}]})
        client = llm.LocalLLM(transport=transport)
        assert client.models() == ["gemma3:4b", "qwen3:8b"]

    def test_動いていなければ空(self) -> None:
        assert llm.LocalLLM(transport=Unreachable()).models() == []


SOURCES = [("会議メモ", "来週の予算を話した。"), ("買い物", "牛乳とパン。")]


class TestQuestionPrompt:
    """vault 全体への質問（L-2）。

    **答えの材料はこちらが選んで渡す。** モデルに探させない（探せない）。
    渡した抜粋だけで答えさせ、**足りなければ「書かれていない」と言わせる**。
    """

    def test_質問が入る(self) -> None:
        found = llm.build_question_prompt("予算はどうなった？", SOURCES)
        assert "予算はどうなった？" in found

    def test_抜粋が題名付きで入る(self) -> None:
        found = llm.build_question_prompt("予算は？", SOURCES)
        assert "会議メモ" in found
        assert "来週の予算を話した。" in found

    def test_渡したものだけで答えさせる(self) -> None:
        found = llm.build_question_prompt("予算は？", SOURCES)
        assert "以外" in found or "だけ" in found

    def test_無ければ無いと言わせる(self) -> None:
        """**作り話をさせない。** 出典の無い答えは使えない。"""
        found = llm.build_question_prompt("予算は？", SOURCES)
        assert "書かれていません" in found

    def test_材料が無ければ組み立てない(self) -> None:
        assert llm.build_question_prompt("予算は？", []) is None

    def test_質問が空なら組み立てない(self) -> None:
        assert llm.build_question_prompt("   ", SOURCES) is None


class TestPack:
    """渡す量を抑える（L-2）。**文脈からあふれると黙って切れる。**"""

    def test_短ければそのまま(self) -> None:
        found = llm.pack([("題", "本文")], each=100)
        assert found == [("題", "本文")]

    def test_1本ずつ切る(self) -> None:
        found = llm.pack([("題", "あ" * 500)], each=100)
        assert len(found[0][1]) < 500

    def test_切ったと伝える(self) -> None:
        found = llm.pack([("題", "あ" * 500)], each=100)
        assert llm.TRUNCATED in found[0][1]

    def test_本数も抑える(self) -> None:
        found = llm.pack([(f"題{n}", "本文") for n in range(20)], each=100, most=5)
        assert len(found) == 5
