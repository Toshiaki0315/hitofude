"""保管フォルダの外を指す参照を弾く規則。

同じ判定が `config.py` / `editor/exporter.py` / `editor/image_cache.py` に
**別々の実装で 3 つ**あり、`config` だけシンボリックリンクを見ていなかった。
安全に関わる規則の実装が複数あると、1 つ直しても他が残る。ここへ寄せる。
"""

from pathlib import Path

from hitofude.core.paths import relative_inside, resolve_inside, resolve_reference


class TestRelativeInside:
    def test_中を指す相対パスは通す(self, tmp_path: Path) -> None:
        assert relative_inside(tmp_path, "attachments/a.png") == Path("attachments/a.png")

    def test_存在しなくても通す(self, tmp_path: Path) -> None:
        """まだ作られていない保存先にも使う。存在は別の話。"""
        assert relative_inside(tmp_path, "これから作る.md") is not None

    def test_絶対パスは弾く(self, tmp_path: Path) -> None:
        assert relative_inside(tmp_path, "/etc/passwd") is None

    def test_親をたどるパスは弾く(self, tmp_path: Path) -> None:
        assert relative_inside(tmp_path, "../外.md") is None

    def test_途中で親へ戻るパスも弾く(self, tmp_path: Path) -> None:
        assert relative_inside(tmp_path, "a/b/../../../外.md") is None

    def test_中で行って戻るのは通す(self, tmp_path: Path) -> None:
        assert relative_inside(tmp_path, "a/../b.md") is not None

    def test_シンボリックリンクで外へ出るのは弾く(self, tmp_path: Path) -> None:
        """`config` だけがこれを見ていなかった。"""
        outside = tmp_path.parent / "外部"
        outside.mkdir(exist_ok=True)
        (tmp_path / "抜け道").symlink_to(outside)
        assert relative_inside(tmp_path, "抜け道/秘密.md") is None

    def test_中を指すシンボリックリンクは通す(self, tmp_path: Path) -> None:
        (tmp_path / "本体").mkdir()
        (tmp_path / "別名").symlink_to(tmp_path / "本体")
        assert relative_inside(tmp_path, "別名/a.md") is not None

    def test_空文字は弾く(self, tmp_path: Path) -> None:
        assert relative_inside(tmp_path, "") is None


class TestResolveInside:
    def test_実ファイルなら絶対パスを返す(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("本文", encoding="utf-8")
        assert resolve_inside(tmp_path, "a.md") == (tmp_path / "a.md").resolve()

    def test_無ければNone(self, tmp_path: Path) -> None:
        assert resolve_inside(tmp_path, "居ない.md") is None

    def test_フォルダはNone(self, tmp_path: Path) -> None:
        (tmp_path / "フォルダ").mkdir()
        assert resolve_inside(tmp_path, "フォルダ") is None

    def test_外は読めない(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "外.md"
        outside.write_text("秘密", encoding="utf-8")
        assert resolve_inside(tmp_path, "../外.md") is None


class TestResolveReference:
    """本文に書かれた参照（`![](…)` のパス）を解決する。"""

    def test_相対パスを解決する(self, tmp_path: Path) -> None:
        (tmp_path / "a.png").write_bytes(b"x")
        assert resolve_reference(tmp_path, "a.png") is not None

    def test_パーセント符号化を戻す(self, tmp_path: Path) -> None:
        (tmp_path / "写真 1.png").write_bytes(b"x")
        assert resolve_reference(tmp_path, "写真%201.png") is not None

    def test_file_スキームを剥がす(self, tmp_path: Path) -> None:
        (tmp_path / "a.png").write_bytes(b"x")
        assert resolve_reference(tmp_path, "file://a.png") is not None

    def test_httpは取りに行かない(self, tmp_path: Path) -> None:
        """描画や書き出しのたびに通信しない。"""
        assert resolve_reference(tmp_path, "https://example.com/a.png") is None

    def test_dataURIはそのまま(self, tmp_path: Path) -> None:
        assert resolve_reference(tmp_path, "data:image/png;base64,AAAA") is None

    def test_絶対パスは読まない(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "秘密.png"
        outside.write_bytes(b"x")
        assert resolve_reference(tmp_path, str(outside)) is None

    def test_file_スキームの絶対パスも読まない(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "秘密2.png"
        outside.write_bytes(b"x")
        assert resolve_reference(tmp_path, f"file://{outside}") is None

    def test_起点が無ければNone(self) -> None:
        assert resolve_reference(None, "a.png") is None
