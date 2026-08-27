# 覚書（OboeGaki）

ライブプレビュー型 Markdown エディタ（macOS）。旧名 Hitofude（ADR-0032 で改名）。

編集画面とプレビュー画面が分かれておらず、単一のテキスト領域で入力しながら装飾が反映される。
Markdown のマーカー（`**`, `#`, `- ` など）はキャレットが要素の外にあるとき隠れ、中に入ると現れて編集できる。
ノートは**素の `.md` ファイル**としてローカルフォルダに保存される（独自形式を使わない）。

| | |
|---|---|
| 対象 OS | macOS 13 Ventura 以降（Apple Silicon）        |
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
- 使っているものとライセンス: [docs/licenses.md](docs/licenses.md)

**本プロジェクトはテスト駆動開発で進める。** テストが緑でないコミットは作らない。

## ライセンス

[MIT](LICENSE)

依存しているライブラリの許諾条件と、配布のときにやることは
[docs/licenses.md](docs/licenses.md) にまとめてある。**Qt（PySide6）が
LGPL-3.0 なので、配布は「表示すれば済む」ものではない。**

同梱する PySide6 は LGPLv3 で、**ソースを MIT で配ることには影響しない**。
ビルドした `.app` を再配布する場合だけ LGPL の条件（Qt を差し替えられること）
を満たす必要がある。

## 同梱している他所のソフトウェア

| もの | 用途 | ライセンス |
| --- | --- | --- |
| [Mermaid](https://github.com/mermaid-js/mermaid) 11.16.1 | 書き出した HTML で図を描く | MIT（`hitofude/resources/vendor/mermaid-LICENSE.txt`） |

書き出した HTML には Mermaid 本体と**その MIT 表記**が一緒に埋め込まれる。
`mermaid.min.js` には mermaid 自身の著作権表示が入っていないため、こちらで添えている。

依存ライブラリ（PySide6 ほか）は `pyproject.toml` を参照。**PySide6 は LGPLv3** なので、
`.app` を第三者へ配布する場合は別途その条件も確認すること。
