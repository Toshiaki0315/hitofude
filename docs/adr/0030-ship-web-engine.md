# ADR-0030: `.app` に QtWebEngine を同梱し、arm64 だけに削る

- 状態: 採用
- 日付: 2026-08-26
- 関連: [ADR-0012](0012-apple-silicon-only.md)（Intel 対象外）、
  [ADR-0020](0020-math-inline-rendering.md)（数式）、[ADR-0021](0021-mermaid-inline-rendering.md)（Mermaid）、
  仕様書 §8.1

## 何が起きたか

`make app` で作った `.app` が、起動と同時に py2app の "Launch error" で
落ちるとユーザーから報告があった（2026-08-26）。バンドルの実行ファイルを
直に叩くと理由が出た。

```
ModuleNotFoundError: No module named 'PySide6.QtWebEngineWidgets'
```

直すと次が出て、それも直すと次が出た。**3 つ重なっていた**。

| # | 症状 | 原因 |
|---|---|---|
| 1 | `PySide6.QtWebEngineWidgets` が無い | Mermaid（ADR-0021）で使い始めたのに、`setup.py` が**除外したまま**だった |
| 2 | `ziamath.fonts` が無い | 数式（ADR-0020）のフォントは実行時に `importlib.resources` で読む。`packages` に入れないと py2app は `.py` だけ拾う |
| 3 | `SIGKILL (Code Signature Invalid)` | `lipo` で CPU を削ると署名が合わなくなる。`codesign --deep` は `Contents/Resources/` の下まで届かない |

いずれも**普段のテストでは動かない道**だったので、誰も気づけなかった。
ビルドは 2026-08-19 の Mermaid 導入から一度も通していなかったことになる。

## 決めたこと

### 1. QtWebEngine は同梱する

除外をやめ、`QtWebEngineWidgets` が動くのに要るフレームワーク一式
（`otool -L` の実測で 13 個）と qml モジュールを残す。

引き換えはサイズで、Chromium の枠組みだけで 572MB ある。
**同梱しない案**（`.app` では図を諦める）とユーザーに諮り、
**同梱する**を選んでもらった。図が出ない配布物は機能の穴になる。

### 2. arm64 だけに削る

wheel の Qt は universal（x86_64 + arm64）。`lipo -thin arm64` で全体が
**ほぼ半分**になる。仕様書 §4 と ADR-0012 が既に **Intel を対象外**と
決めているので、両方を持ち歩く理由が無い。

| | 大きさ |
|---|---|
| 削る前（WebEngine 込み） | 1,294 MB |
| 削った後 | **557 MB** |

内訳の工夫: Chromium の翻訳は 100 言語で 38MB あるので `ja` と `en-US`
だけ残す。開発者ツールの資源（10MB）は絵にするだけなら要らない。

### 3. 署名は 1 つずつやり直す

`lipo` はバイナリを書き換えるので、元の署名が合わなくなる。dyld は
読み込む瞬間に **SIGKILL** で殺す（crash report の
`CODESIGNING / Invalid Page`）。

`codesign --deep` では届かない。PySide6 が持ち込む Qt は
`Contents/Resources/` の下——macOS から見れば「入れ子のコード」ではなく
**ただの資源**で、封をするときにハッシュは取られても中身の署名は
触られない。深いものから順に 1 つずつ署名し直す（243 個）。

## 落ちない形にもした

同梱の判断とは別に、**無いなら諦める**形に直した。

- `app.py` の先読みは `preload_web_engine()` にして、無ければ警告を書いて先へ進む
- `mermaid_cache` は取り出し口を 1 か所にまとめ、ImportError を「描けなかった」として扱う
- 履歴の掃除（`storage/history.prune`）は、置き場が読めなくても起動を止めない
  （書類フォルダの許可を**断った**ときに実際に落ちていた）

図が出ないのは我慢できるが、**起動しないのは我慢できない**。

## 二度と気づかないことにしないために

`tests/test_packaging.py` が `hitofude/` の import と `setup.py` を突き合わせる。

- 外から入れたものが `packages` / `includes` に無ければ落ちる（#2 を捕まえる）
- `excludes` に書いたものを import していたら落ちる（#1 を捕まえる）

#3 は実際に組まないと出ないので、**`make app` の後に一度起動する**ことを
`docs/manual_test.md` の手順に入れた。

## 追記（同日）: サイズ削減レビューで 557 → 435MB、ついでに QtPdf の欠落を修正

ユーザー依頼で「もっと小さくできないか」をレビューした（対象は
Apple Silicon のみ。ADR-0012 の再確認）。バンドルの中身を実測して、
**実行時に読まれないもの**を 4 種類見つけた。

| 削ったもの | 大きさ | なぜ要らないか |
|---|---|---|
| PySide6 の開発道具（lupdate 39MB ほか 17 個） | 53MB | アプリの実行に無関係。lupdate だけで Chromium 以外のどの部品より大きい |
| ffmpeg（libav* / libsw*） | 36MB | QtMultimedia（削除済み）の付属。WebEngine は自前のコーデックを静的に持つ。symlink の組が py2app で実体の複製になり 2 倍になっていた |
| Qt/qml と Qt/metatypes | 38MB | QWebEngineView（Widgets）は qml のモジュール置き場を読まない——**消しても図が描けることをバンドルの中で実測**（ADR-0030 本文の「QtQuick 一式が要る」は誤りだった） |
| import しない Python 束縛（QtOpenGL 10MB ほか） | 15MB | フレームワーク（C++ 側）は dyld が要るが、束縛はただの重り。残すものは実測の import 一覧から決めた（KEEP_BINDINGS） |

    557 MB → 435 MB（元の universal 比 66% 削減）

**逆に足りないものも見つかった。** `QtPdf`（PDF の取り込み。F-2）を
import しているのに KEEP に無く、`.app` では
`No module named 'PySide6.QtPdf'` になっていた。KEEP へ足して修正。
`tests/test_packaging.py` に「hitofude の PySide6 import は
prune_bundle の KEEP_FRAMEWORKS / KEEP_BINDINGS に入っている」検査を
足し、この形の欠落は機械で捕まえる。

確認: まっさらな環境から起動 / バンドル内で QtPdf・数式・Mermaid が動く /
`codesign --verify --deep --strict` が通る。

### 残っているもの（これ以上は削りにくい）

- Chromium 本体 211MB（arm64 済み）— Mermaid の対価。これが総量の半分
- ICU データ 10MB、Python 本体 13MB、PIL 14MB、lxml 11MB — いずれも実際に使う
