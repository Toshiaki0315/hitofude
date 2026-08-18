# ADR-0013: front matter は折りたたみ表示ではなく完全に隠す

- **日付**: 2026-08-18
- **状態**: 採用（実装済みの判断の追認）
- **覆す対象**: spec.md §7.2「front matter を隠すか」

## 背景

spec §7.2 は「既定で**折りたたみ表示**（`▸ メタデータ` の 1 行に潰す）。
`Cmd+/` のソースモードで展開。最初の行にオーバーレイ描画」と定めている。

実装はこれと異なり、front matter を**常に完全に隠す**。`▸ メタデータ` の
オーバーレイは描かず、Raw（ソースモード）でも表示しない。この判断は
`editor/highlighter.py` と `tests/editor/test_highlighter.py`
（`TestFrontMatterStaysHidden`）に理由付きで実装・固定されていたが、
spec への反映と ADR が漏れていた（2026-08-18 のレビューで発見）。

## 決定

front matter は**どのモードでも表示しない**。

- 折りたたみ 1 行（`▸ メタデータ`）のオーバーレイは作らない
- Raw（`Cmd+/`）でも出さない
- `Cmd+A`・`Cmd+X`・貼り付け・Backspace などの編集経路は、front matter を
  巻き込まないよう本文の先頭へ丸める（`_guard_front_matter` / `selectAll` /
  `cut` のオーバーライド）

## 根拠

- `id` / `created` / `modified` は**アプリの管理情報**で、書く人が触る
  ものではない。誤って消すと ULID による同一性（改名耐性）が失われ、
  復元できない（ユーザー要望として highlighter に記録済み）
- Raw は「Markdown の記号を出して直す」ためのモードであり、記法ではない
  ものまで出す必要がない
- 折りたたみ表示には「1 行に潰した行の高さ・クリック判定・キャレットの
  素通り」という R4/R5 と干渉しやすい実装が必要になる。完全隠蔽なら
  既存のマーカー隠蔽（`setFontPointSize(0.5)`）だけで成立する
- メタデータを直したい場合はファイルを他のエディタで開けばよい
  （ノートは素の `.md`。G3）

## 影響

- spec §7.2 の当該項に「→ ADR-0013 で変更」を追記
- 不可侵ルール（CLAUDE.md §3）への影響なし。R4 の手段のみで実装されている
- 回帰テスト: `tests/editor/test_highlighter.py::TestFrontMatterStaysHidden`
  （通常・Raw の両方で隠れたままであること）
