# Hitofude

ライブプレビュー型 Markdown エディタ（macOS）。

編集画面とプレビュー画面が分かれておらず、単一のテキスト領域で入力しながら装飾が反映される。
Markdown のマーカー（`**`, `#`, `- ` など）はキャレットが要素の外にあるとき隠れ、中に入ると現れて編集できる。
ノートは**素の `.md` ファイル**としてローカルフォルダに保存される（独自形式を使わない）。

| | |
|---|---|
| 対象 OS | macOS 13 Ventura 以降（Apple Silicon / Intel） |
| 言語 | Python 3.12+ |
| GUI | PySide6（Qt 6.8 LTS / 6.9） |
| 保存形式 | ローカルの `.md` プレーンテキスト |

## セットアップ

[uv](https://docs.astral.sh/uv/) が必要。

```bash
make setup
```

## 起動

```bash
make run
```

## 開発

```bash
make check
```

`make help` で全コマンドを表示。

依存を足すときは `uv add`（開発用は `uv add --dev`）を使う。
**`pip install` は使わない** — `uv.lock` が更新されず、他の環境で結果が変わる。

- 開発の作業規約: [CLAUDE.md](CLAUDE.md)
- 仕様書（設計判断の根拠）: [docs/spec.md](docs/spec.md)
- 実装タスクと進捗: [docs/TASKS.md](docs/TASKS.md)

**本プロジェクトはテスト駆動開発で進める。** テストが緑でないコミットは作らない。
