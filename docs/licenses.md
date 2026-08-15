# 使っているものとライセンス

Hitofude が依存しているライブラリと、その許諾条件の一覧。

**この表は手で書いていない。** 実際に入っているパッケージのメタデータと、
ビルドした `.app` の中身から起こしている。書き写すと必ず古くなるので、
依存を足したときは同じやり方で確かめ直すこと（末尾の「調べ直し方」）。

最終確認: 2026-08-15 / PySide6 6.9.3

---

## Hitofude 自身

|            |                        |
| ---------- | ---------------------- |
| ライセンス | MIT（`LICENSE`）       |
| 著作権     | © 2026 Toshiaki Nomura |

## アプリに同梱されるもの

`make app` で作った `dist/Hitofude.app` に**実際に入っていたもの**。
配布するときは、ここに挙げた許諾表示を添える必要がある。

| ライブラリ                                    | 版     | ライセンス                              | 使っている場所                           |
| --------------------------------------------- | ------ | --------------------------------------- | ---------------------------------------- |
| PySide6 / PySide6-Essentials / PySide6-Addons | 6.9.3  | **LGPL-3.0-only** OR GPL-2.0 OR GPL-3.0 | 画面全体（Qt の Python 束縛）            |
| shiboken6                                     | 6.9.3  | **LGPL-3.0-only** OR GPL-2.0 OR GPL-3.0 | PySide6 の土台                           |
| markdown-it-py                                | 4.2.0  | MIT                                     | 書き出しのブロック解析（`core/html.py`） |
| mdit-py-plugins                               | 0.6.1  | MIT                                     | 表・脚注・数式・`:::note` の拡張         |
| mdurl                                         | 0.1.2  | MIT                                     | markdown-it-py が使う URL 処理           |
| Pygments                                      | 2.20.0 | BSD-2-Clause                            | コードの色分け（画面と書き出し）         |
| latex2mathml                                  | 3.81.0 | MIT                                     | 数式を MathML にする（HTML 書き出し）    |
| PyYAML                                        | 6.0.3  | MIT                                     | front matter の読み書き                  |
| watchdog                                      | 6.0.0  | Apache-2.0                              | 保管フォルダの監視                       |

使っている Qt のモジュールは `QtCore` / `QtGui` / `QtWidgets` /
`QtPrintSupport` の 4 つ（PDF の読み込みを入れると `QtPdf` が加わる）。

## 書き出した HTML に入るもの

| ライブラリ | ライセンス | 備考                                                        |
| ---------- | ---------- | ----------------------------------------------------------- |
| mermaid    | MIT        | 図のあるノートを HTML に書き出したときだけ埋め込む（3.4MB） |

**書き出した HTML はそれ自体が mermaid の複製物になる**ので、MIT の求める
著作権表示と許諾表示を中に入れている（`editor/exporter._mermaid_notice`）。
`mermaid.min.js` 自身には mermaid の表記が入っていないため、こちらで添えた。

## 開発のときだけ使うもの

**配布物には入らない**（`.app` の中に無いことを確認済み）。

| ライブラリ                                                      | 版             | ライセンス                                      | 用途              |
| --------------------------------------------------------------- | -------------- | ----------------------------------------------- | ----------------- |
| pytest                                                          | 9.1.1          | MIT                                             | テスト            |
| pytest-qt                                                       | 4.5.0          | MIT                                             | GUI テスト        |
| pytest-cov / coverage                                           | 7.1.0 / 7.15.4 | MIT / Apache-2.0                                | カバレッジ        |
| ruff                                                            | 0.16.2         | MIT                                             | lint と整形       |
| py2app                                                          | 0.28.10        | MIT or PSF                                      | `.app` の組み立て |
| altgraph / macholib / modulegraph                               | —             | MIT                                             | py2app が使う     |
| setuptools / packaging / pluggy / iniconfig / typing_extensions | —             | MIT / Apache-2.0 or BSD-2 / MIT / MIT / PSF-2.0 | 各ツールの土台    |

## これから増えるもの（F 群 / 未着手）

PowerPoint との行き来（TASKS.md の F-3 / F-5）で入る予定。**まだ入れていない。**

| ライブラリ  | ライセンス   | 大きさ |
| ----------- | ------------ | ------ |
| python-pptx | MIT          | 1.4MB  |
| lxml        | BSD-3-Clause | 19MB   |
| Pillow      | MIT-CMU      | 13MB   |

Pillow が同梱するネイティブライブラリ（実測で入っていたもの）:

| ライブラリ                       | ライセンス                            |
| -------------------------------- | ------------------------------------- |
| FreeType                         | FTL（GPLv2 との二択。**FTL を選ぶ**） |
| libjpeg-turbo                    | IJG / BSD-3-Clause                    |
| libtiff                          | libtiff（BSD 系）                     |
| libwebp / libsharpyuv            | BSD-3-Clause                          |
| libpng                           | PNG Reference Library License         |
| OpenJPEG / libavif               | BSD-2-Clause                          |
| Little CMS 2 / HarfBuzz / Brotli | MIT                                   |
| libxcb / libXau                  | X11（MIT 系）                         |
| zlib-ng / liblzma                | Zlib / 0BSD                           |

**`libimagequant`（GPL-3.0-or-later）は入っていない。** SBOM には名前が
あるが、`PIL.features.check("libimagequant")` は `False` で、`.dylibs` にも
無い。**入ると `.app` 全体に GPL の義務が及ぶ**ので、Pillow の版を上げる
ときは毎回ここを確かめること（`raqm` も同じ。LGPL の FriBiDi を連れてくる）。

lxml は libxml2 / libxslt を静的に埋め込んでいる（どちらも MIT）。
GPL なのは配布物に入らないテスト実行スクリプトだけ。

## フォント

**同梱しない。** macOS に元からあるものを名前で指定しているだけ。

| フォント      | 使い道                                    |
| ------------- | ----------------------------------------- |
| Hiragino Sans | 本文の既定                                |
| BIZ UDGothic  | 表（全角が半角のちょうど 2 倍。ADR-0003） |
| Menlo         | コードブロック                            |

## 配布のときにやること

1. **LGPL-3.0（PySide6 / shiboken6）** — ここだけ「表示すれば済む」ものではない
   - 許諾条文（LGPL-3.0 と GPL-3.0）を同梱し、Qt を使っている旨を表示する
   - **利用者が Qt を差し替えられる状態にする**（動的リンクのまま配る。
     `.app` の中の `.dylib` を入れ替えれば動くこと）
   - Qt に手を入れたなら、その変更を提供できるようにする（手は入れていない）
   - 差し替えを妨げる仕掛け（DRM）を入れない
2. **MIT / BSD / Apache-2.0 / PSF / FTL など** — 著作権表示と許諾条文を同梱する。
   Apache-2.0（watchdog）は `NOTICE` があればそれも添える
3. **Pillow を足したら** `libimagequant` が入っていないことを確かめる（上記）

## 調べ直し方

```bash
uv run python -c "
import importlib.metadata as md
for d in md.distributions():
    m = d.metadata
    print(m['Name'], d.version, m.get('License-Expression') or m.get('License'))
"
```

`.app` に実際に入るものは、ビルドしてから確かめる。

```bash
ls dist/Hitofude.app/Contents/Resources/lib/python*/
```
