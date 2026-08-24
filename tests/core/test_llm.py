"""ローカルLLM に読ませる（L-1 / ADR-0025）。

**ここは Qt もネットワークも知らないままテストできる**（R3）。通信の口は
差し替えられるようにしてあり、テストでモデルを動かさない。

外へ出さないことがこの機能の前提なので、**送り先が `127.0.0.1` に
固定されていること**もここで固定する。
"""

import base64
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


class TestImages:
    """画像を渡す（ADR-0027 の 3。読み取りをここ経由でやる）。"""

    def test_base64_にして載せる(self) -> None:
        transport = FakeTransport(responses("会議メモ"))
        found = llm.LocalLLM(transport=transport)
        assert found.generate("読んで", images=[b"\x89PNG\r\n"]) == "会議メモ"
        assert transport.payloads[0]["images"] == [base64.b64encode(b"\x89PNG\r\n").decode()]

    def test_複数枚も順に載せる(self) -> None:
        transport = FakeTransport(responses("あ"))
        llm.LocalLLM(transport=transport).generate("読んで", images=[b"one", b"two"])
        assert transport.payloads[0]["images"] == [
            base64.b64encode(b"one").decode(),
            base64.b64encode(b"two").decode(),
        ]

    def test_渡さなければ載せない(self) -> None:
        """**文章だけの頼み事に空の枠を足さない**（モデルによっては読み方が変わる）。"""
        transport = FakeTransport(responses("要点"))
        llm.LocalLLM(transport=transport).generate("まとめて")
        assert "images" not in transport.payloads[0]

    def test_空の並びも載せない(self) -> None:
        transport = FakeTransport(responses("要点"))
        llm.LocalLLM(transport=transport).generate("まとめて", images=[])
        assert "images" not in transport.payloads[0]


class TestLazyTransportFailure:
    """**繋がらないことを、繋ぎに行った人が受け取る**（回帰）。

    `_urlopen` はジェネレータなので、呼んだだけでは中身が走らない。
    `_request` の try が空振りし、URLError が素のまま
    `available()` / `models()` / `generate()` を突き抜けていた。
    起動時（`_restore_layout`）や `Cmd+,` から呼ばれるため、
    Ollama を止めているだけでアプリが落ちた。
    """

    def lazy_client(self):
        """本物と同じ「呼んでも走らない」形の口（生成器）。"""

        def transport(url, payload, timeout):
            raise OSError(61, "Connection refused")
            yield b""  # ここに来ないが、生成器にするために要る

        return llm.LocalLLM(transport=transport)

    def test_availableは偽を返す(self) -> None:
        assert self.lazy_client().available() is False

    def test_modelsは空を返す(self) -> None:
        assert self.lazy_client().models() == []

    def test_generateはNotRunningになる(self) -> None:
        with pytest.raises(llm.NotRunning):
            list(self.lazy_client().generate("こんにちは"))


class TestProbeTimeout:
    """**居るかどうかの確認は待たない**（回帰）。

    `available()` / `models()` は起動時・`Cmd+,`・`Cmd+6` から GUI
    スレッドで呼ばれる。生成と同じ 120 秒を待つと、繋がらない相手
    （docs/ollama.md の SSH トンネルが半分開いている等）で窓が 2 分固まる。
    """

    def timeouts(self, call) -> list[float]:
        seen: list[float] = []

        def transport(url, payload, timeout):
            seen.append(timeout)
            yield b'{"models": []}'

        call(llm.LocalLLM(transport=transport))
        return seen

    def test_確認は短く待つ(self) -> None:
        assert self.timeouts(lambda client: client.available()) == [llm.PROBE_TIMEOUT_SECONDS]
        assert llm.PROBE_TIMEOUT_SECONDS < llm.TIMEOUT_SECONDS

    def test_一覧も短く待つ(self) -> None:
        assert self.timeouts(lambda client: client.models()) == [llm.PROBE_TIMEOUT_SECONDS]

    def test_生成は今まで通り待つ(self) -> None:
        """長いノートを読ませるので、こちらは短くしない。"""
        seen = self.timeouts(lambda client: list(client.generate("こんにちは")))
        assert seen == [llm.TIMEOUT_SECONDS]


class TestTimedOut:
    """**時間切れと「繋がらない」を分ける**（ユーザー報告 2026-08-24）。

    大きいモデルは読み込みだけで数分かかる（実測: gemma4:26b で最初の
    1 行まで 391.9 秒）。待ちきれずに切ったのを「Ollama に繋がりません
    でした。動いているか確かめてください」と出すと、動いているのに
    動いていないと言われて原因に辿り着けない。
    """

    def timing_out(self, seconds: float = 600.0):
        def transport(url, payload, timeout):
            raise TimeoutError("timed out")
            yield b""  # 生成器にするために要る（本物と同じ形）

        return llm.LocalLLM(transport=transport, timeout=seconds)

    def test_時間切れは別の例外(self) -> None:
        with pytest.raises(llm.TimedOut):
            list(self.timing_out().generate("こんにちは"))

    def test_時間切れは繋がらないとは別物(self) -> None:
        """どちらも RuntimeError だが、混ぜると案内が嘘になる。"""
        assert not issubclass(llm.TimedOut, llm.NotRunning)
        assert not issubclass(llm.NotRunning, llm.TimedOut)

    def test_待ち時間を渡せる(self) -> None:
        seen: list[float] = []

        def transport(url, payload, timeout):
            seen.append(timeout)
            yield json.dumps({"response": "はい", "done": True}).encode("utf-8")

        llm.LocalLLM(transport=transport, timeout=900.0).generate("こんにちは")
        assert seen == [900.0]

    def test_確認の待ちは延ばさない(self) -> None:
        """居るかどうかの確認は即答が返る。生成の待ちに引きずられない。"""
        seen: list[float] = []

        def transport(url, payload, timeout):
            seen.append(timeout)
            yield b'{"models": []}'

        llm.LocalLLM(transport=transport, timeout=900.0).available()
        assert seen == [llm.PROBE_TIMEOUT_SECONDS]


class TestLoadedModels:
    """読み込み済みかを見る（「読み込んでいます…」と出すため）。"""

    def client(self, payload: bytes):
        def transport(url, payload_in, timeout):
            assert url.endswith("/api/ps"), url
            yield payload

        return llm.LocalLLM(model="gemma4:26b", transport=transport)

    def test_載っていれば真(self) -> None:
        assert self.client(b'{"models": [{"name": "gemma4:26b"}]}').is_loaded() is True

    def test_載っていなければ偽(self) -> None:
        assert self.client(b'{"models": [{"name": "gemma3:12b"}]}').is_loaded() is False

    def test_繋がらなければ偽(self) -> None:
        def transport(url, payload, timeout):
            raise OSError(61, "Connection refused")
            yield b""

        assert llm.LocalLLM(transport=transport).is_loaded() is False


class TestKeepAlive:
    """答えたあとモデルを残す長さ（ユーザー報告 2026-08-24）。

    指定しないと Ollama の既定（5 分）で、12b でも `llama-server` が
    8.0GB を抱え続ける（実測）。**送る payload で決める。**
    """

    def test_保持時間を渡す(self) -> None:
        transport = FakeTransport(responses("はい"))
        llm.LocalLLM(transport=transport, keep_alive=5).generate("読んで")
        assert transport.payloads[0]["keep_alive"] == "5m"

    def test_ゼロなら答えたらすぐ降ろす(self) -> None:
        transport = FakeTransport(responses("はい"))
        llm.LocalLLM(transport=transport, keep_alive=0).generate("読んで")
        assert transport.payloads[0]["keep_alive"] == 0

    def test_選べる長さは4つ(self) -> None:
        assert llm.KEEP_ALIVE_CHOICES == (0, 1, 5, 30)


class TestUnload:
    """手で降ろす（ユーザー要望 2026-08-24）。"""

    def test_降ろす要求を送る(self) -> None:
        transport = FakeTransport(responses(""))
        assert llm.LocalLLM(transport=transport, model="gemma3:12b").unload() is True
        assert transport.payloads[0] == {"model": "gemma3:12b", "keep_alive": 0}

    def test_本文は送らない(self) -> None:
        """**答えを作らせない。** 中身の無い生成が「降ろす」の合図。"""
        transport = FakeTransport(responses(""))
        llm.LocalLLM(transport=transport).unload()
        assert "prompt" not in transport.payloads[0]

    def test_繋がらなければFalse(self) -> None:
        """降ろす操作で例外を上げても打つ手が無い。"""
        assert llm.LocalLLM(transport=Unreachable()).unload() is False
