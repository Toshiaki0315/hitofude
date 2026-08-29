"""同じ保管フォルダを渡し直しても抱えた絵を捨てない（レビュー 2026-08-29）。

`set_base_path` は**毎回**捨てていた。置き場が変わったなら正しいが、
同じ場所を渡し直しただけなら捨てる理由がない。

描き方の設定を 1 か所から流すようにした（`_apply_view_settings`）ため、
**文字を大きくするたびに**ここを通るようになり、そのたびに絵を捨てて
いた（実測: `Cmd +` 1 回で 1 回）。
"""

from pathlib import Path

from hitofude.editor.image_cache import ImageCache


class TestSetBasePath:
    def test_同じ場所なら捨てない(self, tmp_path: Path) -> None:
        cache = ImageCache(tmp_path)
        calls: list[int] = []
        cache.clear = lambda: calls.append(1)  # type: ignore[method-assign]
        cache.set_base_path(tmp_path)
        assert calls == []

    def test_場所が変われば捨てる(self, tmp_path: Path) -> None:
        cache = ImageCache(tmp_path)
        calls: list[int] = []
        cache.clear = lambda: calls.append(1)  # type: ignore[method-assign]
        cache.set_base_path(tmp_path / "べつ")
        assert calls == [1]

    def test_Noneへの変更も捨てる(self, tmp_path: Path) -> None:
        cache = ImageCache(tmp_path)
        calls: list[int] = []
        cache.clear = lambda: calls.append(1)  # type: ignore[method-assign]
        cache.set_base_path(None)
        assert calls == [1]
