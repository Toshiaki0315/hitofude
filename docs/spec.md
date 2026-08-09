# ライブプレビュー型 Markdownエディタ 仕様書

**プロジェクト名（仮）**: `Hitofude`
**対象OS**: macOS 13 Ventura 以降（Apple Silicon / Intel）
**開発言語**: Python 3.12+
**GUIフレームワーク**: PySide6（Qt 6.8 LTS 系 / 6.9系）
**保存先**: ローカルファイルシステム（`.md` プレーンテキスト）
**作成日**: 2026-08-07

---

## 0. この文書の使い方

本書は「調査結果 → 技術選定 → 設計 → 実装タスク」の順に構成されている。
Claude Code 等のコーディングエージェントに渡す場合は、**§9 の開発ロードマップのフェーズ単位**で指示するとスコープが破綻しにくい。
§3 は「なぜその方式なのか」の根拠であり、実装時に迷ったときの判断基準として参照する。

---

## 1. ゴールと非ゴール

### 1.1 ゴール

| # | 内容 |
|---|---|
| G1 | 編集画面とプレビュー画面が**分かれていない**。単一のテキスト領域で入力しながら装飾が反映される |
| G2 | Markdown 記法のマーカー（`**`, `#`, `- ` など）は、**キャレットがその要素の外にあるとき隠れる**。中にあるときは現れて編集できる |
| G3 | ファイルは**ユーザーが指定したローカルフォルダに素の `.md` として保存**される。独自バイナリ形式を使わない |
| G4 | 数千ノート規模でも、全文検索・タグ絞り込みが 200ms 以内で返る |
| G5 | 入力遅延（キー押下 → 画面反映）が**16ms 以内**（60fps を割らない） |
| G6 | Python だけで完結する。JavaScript / Web エンジンを実行時依存に含めない |

### 1.2 非ゴール（v1 では作らない）

- クラウド同期、マルチデバイス（ファイルは iCloud Drive 等のフォルダに置けば実質同期できるので v1 では OS 任せ）
- 共同編集
- Windows / Linux 対応（コードは移植可能に保つが、テストとビルドは macOS のみ）
- WYSIWYG な表エディタ（**→ ADR-0003 で変更**。罫線は描くが、セル内の折り返しは行わない）

---

## 2. 用語定義

| 用語 | 定義 |
|---|---|
| **ライブプレビュー（Live Preview）** | 入力中のテキストに対して装飾がその場で適用される表示方式。Typora / Obsidian の「ライブプレビュー」に相当 |
| **マーカー（Marker / Syntax Token）** | `**`、`# `、`` ` ``、`> ` など、Markdown の構文記号そのもの |
| **フォーカスブロック** | キャレット（テキストカーソル）が現在存在する QTextBlock |
| **リビール（Reveal）** | フォーカス中の要素のマーカーを一時的に表示状態へ戻すこと |
| **ブロック（Block）** | Qt の `QTextBlock`。原則として「Markdown ソースの 1 行」と 1:1 で対応させる |
| **ノート** | 1 つの `.md` ファイル |

---

## 3. 方式調査

### 3.1 エディタの表示方式は 3 種類ある

| 方式 | 説明 | 代表例 | 内部モデル |
|---|---|---|---|
| **A. 分割プレビュー** | 左に生ソース、右に HTML | MacDown, Mou, CuteMarkEd | ソース文字列 |
| **B. ハイブリッド / インライン装飾** | ソース文字列を保持したまま、その上に装飾スタイルを重ねる。マーカーは隠す/薄くする | **Obsidian Live Preview**, iA Writer | **ソース文字列**（＝真実の source of truth） |
| **C. 完全 WYSIWYG** | 内部はリッチテキストの木構造。Markdown は入出力フォーマットに過ぎない | **Typora**, **Notion**, Craft | ドキュメントツリー |

**本プロジェクトの採用: B（ハイブリッド）**

理由:

1. **ソース文字列が唯一の真実**なので、保存が `open(path,"w").write(text)` で済み、往復変換によるデータ破損が構造的に起きない（G3 に直結）。
2. C 方式は「入力 → ツリー変換 → ツリー → Markdown 直列化」の 2 段変換が必要で、記法の取りこぼし＝データ損失になる。個人のノートアプリで最も避けるべき事故。
3. 独自記法を採る一部のノートアプリは、ユーザーからは C に見えて実体は B に近い（マーカーを隠しているだけで、互換モードに切り替えると素の記法が見える）。**見た目が WYSIWYG であることと、内部モデルがツリーであることは別問題**であり、B でも目標の体験は達成できる。
4. C は Undo/Redo、IME 変換中の挙動、コピー&ペーストの整合性が桁違いに難しい。Python + Qt で現実的に完遂できるのは B。

> **参考**: Typora は「インライン装飾（`**` など）は入力し終えた瞬間に反映、ブロック装飾（`###`, `- [ ]`）は Enter でフォーカスが外れた時点で確定」という段階的な反映をしている。この 2 段階の反映タイミングは B 方式でも再現でき、体感品質に大きく効くので採用する（§6.4）。

### 3.2 記法の基準と独自拡張の方針

タグベースのノートアプリには、Markdown ではない独自記法（`::ハイライト::`、`#tag` など）を既定とし、設定で CommonMark 準拠モードに切り替えられるものがある。この種のアプリはノートを独自形式で保存し、Markdown はエクスポート時の形式に過ぎない。

**本アプリの方針**: 先行アプリの *UX*（マーカーが隠れる、タグがインラインで書ける、サイドバーがタグツリー）は取り入れるが、*記法* は **CommonMark + GFM 拡張**を基準とし、**保存形式も素の Markdown とする**（G3）。GFM に無い便利記法のうち、以下だけを独自拡張として採用する。

| 拡張記法 | 本アプリでの扱い |
|---|---|
| `#タグ` / `#親/子` | **採用**。行頭・行中どちらでも認識。`#` の直後が空白でないこと、が条件 |
| `::ハイライト::` | **採用**（GFM にないため独自）。設定で無効化可能 |
| `- [ ]` / `- [x]` | GFM タスクリストとして採用 |

### 3.3 Qt での実装方式の比較（**実機検証済み**）

Qt には Markdown を扱う道が 2 つある。どちらを採るかがこのプロジェクト最大の分岐点。

#### 方式 Q1: `QTextDocument.setMarkdown()` / `toMarkdown()` を使う（＝ C 方式）

Qt 5.14 以降、`QTextDocument` は Markdown の読み書きを標準サポートする。一見これが最短ルートに見える。

**→ 却下。実機検証で往復変換が壊れることを確認した。**

PySide6 6.8.0.2 で以下を実行した結果:

```python
d = QTextDocument()
d.setMarkdown(src)
print(d.toMarkdown())
```

入力:

````markdown
```python
x = 1
```

| A | B |
|---|---|
| 1 | 2 |

[link](https://x.com)  #tag
````

出力（抜粋、原文ママ）:

```
```python
x = 1

|```
 |A|B|
|-|-|
|1|2|

[link](https://x.com)  \#tag
```

**確認された破壊**:

1. **フェンスドコードブロックの閉じフェンスが消失**し、直後の表の行と融合して `|``` ` という壊れた行が生成された。
2. **表の整形が崩れ**、閉じフェンスの残骸を巻き込んだ。
3. `#tag` が `\#tag` に**エスケープされ**、タグとして機能しなくなった。
4. 空白・改行の正規化により、保存のたびにファイルの diff が発生する（Git 管理と相性が最悪）。

加えて Qt 公式ドキュメントも「`toMarkdown()` は無効化を指定しても GitHub 拡張を出力してしまうことがある（将来修正されうる）」「QTextDocument が表現できても純粋な Markdown に書けない属性は欠落する」「YAML front matter のパーサは同梱していない」と明記している。

> **結論**: `setMarkdown()` は **読み取り専用のエクスポート/プレビュー用途に限定**する。編集モデルには絶対に使わない。

#### 方式 Q2: `QPlainTextEdit` + `QSyntaxHighlighter` でソース文字列に装飾を重ねる（＝ B 方式）

**→ 採用。**

- ドキュメントの中身は**常に生の Markdown 文字列**。`toPlainText()` がそのまま保存内容になる。
- `QSyntaxHighlighter.highlightBlock()` が変更ブロックだけに対して自動で呼ばれるため、**差分レンダリングが標準で効く**（G5 に直結）。
- Undo/Redo、IME、検索、コピペはすべて Qt の標準実装がそのまま使える。

##### 検証: マーカーは本当に「隠せる」のか

Qt の `QTextCharFormat` には CSS の `display:none` に相当する機能がない。そのため「マーカーを隠す」を近似する必要がある。3 案を実測した（`QTextDocument.idealWidth()` で描画幅を計測、DejaVu Sans 14pt、文字列 `**abc**`）。

| 手法 | 描画幅 | 評価 |
|---|---|---|
| 何もしない | 80.12 px | — |
| 前景色を薄いグレーに（dim） | 80.12 px | 幅が変わらない＝マーカーの隙間が残る。Obsidian 初期実装と同等 |
| **`setFontPointSize(0.5)`** | **44.12 px** | **採用**。マーカー 4 文字分が 38px → 2px に潰れる |
| `setFontPointSize(0.5)` + `setFontStretch(1)` | 44.88 px | 改善せず。不要 |
| （参考）マーカーなしの `abc` | 42.12 px | 理論下限 |

**結論**: `setFontPointSize(0.5)` により、マーカー 1 文字あたり残る幅は **約 0.5px**。人間の目には消えて見え、かつ以下の重要な性質を保つ。

- 文字は**実在し続ける**ので、`QTextCursor` の位置とソース文字列のオフセットが**常に 1:1 で一致する**。位置マッピングのテーブルが一切要らない。これが本方式最大の利点。
- キャレットが要素内に入った瞬間、フォントサイズを本来の値に戻すだけでマーカーが現れる（リビール）。

**注意点（実装時に必ず対処）**:

- 極小フォントは行の高さ計算に影響しうる。**マーカーには本文と同じフォントファミリを指定した上でサイズのみ縮める**こと。行高が跳ねる場合は `QTextBlockFormat.setLineHeight()` で明示固定する。
- テキスト選択時、潰れたマーカーも選択範囲に含まれる（＝コピーすると `**` が付いてくる）。これは**仕様として正しい**（生 Markdown をコピーできる）。プレーンテキストとしてコピーしたい場合は `Cmd+Shift+C` を別途割り当てる。

##### 検証: ブロックレベルの装飾（余白・インデント・行高）

> **→ ADR-0002 で変更。** 以下の記述は実装前の検証時点のもの。実機で追試したところ
> `QPlainTextDocumentLayout` はブロック書式を無視し、また下記の対処コードは
> Undo 履歴を破壊することが分かった。v1 ではブロック書式を使わない。

`highlightBlock()` は `QTextCharFormat` しか適用できず、**`QTextBlockFormat`（インデント、上下マージン、行高）は変更できない**。見出しの上下余白、リストのぶら下げインデント、引用の左マージンにはこれが必須。

検証したところ、`QTextCursor.mergeBlockFormat()` でブロック書式は適用できるが、**副作用として `document.isModified()` が True になり、Undo スタックにも積まれる**ことを確認した。

**対処（必須）**:

```python
doc.blockSignals(True)
was_modified = doc.isModified()
doc.setUndoRedoEnabled(False)  # ← アンドゥ汚染を防ぐ
cursor.mergeBlockFormat(block_format)
doc.setUndoRedoEnabled(True)
doc.setModified(was_modified)  # ← 「変更あり」フラグの誤検知を防ぐ
doc.blockSignals(False)
```

この処理は `highlightBlock()` の中では**行わない**（再入の危険がある）。`QTextDocument.contentsChange` シグナル経由で、ハイライト完了後にキューイングして実行する（§6.3）。

### 3.4 Markdown パーサの選定と、その使い分け（**実機検証済み**）

`markdown-it-py`（検証時点の最新: **4.2.0**）を採用。CommonMark 100% 準拠、プラグイン機構あり、純 Python。

ただし決定的な制約を検証で確認した:

```
heading_open   | map=[0, 1]     ← ブロックトークンには行範囲がある
inline         | map=[0, 1]
    child: strong_open  map=None ← インライントークンには位置情報がない
    child: code_inline  map=None
```

**ブロックトークンは `token.map = [開始行, 終了行]` を持つが、インラインの子トークンは `map=None`** で、ソース上のオフセットを取得できない。

**したがってレイヤを分ける（本設計の中核）**:

| レイヤ | 担当 | 用途 |
|---|---|---|
| **ブロック解析** | `markdown-it-py` | 見出しレベル、リストの深さ、コードフェンスの範囲、引用の入れ子、表の範囲を **行番号単位**で確定。文書全体（またはダーティ範囲）に対して実行 |
| **インライン解析** | **自作の正規表現スキャナ**（`inline_scanner.py`） | `**`, `*`, `` ` ``, `~~`, `::`, `[]()`, `#tag` の**文字オフセットを 1 ブロック内で確定**。`highlightBlock()` から呼ばれる |

インラインを自作にするのは妥協ではなく必然。`highlightBlock()` は 1 行だけを受け取り、文字オフセットを要求するため、markdown-it の出力形式とそもそも噛み合わない。1 行分の正規表現スキャンは十分に高速（数 µs）。

---

## 4. 技術選定

| 領域 | 採用 | バージョン目安 | 理由 / 備考 |
|---|---|---|---|
| 言語 | Python | 3.12 以上 | `match` 文、性能改善。3.13 でも可 |
| GUI | **PySide6** | 6.8 LTS 系（または 6.9） | LGPL。商用配布可。PyQt6 は GPL/商用ライセンスなので配布を考えるなら PySide6 |
| エディタウィジェット | `QPlainTextEdit` サブクラス | — | `QTextEdit` より軽い。~~画像インライン表示を v1.1 で入れるなら `QTextEdit`~~（**→ ADR-0004**。移行せずに実現した） |
| ブロックパーサ | `markdown-it-py` | 4.2.0 | `token.map` で行範囲が取れる |
| インラインパーサ | 自作 `re` ベース | — | §3.4 の理由 |
| 検索インデックス | 標準 `sqlite3` + **FTS5 trigram** | Python 同梱 | §7.3。日本語対応のため trigram 必須 |
| ファイル監視 | `watchdog` | 4.x | 外部エディタでの変更検知 |
| Front Matter | `PyYAML` | 6.x | Qt は front matter をパースしない（公式明記） |
| 設定保存 | `QSettings` | — | macOS では `~/Library/Preferences/` に plist として自動保存 |
| パッケージング | **py2app**（主）/ PyInstaller（代替） | — | §8 |
| テスト | `pytest` + `pytest-qt` | — | オフスクリーンで CI 可能 |
| Lint / Format | `ruff` | — | — |

### 4.1 `QPlainTextEdit` か `QTextEdit` か

| | `QPlainTextEdit` | `QTextEdit` |
|---|---|---|
| 大きな文書での性能 | ◎（行単位レイアウト） | ○ |
| 文字書式の適用 | ◎ Highlighter で可 | ◎ |
| ブロック書式（インデント/余白） | ○ QTextCursor 経由で可 | ◎ |
| **画像のインライン表示** | **×** → **○**（**→ ADR-0004**。行高を文字サイズで確保して `paintEvent` で描く） | **◎**（`QTextDocument.addResource` + `QTextImageFormat`） |
| 表の罫線描画 | × | △（`QTextTable`。ただしソース保持と両立が難しい） |

**v1 の判断: `QPlainTextEdit` を採用**。

画像は「`![alt](path)` の行の下に別ウィジェットで縮小表示」ではなく、**v1 ではリンクとして扱い、`Cmd+クリック` でプレビューをポップオーバー表示**する。インライン画像は v1.1 で `QTextEdit` への移行と合わせて再検討する。（**→ ADR-0004 で変更**。移行せずに `QPlainTextEdit` のままインライン表示できた）

> エディタウィジェットは `MarkdownEditor` クラスとして**基底クラスへの依存を 1 箇所に閉じ込める**設計にし、後の差し替えコストを下げること。

---

## 5. UI 仕様

### 5.1 レイアウト（3 ペイン）

```
┌───────────┬───────────────────┬────────────────────────────────────────┐
│ サイドバー │  ノートリスト      │  エディタ                               │
│ (180px)   │  (280px)          │  (可変・中央寄せ max 720px)             │
│           │                   │                                        │
│ 📝 すべて  │ ┌───────────────┐ │  # 会議メモ                            │
│ ⭐ お気に入り│ │ 会議メモ       │ │                                        │
│ 🗑 ゴミ箱  │ │ 8/7 プロジェク..│ │  今日の論点は **3 つ**。               │
│           │ ├───────────────┤ │                                        │
│ タグ       │ │ 読書メモ       │ │  - [ ] 予算確認                        │
│  #work    │ │ 8/6 第3章まで  │ │  - [x] 資料共有                        │
│   ├#会議   │ └───────────────┘ │                                        │
│   └#企画   │                   │  #work/会議                            │
│  #private │                   │                                        │
└───────────┴───────────────────┴────────────────────────────────────────┘
```

- `QSplitter` で 3 分割。幅は `QSettings` に永続化。
- `Cmd+1` / `Cmd+2` でサイドバー / ノートリストの表示トグル。
- エディタは**中央寄せ・最大幅 720px**（読みやすさのため。iA Writer と同じ）。左右に自動マージン。

### 5.2 エディタの見た目

| 要素 | スタイル |
|---|---|
| 本文フォント | 設定可。既定は `Hiragino Sans` 15pt / 行高 1.7 |
| 等幅フォント | 既定 `Menlo`（コード）/ `BIZ UDGothic`（表）。**→ ADR-0003**。`SF Mono` は macOS がアプリに公開しておらず解決されない |
| H1 | 1.8em, Bold, 上余白 24px, 下余白 12px |
| H2 | 1.5em, Bold, 上余白 20px, 下余白 10px |
| H3 | 1.25em, Bold |
| H4–H6 | 1.1em / 1.0em / 0.95em, Bold（H5/H6 はグレー） |
| 強調 `**` | Bold |
| 斜体 `*` | Italic |
| 取り消し `~~` | Strikeout |
| インラインコード | 等幅 + 背景 `#F0F0F2` + 角丸（`QTextCharFormat.setBackground`） |
| コードブロック | 等幅 + ブロック背景 + 左 4px アクセントバー（後述の描画フック） |
| 引用 `>` | 左に 3px の縦バー、左マージン 16px、文字色 60% グレー |
| リンク | アクセントカラー + 下線。`Cmd+クリック` で既定ブラウザを開く |
| タグ `#tag` | 背景色付きピル形状。クリックでそのタグで絞り込み |
| ハイライト `::` | 背景 `#FFF3A0` |
| チェックボックス | `- [ ]` を `☐` / `- [x]` を `☑` に置換描画。クリックでトグル |
| 水平線 `---` | 実線を描画（テキストは極小化して隠す） |

**背景バー・縦バー・チェックボックス記号の描画**は `QSyntaxHighlighter` では不可能なので、`MarkdownEditor.paintEvent()` をオーバーライドし、`firstVisibleBlock()` から可視ブロックを走査して `QPainter` で直接描く。ブロックのメタ情報（引用か、コードブロックか）は §6.2 の `QTextBlockUserData` から取得する。

### 5.3 テーマ

- ライト / ダーク / システム追従の 3 モード。
- 色は `theme.py` に `dataclass` で定義し、`QPalette` とハイライタの両方に流し込む。
  ただし**それだけでは macOS のネイティブ部品に届かない**（**→ ADR-0006 で補足**）。
  アプリの外観そのものも申告する。
- macOS のダークモード切り替えは `QGuiApplication.styleHints().colorSchemeChanged` シグナルで検知。

### 5.4 キーバインド

| 操作 | ショートカット | 備考 |
|---|---|---|
| 新規ノート | `Cmd+N` | |
| 保存（明示） | `Cmd+S` | 自動保存があるので実質フラッシュ |
| 検索（全ノート） | `Cmd+Shift+F` | |
| ノート内検索 | `Cmd+F` | |
| クイックオープン | `Cmd+O` | ファジー検索のパレット |
| 太字 | `Cmd+B` | 選択範囲を `**` で囲む / 既に囲まれていれば外す |
| 斜体 | `Cmd+I` | 同上、`*` |
| 取り消し線 | `Cmd+Shift+X` | `~~` |
| インラインコード | `Cmd+E` | `` ` `` |
| ハイライト | `Cmd+Shift+H` | `::` |
| リンク挿入 | `Cmd+K` | 選択文字を `[選択]()` にしてキャレットを `()` 内へ |
| 見出しレベル ±1 | `Cmd+Ctrl+↑ / ↓` | 行頭の `#` を増減 |
| チェックボックス切替 | `Cmd+Shift+T` | |
| インデント / 逆 | `Tab` / `Shift+Tab` | **リスト行のみ**。それ以外は通常のタブ挿入 |
| ソースモード切替 | `Cmd+/` | 全マーカーを表示（＝装飾を切る） |
| フォーカスモード | `Cmd+Shift+D` | 現在段落以外を減光 |
| タイプライタモード | `Cmd+Shift+Y` | キャレット行を画面中央に固定 |
| サイドバー / リスト | `Cmd+1` / `Cmd+2` | |
| プレーンテキストとしてコピー | `Cmd+Shift+C` | マーカーを除去してコピー |

### 5.5 入力補助（オートペア / スマートリスト）

`MarkdownEditor.keyPressEvent()` で実装。

1. **リスト継続**: `- item` の行末で Enter → 次行に `- ` を自動挿入。インデントも継承。
2. **空リスト項目で Enter** → マーカーを削除して段落に戻す（2 段階: `  - ` → `- ` → ``）。
3. **番号リスト**: `1. ` で Enter → `2. ` を挿入。以降の番号は**振り直さない**（ソースの diff を最小化するため。CommonMark は番号がずれても正しくレンダリングする）。
4. **囲み記号のオートペア**: 選択状態で `*`, `` ` ``, `[`, `(`, `"` を押すと選択範囲を囲む。
5. **`Cmd+V` でリンクを貼る**: 選択範囲がある状態でクリップボードが URL なら `[選択](URL)` にする。
6. **引用継続**: `> ` で始まる行で Enter → `> ` を継承。空なら解除。

**IME に関する必須事項**: 日本語変換中（プリエディット中）は上記の Enter/Tab 処理を**すべて無効化**する。`QInputMethodEvent` の処理中か、`self.inputMethodQuery(Qt.ImCurrentSelection)` で変換中か判定してガードすること。ここを怠ると日本語入力が壊滅的に使えなくなる。

---

## 6. アーキテクチャ

### 6.1 モジュール構成

```
hitofude/
├── __main__.py              # エントリポイント
├── app.py                   # QApplication のセットアップ、テーマ、シングルインスタンス
├── config.py                # QSettings ラッパ、既定値
├── theme.py                 # ThemeColors dataclass, ライト/ダーク定義
│
├── core/                    # ── GUI に依存しない層（ここは pytest で完全にテストできる）
│   ├── document.py          #   Note: パス/本文/front matter/mtime
│   ├── frontmatter.py       #   YAML front matter の分離と再結合
│   ├── block_parser.py      #   markdown-it-py ラッパ → BlockInfo のリスト
│   ├── inline_scanner.py    #   1 行 → InlineSpan のリスト（正規表現）
│   ├── tags.py              #   #tag の抽出、階層タグの分解
│   └── models.py            #   BlockInfo, InlineSpan, BlockType, SpanType
│
├── storage/                 # ── 永続化層
│   ├── vault.py             #   ノートフォルダの走査、CRUD、ゴミ箱
│   ├── index_db.py          #   SQLite + FTS5。検索、タグ集計
│   ├── watcher.py           #   watchdog。外部変更の検知
│   └── autosave.py          #   デバウンス保存、アトミック書き込み
│
├── editor/                  # ── エディタウィジェット層
│   ├── editor_widget.py     #   MarkdownEditor(QPlainTextEdit)
│   ├── highlighter.py       #   MarkdownHighlighter(QSyntaxHighlighter)
│   ├── block_decorator.py   #   QTextBlockFormat の適用（余白/インデント）
│   ├── painter_overlay.py   #   paintEvent での背景バー・チェックボックス描画
│   ├── input_handler.py     #   keyPressEvent のロジック（リスト継続等）
│   └── commands.py          #   Cmd+B などのテキスト変換コマンド
│
├── ui/                      # ── アプリケーション UI 層
│   ├── main_window.py
│   ├── sidebar.py           #   タグツリー
│   ├── note_list.py         #   ノート一覧（QListView + カスタムデリゲート）
│   ├── quick_open.py        #   Cmd+O のパレット
│   └── preferences.py
│
└── resources/
    ├── icons/
    └── styles.qss
```

**設計原則**: `core/` と `storage/` は PySide6 に依存させない（`storage/watcher.py` の Qt シグナル橋渡し部分を除く）。これによりパーサ・保存ロジックをヘッドレスでテストできる。

### 6.2 データモデル

```python
# core/models.py
from dataclasses import dataclass, field
from enum import Enum, auto


class BlockType(Enum):
    PARAGRAPH = auto()
    HEADING = auto()  # level 1..6
    BULLET_LIST_ITEM = auto()
    ORDERED_LIST_ITEM = auto()
    TASK_LIST_ITEM = auto()  # checked: bool
    BLOCKQUOTE = auto()
    CODE_FENCE_OPEN = auto()
    CODE_FENCE_BODY = auto()
    CODE_FENCE_CLOSE = auto()
    TABLE_ROW = auto()
    TABLE_DELIMITER = auto()
    HORIZONTAL_RULE = auto()
    FRONT_MATTER = auto()
    BLANK = auto()


@dataclass
class BlockInfo:
    """Markdown ソース 1 行 = QTextBlock 1 個 に対するメタ情報"""

    line: int
    type: BlockType
    level: int = 0  # 見出しレベル / リストのネスト深さ / 引用の深さ
    marker_len: int = 0  # 行頭マーカーの文字数（'## ' なら 3）
    checked: bool | None = None
    lang: str | None = None  # コードフェンスの言語
    quote_depth: int = 0


class SpanType(Enum):
    STRONG = auto()
    EM = auto()
    STRONG_EM = auto()
    CODE = auto()
    STRIKE = auto()
    HIGHLIGHT = auto()
    LINK_TEXT = auto()
    LINK_URL = auto()
    IMAGE = auto()
    TAG = auto()
    AUTOLINK = auto()


@dataclass
class InlineSpan:
    """1 行内の文字オフセット。すべて [start, end) の半開区間"""

    type: SpanType
    open_start: int  # 開きマーカー開始
    open_end: int  # 開きマーカー終端 = 内容開始
    close_start: int  # 内容終端 = 閉じマーカー開始
    close_end: int  # 閉じマーカー終端
    payload: str = ""  # リンク URL, タグ名など
```

**ブロック情報の保持**: `QTextBlockUserData` を継承した `BlockData(QTextBlockUserData)` に `BlockInfo` を格納し、`highlightBlock()` の中で `self.setCurrentBlockUserData(...)` する。`paintEvent()` や `block_decorator` はここから読む。これが Qt での標準的なやり方。

### 6.3 レンダリングパイプライン

```
ユーザー入力
    │
    ▼
QTextDocument.contentsChange(position, charsRemoved, charsAdded)
    │
    ├──▶ [同期] QSyntaxHighlighter.highlightBlock(text)   ← 変更ブロックのみ Qt が自動で呼ぶ
    │         │
    │         ├─ 1. 前ブロックの state を取得（previousBlockState）
    │         │      → コードフェンス内 / front matter 内 / 表内 かを判定
    │         ├─ 2. 行頭マーカーを正規表現で判定 → BlockInfo を作成
    │         ├─ 3. inline_scanner.scan(text) → list[InlineSpan]
    │         ├─ 4. setFormat() で装飾を適用
    │         ├─ 5. マーカー範囲に hidden_format を適用
    │         │      （ただしフォーカスブロック かつ リビール条件を満たす範囲は除外）
    │         ├─ 6. setCurrentBlockUserData(BlockData(info, spans))
    │         └─ 7. setCurrentBlockState(次ブロックへ引き継ぐ状態)
    │
    ├──▶ [廃止] block_decorator（ADR-0002 で削除）
    │         ブロックレベルの見た目は painter_overlay の paintEvent が描く
    │
    ├──▶ [デバウンス 400ms] block_parser でダーティ範囲を再解析
    │         → リストの入れ子構造・表の範囲など、1 行では判断できない構造を確定
    │
    └──▶ [デバウンス 800ms] autosave → ファイル書き込み → index_db 更新
```

**ブロック状態（`setCurrentBlockState`）の設計**:

```
0        : 通常
1        : フェンスドコードブロックの内部
2        : YAML front matter の内部
3..8     : 引用の深さ（3 + depth）
9        : 表の内部
```

複数条件が同時に立つ場合（引用の中のコードブロック等）はビットフラグで表現する:

```python
STATE_CODE = 1 << 0
STATE_FRONT = 1 << 1
STATE_TABLE = 1 << 2
QUOTE_SHIFT = 4  # 上位ビットに引用の深さを詰める
```

### 6.4 リビール（マーカーの表示/非表示）のルール

これがこのアプリの体験を決める中核ロジック。**リビール条件を厳密に定義する。**

`MarkdownEditor.cursorPositionChanged` を受け、変化した「旧フォーカスブロック」と「新フォーカスブロック」だけを `rehighlightBlock()` する（全体再ハイライトは絶対にしない。G5 が壊れる）。

`MarkdownHighlighter` は `self._reveal_position: int | None`（ドキュメント全体でのキャレット位置）と `self._has_selection: bool` を保持する。

| 対象 | 隠す条件 | 現す条件 |
|---|---|---|
| **インラインマーカー**（`**`, `*`, `` ` ``, `~~`, `::`） | 常に隠す | キャレットが `[open_start, close_end]` の**閉区間**内にあるとき、その span のマーカーのみ現す（両端を含むので、直後にカーソルを置いた状態で編集できる） |
| **リンク** `[text](url)` | `(url)` 部分と `[` `]` を隠す | キャレットが `[open_start, close_end]` 内にあるとき全体を現す |
| **見出しマーカー** `## ` | 常に隠す | キャレットがその**ブロック内のどこか**にあるとき現す |
| **リストマーカー** `- `, `1. ` | **隠さない**（記号自体が意味を持つ表示要素） | — （`- ` は `•` に置換描画してもよいが v1 では素のまま） |
| **タスクマーカー** `- [ ] ` | `[ ]` を `☐` としてオーバーレイ描画し、原文は極小化 | ブロックにキャレットがあるとき原文を現す |
| **引用マーカー** `> ` | 常に隠す（左の縦バーで表現） | ブロックにキャレットがあるとき現す |
| **コードフェンス** ` ```lang ` | 常に隠す（ブロック背景で表現） | フェンス行またはブロック内にキャレットがあるとき現す |
| **水平線** `---` | 常に隠す（線を描画） | ブロックにキャレットがあるとき現す |
| **タグ** `#tag` | `#` を含めて隠さない（ピル表示の一部） | — |
| **全マーカー** | — | **ソースモード（`Cmd+/`）が ON のときは常に全表示** |
| **全マーカー** | — | **選択範囲が存在するとき、選択範囲に交差するブロックは全表示**（選択→コピーの直前に何をコピーするか見えるようにする） |

**タイミングの段階化（Typora の挙動を踏襲）**:

- **インライン**は入力確定と同時に反映（`highlightBlock` が同期で走るので自然にこうなる）。
- **ブロック**（`## `, `- [ ] `, `> `）は「キャレットがそのブロックを離れた時点」で確定。実装上は、リビール条件が「ブロック内にキャレットがあるか」なので、これは自動的に満たされる。

**リビール時のちらつき対策**: フォントサイズが `0.5pt ↔ 15pt` に切り替わると行が横方向にガクッと動く。これは仕様として許容する（Obsidian / Typora も同じ挙動）。ただし**縦方向は動かしてはいけない**ので、`QTextBlockFormat.setLineHeight(value, QTextBlockFormat.FixedHeight)` で行高を固定すること。

### 6.5 インラインスキャナの仕様

`core/inline_scanner.py` は 1 行の文字列を受け取り `list[InlineSpan]` を返す純関数。

**処理順（重要 — 先に確定したものが優先）**:

1. **インラインコード** `` `...` `` / ` ``...`` ` を最優先で確定。この範囲内では他の記法を一切解釈しない。
2. **自動リンク** `<https://...>` と裸の URL。
3. **画像** `![alt](url)` → その後 **リンク** `[text](url)`（`!` の有無で区別）。
4. **強調**: `***`, `**`, `*`, `___`, `__`, `_` の順（長いデリミタから）。
   - **CJK 対応の必須要件**: CommonMark の `_` は単語内では強調にならない（`snake_case` を守るため）が、`*` は日本語のように前後が空白でなくても強調にする。日本語ユーザーは `**太字**と続けて書く**ため、`*` については left-flanking / right-flanking の空白条件を**緩める**こと。
5. **取り消し線** `~~...~~`。
6. **ハイライト** `::...::`。
7. **タグ** `#([^\s#]+)`。ただし `#` の直前が行頭または空白であること。`#` の直後が空白・`#` の場合は見出しなのでタグにしない。階層は `/` 区切り。

**スキャナの実装方針**: 単一の巨大な正規表現ではなく、**確定済み範囲のマスクを持ちながら段階的にスキャン**する。

```python
def scan(text: str) -> list[InlineSpan]:
    spans: list[InlineSpan] = []
    mask = bytearray(len(text))  # 1 = 確定済み（他の規則は触れない）
    for rule in RULES_IN_PRIORITY_ORDER:
        for m in rule.pattern.finditer(text):
            if any(mask[m.start() : m.end()]):
                continue
            span = rule.build(m)
            spans.append(span)
            mask[span.open_start : span.close_end] = b"\x01" * (span.close_end - span.open_start)
    return sorted(spans, key=lambda s: s.open_start)
```

ネストした強調（`**bold *and italic* here**`）は、マスク方式では内側が拾えない。**v1 は「1 段のネストまで」を許容範囲とし、コード内では `mask` を「排他マスク」と「内容マスク」に分けて、内容領域内での再スキャンを 1 回だけ許す**。完全な再帰は v1.1。

### 6.6 性能設計

| 施策 | 内容 |
|---|---|
| 差分ハイライト | `QSyntaxHighlighter` が変更ブロックのみ呼ぶ。`rehighlight()` は起動時とテーマ変更時のみ |
| リビールの局所化 | `cursorPositionChanged` では**旧/新の 2 ブロックだけ** `rehighlightBlock()` |
| 正規表現のプリコンパイル | モジュールレベルで `re.compile`。ループ内でコンパイルしない |
| ブロックパーサのデバウンス | 400ms。かつ**ダーティ行の前後 ±20 行だけ**を再パース（フェンスの整合のため前方に伸ばす） |
| 巨大ファイルのガード | 2MB / 20,000 行を超えるファイルは装飾を切って警告を出す |
| インデックス更新 | ファイル保存後、**別スレッド**（`QThreadPool` + `QRunnable`）で SQLite を更新 |
| ノートリスト | `QListView` + `QAbstractListModel`（`QListWidget` は使わない）。プレビュー文は先頭 120 文字だけ読む |

**性能受け入れ基準**:

- 10,000 語のノートで、キー入力から画面反映まで **95 パーセンタイル < 16ms**
- 5,000 ノートの vault で、全文検索の応答 **< 200ms**
- 起動からウィンドウ表示まで **< 1.5 秒**（Apple Silicon）

---

## 7. データ設計・ローカル保存

### 7.1 ディレクトリ構成（vault）

ユーザーが「保管フォルダ（vault）」を 1 つ選ぶ。既定は `~/Documents/HitofudeNotes`。

```
HitofudeNotes/
├── 2026-08-07-会議メモ.md          ← ノートは vault 直下のフラット構成
├── 読書メモ.md
├── attachments/                    ← 画像等の添付
│   └── 2026-08-07-screenshot.png
├── .trash/                         ← 削除したノート（30 日後に自動消去）
│   └── 古いメモ.md
└── .hitofude/                          ← アプリの管理領域（ユーザーは触らない）
    ├── index.sqlite                ← 検索インデックス（キャッシュ。消えても再構築可能）
    └── index.sqlite-wal
```

**設計判断**:

- **フォルダ階層で分類しない**。分類はタグで行う（タグベースのノートアプリと同じ方針）。ユーザーが手でサブフォルダを作った場合は再帰的に読み込むが、アプリからは作らせない。
- **`.hitofude/index.sqlite` は完全なキャッシュ**。削除しても `.md` から全再構築できること。真実は常にファイル側にある。これが G3 の担保。
- ファイル名は `sanitize(タイトル) + .md`。重複時は `-2`, `-3` を付与。タイトル変更時はファイルをリネームする（旧名は `.trash` に残さない）。UI の「名前を変更」がどちらを変えるかは **ADR-0005 で補足**。

### 7.2 ノートファイルの形式

```markdown
---
id: 01J9XQ2F8K7M3N5P
created: 2026-08-07T09:12:00+09:00
modified: 2026-08-07T14:33:12+09:00
pinned: false
---

# 会議メモ

今日の論点は **3 つ**。

- [ ] 予算確認
- [x] 資料共有

#work/会議
```

| 項目 | 仕様 |
|---|---|
| Front matter | **YAML、任意**。無くても正常に開ける。`---` で始まり `---` で終わる |
| `id` | ULID。ファイル名変更に耐える永続 ID。ノート間リンク `[[title]]` の解決に使う（v1.1） |
| `created` / `modified` | ISO 8601（タイムゾーン付き）。`modified` は保存時に更新 |
| タイトル | **最初の H1 → 無ければ最初の非空行 → 無ければファイル名** の順で決定 |
| タグ | 本文中の `#tag` を全走査して抽出。front matter には**書かない**（本文が真実） |
| 改行コード | LF 固定。読み込み時に CRLF は正規化 |
| エンコーディング | UTF-8（BOM なし）。読み込み時のみ BOM 付きを許容 |

**front matter を隠すか**: 既定で**折りたたみ表示**（`▸ メタデータ` の 1 行に潰す）。`Cmd+/` のソースモードで展開。実装は「front matter 範囲のブロックに極小フォントを適用 + 最初の行にオーバーレイ描画」。

### 7.3 SQLite インデックス

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,      -- ULID
    path         TEXT NOT NULL UNIQUE,  -- vault からの相対パス
    title        TEXT NOT NULL,
    preview      TEXT NOT NULL,         -- 本文先頭 200 文字（front matter/H1 を除く）
    created_at   TEXT NOT NULL,
    modified_at  TEXT NOT NULL,
    mtime_ns     INTEGER NOT NULL,      -- os.stat の st_mtime_ns。差分同期用
    size_bytes   INTEGER NOT NULL,
    pinned       INTEGER NOT NULL DEFAULT 0,
    trashed      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notes_modified ON notes(modified_at DESC);

CREATE TABLE IF NOT EXISTS tags (
    note_id  TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,             -- 正規化済み小文字フルパス 'work/会議'
    PRIMARY KEY (note_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

-- 全文検索。日本語のため trigram を使う（unicode61 では日本語が 1 トークンになり検索不能）
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    body,
    note_id UNINDEXED,
    tokenize = 'trigram'
);
```

**日本語検索の設計（重要）**:

- SQLite 3.34+ の **`tokenize='trigram'`** を使う。3 文字ずつの重なりウィンドウで索引するため、日本語の部分一致が形態素解析なしで動く。macOS の Python 同梱 SQLite は 3.43+ なので利用可。
- **`trigram` の制約: 2 文字以下のクエリはヒットしない**（「人事」「経費」等）。
  → **対策**: クエリ長が 3 未満、または CJK を含む短いクエリのときは FTS を使わず `notes.title/preview` への `LIKE '%q%'` にフォールバックする。ハイブリッド戦略を `index_db.search()` の内部で自動切替する。
- 英数字は trigram でも動くが、単語境界を無視するので精度が落ちる。**英数字のみのクエリは `unicode61` の第 2 インデックスに回す**構成も可（v1.1。v1 は trigram 単独 + LIKE フォールバックで十分）。

**起動時の同期処理**:

```
1. vault を os.scandir で走査（*.md）
2. DB の (path, mtime_ns, size_bytes) と突き合わせ
3. 差分（新規 / 更新 / 消失）だけを再インデックス
4. 走査は QThreadPool。UI はその間も「前回のリスト」を表示して操作可能に
```

### 7.4 自動保存とアトミック書き込み

```python
# storage/autosave.py
def save_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())  # ← 電源断でも中途半端なファイルを残さない
    os.replace(tmp, path)  # ← 同一ボリューム内なら atomic
```

**保存トリガ**:

| 契機 | 遅延 |
|---|---|
| テキスト変更 | 800ms のデバウンス |
| ノート切り替え | 即時（切り替え前にフラッシュ） |
| ウィンドウのフォーカス喪失 | 即時 |
| `Cmd+S` | 即時 |
| アプリ終了 | 即時（`QApplication.aboutToQuit`） |

### 7.5 外部変更の検知と競合解決

`watchdog` で vault を監視。自分で書いた直後のイベントは**無視リスト**（保存直後 1.5 秒間、そのパスを抑制）で除外する。

| 状況 | 挙動 |
|---|---|
| 開いていないノートが外部で変更 | 静かに再インデックス |
| 開いているノートが外部で変更、**アプリ側は未編集** | 静かにリロードしてキャレット位置を復元 |
| 開いているノートが外部で変更、**アプリ側も編集中** | **競合ダイアログ**を出す:「外部の変更を採用 / 自分の版を採用 / 両方残す（`ファイル名 (競合 2026-08-07).md` を作成）」 |
| 開いているノートが外部で削除 | 「ファイルが削除されました。再作成しますか？」 |

**競合検知の実装**: 読み込み時の `mtime_ns` と `hashlib.blake2b(content)` を `Note` に保持し、保存直前に再検査する（TOCTOU を完全には防げないが実用上十分）。

### 7.6 ゴミ箱

- 削除は `.trash/` への移動（`os.replace`）。ファイル名衝突時はタイムスタンプを付与。
- `.trash/` 内のノートは検索対象外（`notes.trashed = 1`）。
- 起動時に 30 日以上経過したものを削除。日数は設定可能。
- `Cmd+Shift+Delete` で完全削除（確認ダイアログ必須）。

---

## 8. macOS 向け配布

### 8.1 ビルド

**py2app を主とする**。PyInstaller には PySide6 の `--onedir` ビルドで **QtNetwork / QtSvg フレームワークの署名が不正になり公証（notarization）に失敗する既知の不具合**がある。py2app は macOS 専用ゆえに Framework バンドルの構造を正しく扱いやすい。

`setup.py`:

```python
from setuptools import setup

APP = ["hitofude/__main__.py"]
OPTIONS = {
    "argv_emulation": False,  # True にすると Carbon 依存で Apple Silicon で問題が出る
    "iconfile": "resources/Hitofude.icns",
    "packages": ["PySide6", "markdown_it", "yaml", "watchdog"],
    "includes": ["sqlite3"],
    "excludes": [  # バンドルサイズ削減。PySide6 は巨大なので必須
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3D*",
        "PySide6.QtQuick*",
        "PySide6.QtCharts",
        "PySide6.QtMultimedia*",
        "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "tkinter",
        "test",
        "unittest",
    ],
    "plist": {
        "CFBundleName": "Hitofude",
        "CFBundleIdentifier": "app.hitofude.editor",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Markdown Document",
                "CFBundleTypeExtensions": ["md", "markdown"],
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
            }
        ],
    },
}

setup(app=APP, options={"py2app": OPTIONS}, setup_requires=["py2app"])
```

`pyside6-deploy`（Nuitka ベース）も選択肢だが、公証まで含めた実績は py2app のほうが厚い。**v1 は py2app、うまくいかなければ PyInstaller `--onedir` + 手動で個別フレームワーク再署名**、の順で試す。

### 8.2 署名と公証

`entitlements.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
  <key>com.apple.security.files.user-selected.read-write</key><true/>
</dict></plist>
```

> `allow-unsigned-executable-memory` と `disable-library-validation` は CPython が動的にライブラリをロードするため事実上必須。

手順:

```bash
# 1. 内部のバイナリを個別に署名（--deep は信頼できないので、内側から順に明示的に署名する）
find dist/Hitofude.app -name "*.so" -o -name "*.dylib" | while read f; do
  codesign --force --timestamp --options=runtime \
    --sign "Developer ID Application: NAME (TEAMID)" "$f"
done

# 2. Qt フレームワークを個別署名
for fw in dist/Hitofude.app/Contents/Resources/lib/python3.12/PySide6/Qt/lib/*.framework; do
  codesign --force --timestamp --options=runtime \
    --sign "Developer ID Application: NAME (TEAMID)" "$fw"
done

# 3. アプリ本体
codesign --force --timestamp --options=runtime \
  --entitlements entitlements.plist \
  --sign "Developer ID Application: NAME (TEAMID)" dist/Hitofude.app

# 4. 検証
codesign --verify --deep --strict --verbose=2 dist/Hitofude.app
spctl -a -vvv -t install dist/Hitofude.app

# 5. 公証
ditto -c -k --keepParent dist/Hitofude.app Hitofude.zip
xcrun notarytool submit Hitofude.zip --keychain-profile "AC_PASSWORD" --wait
xcrun stapler staple dist/Hitofude.app
```

**ハマりどころ**: 署名は**必ず内側（.so / .dylib / .framework）から外側（.app）へ**の順で行う。`--deep` を使うと entitlements が正しく伝播せず公証で弾かれる。また、一度署名したアプリを再署名するとエラーになることがあるため、ビルドは常にクリーンな `dist/` から行う。

### 8.3 DMG 作成

```bash
create-dmg --volname "Hitofude" --window-size 600 400 \
  --icon "Hitofude.app" 150 180 --app-drop-link 450 180 \
  Hitofude-1.0.0.dmg dist/Hitofude.app
```

DMG 自体も署名 + 公証すること。

### 8.4 サンドボックス

**v1 は非サンドボックス（Developer ID 配布）**。App Store 配布を目指す場合のみサンドボックスを有効にし、vault フォルダへのアクセスは**セキュリティスコープ付きブックマーク**が必要になる。これは PySide6 からは直接扱えず `pyobjc` 経由の実装が必要になるため、v1 のスコープ外とする。

---

## 9. 開発ロードマップ（実装タスク分解）

各フェーズは**単独で動作確認できる**単位に切ってある。Claude Code に渡す場合は 1 フェーズずつ指示する。

### Phase 0: 足場（0.5 日）

- [ ] `pyproject.toml`（uv または Poetry）、`ruff` 設定、`.gitignore`
- [ ] `hitofude/__main__.py` で空の `QMainWindow` が起動する
- [ ] `pytest` + `pytest-qt` がオフスクリーン（`QT_QPA_PLATFORM=offscreen`）で通る
- **完了条件**: `python -m hitofude` でウィンドウが出る。`pytest` が緑

### Phase 1: コア層（GUI なし）（2 日）

- [ ] `core/models.py`: `BlockInfo`, `InlineSpan`, `BlockType`, `SpanType`
- [ ] `core/frontmatter.py`: `split(text) -> (dict, body, body_offset)` / `join(meta, body)`
- [ ] `core/inline_scanner.py`: §6.5 のマスク方式スキャナ
- [ ] `core/block_parser.py`: markdown-it-py で `list[BlockInfo]`（行番号付き）
- [ ] `core/tags.py`: `#tag` 抽出、階層分解、正規化
- [ ] **テスト**: 各モジュールに 20 件以上のケース。特に:
  - 日本語での `**強調**`（前後が空白でない）
  - コードブロック内の `**` が強調にならないこと
  - `# 見出し` と `#タグ` の区別
  - front matter の有無・不正 YAML の両方
- **完了条件**: `core/` のカバレッジ 90% 以上。GUI 一切なしで通る

### Phase 2: エディタの装飾（3 日） ← **山場**

- [ ] `editor/highlighter.py`: `MarkdownHighlighter(QSyntaxHighlighter)`
  - [ ] ブロック状態（§6.3 のビットフラグ）でコードフェンス / front matter を追跡
  - [ ] 行頭マーカー判定 → `BlockInfo`
  - [ ] `inline_scanner` 呼び出し → `setFormat()`
  - [ ] `BlockData(QTextBlockUserData)` に格納
- [ ] マーカー隠蔽: `setFontPointSize(0.5)` 方式（§3.3 の検証結果に従う）
- [ ] `editor/editor_widget.py`: `MarkdownEditor(QPlainTextEdit)`
  - [ ] `cursorPositionChanged` → 旧/新ブロックのみ `rehighlightBlock()`
  - [ ] `_reveal_position` をハイライタに渡す
- [x] ~~`editor/block_decorator.py`~~ **ADR-0002 で削除**（ブロック書式は使わない）
- [ ] `editor/painter_overlay.py`: `paintEvent` で引用の縦バー、コードブロック背景、水平線、チェックボックス
- [ ] `theme.py`: ライト/ダーク
- **完了条件**:
  - 日本語で `**太字**` と打つと確定と同時に太字になり `**` が消える
  - カーソルを太字の中に入れると `**` が現れる
  - コードブロックの中では装飾が一切効かない
  - `Cmd+Z` を 1 回押すと**装飾処理ではなく直前の入力**が戻る（＝ Undo 汚染がない）
  - 10,000 語のファイルでカーソル移動が引っかからない

### Phase 3: 入力補助（1.5 日）

- [ ] `editor/input_handler.py`: リスト継続、空項目解除、引用継続、Tab インデント
- [ ] `editor/commands.py`: `Cmd+B/I/E/K` などのトグル（既に囲まれていれば外す、を必ず実装）
- [ ] **IME ガード**: 変換中は Enter/Tab の特殊処理を全て無効化
- **完了条件**: 「あいうえお」を変換中に Enter を押してもリストが増えない。`- ` で Enter を 2 回押すと段落に戻る

### Phase 4: ファイル層（2 日）

- [ ] `storage/vault.py`: 走査、CRUD、`.trash` への移動、ファイル名 sanitize
- [ ] `storage/autosave.py`: デバウンス + `save_atomic`
- [ ] `storage/index_db.py`: §7.3 のスキーマ、`upsert_note()`、`search()`（trigram + LIKE フォールバック）、`tag_tree()`
- [ ] `storage/watcher.py`: watchdog → Qt シグナル。自己書き込みの抑制リスト
- [ ] 競合ダイアログ（§7.5）
- **完了条件**:
  - vault を指定 → 既存 `.md` が一覧に出る
  - 編集 → 800ms 後にファイルが更新される
  - 外部エディタで書き換える → アプリに反映される
  - `.hitofude/index.sqlite` を消して再起動 → 完全に復元される

### Phase 5: アプリ UI（2.5 日）

- [ ] `ui/main_window.py`: 3 ペイン `QSplitter`、幅の永続化、メニューバー
- [ ] `ui/note_list.py`: `QAbstractListModel` + カスタム `QStyledItemDelegate`（タイトル / 日付 / プレビュー 2 行）
- [ ] `ui/sidebar.py`: タグツリー（`QTreeView`）、すべて / お気に入り / ゴミ箱
- [ ] `ui/quick_open.py`: `Cmd+O` のファジー検索パレット
- [ ] `ui/preferences.py`: フォント、テーマ、vault 変更、ゴミ箱保持日数
- [ ] `Cmd+Shift+F` の全文検索（結果にスニペット + ハイライト）
- **完了条件**: 5,000 件のダミーノートを生成して、リストのスクロールが滑らか、検索が 200ms 以内

### Phase 6: 仕上げと配布（2 日）

- [ ] ソースモード（`Cmd+/`）、フォーカスモード、タイプライタモード
- [ ] `Cmd+Shift+C`（プレーンテキストコピー）
- [x] HTML / PDF エクスポート（~~ここでのみ `QTextDocument.setMarkdown()` を使ってよい~~ → **ADR-0007 で markdown-it-py へ移行**。`QPrinter` で PDF 出力）
- [ ] アプリアイコン（`.icns`）、About ダイアログ
- [ ] `setup.py`（py2app）でビルド → 署名 → 公証 → DMG
- [ ] クラッシュ時のリカバリ（未保存バッファを `~/Library/Application Support/Hitofude/recovery/` に退避）
- **完了条件**: 署名済み DMG を別の Mac にコピーして、Gatekeeper の警告なしに起動する

**合計目安: 13.5 人日**

---

## 10. テスト計画

| 種別 | 対象 | 方法 |
|---|---|---|
| 単体 | `core/` 全モジュール | `pytest`。GUI 不要 |
| 単体 | `storage/` | `tmp_path` フィクスチャで実ファイル操作 |
| ウィジェット | `editor/`, `ui/` | `pytest-qt`（`qtbot.keyClicks` で入力を再現）。`QT_QPA_PLATFORM=offscreen` |
| ゴールデン | ハイライト結果 | サンプル `.md` に対する `(position, length, format名)` のリストを JSON でスナップショット比較 |
| 性能 | 入力遅延 | 10,000 語のファイルで `qtbot` から 1,000 回キー入力し、`highlightBlock` の実行時間分布を計測 |
| 手動 | IME | 日本語・中国語入力で全キーバインドを通す（自動化困難なのでチェックリスト化） |
| 手動 | 配布 | クリーンな macOS VM で DMG からインストール → 起動 |

**回帰テスト用のサンプル文書**を `tests/fixtures/` に必ず用意する:

- `basic.md`（全記法を 1 つずつ）
- `japanese.md`（日本語での強調、タグ、句読点隣接）
- `edge_cases.md`（未閉じの `**`、ネストした強調、コード内の記法、連続フェンス）
- `large.md`（10,000 語、性能計測用）

---

## 11. 既知のリスクと対策

| # | リスク | 影響 | 対策 |
|---|---|---|---|
| R1 | **マーカーを 0.5pt にしても完全には消えない**（1 文字約 0.5px の残滓） | 見た目の粗 | 実用上は視認不能と判断済み。どうしても気になる場合は `QAbstractTextDocumentLayout` の自作が必要だが**費用対効果は極めて悪い**ので推奨しない |
| R2 | **IME 変換中の再ハイライトで変換候補が消える** | 日本語が使えない致命傷 | Phase 2 の時点で日本語入力の実機確認を必ず行う。プリエディット中は `highlightBlock` の重い処理をスキップする逃げ道を用意 |
| R3 | **`QTextBlockFormat` 適用が Undo を汚染** | `Cmd+Z` が効かない | §3.3 の対策を必ず実装。Phase 2 の完了条件に含めてある |
| R4 | 日本語の `**強調**` が CommonMark の flanking 規則で効かない | 主要機能が動かない | `inline_scanner` で `*` の flanking 条件を緩める。`_` は緩めない（`snake_case` を守る） |
| R5 | `trigram` で 2 文字の日本語が検索できない | 検索が使い物にならない | `LIKE` フォールバックを `index_db.search()` に内蔵（§7.3） |
| R6 | py2app で公証に失敗する | 配布できない | Phase 0 の時点で**最小構成のアプリで署名・公証を 1 度通しておく**。最後にまとめてやると詰む |
| R7 | 巨大ファイルで固まる | UX 崩壊 | 2MB 超は装飾を無効化して警告（§6.6） |
| R8 | ネストした強調が拾えない | 軽微 | v1 は 1 段まで。制限として文書化 |
| R9 | `QSyntaxHighlighter` は行またぎの構造（表・入れ子リスト）を単独で判断できない | 表の装飾がずれる | ブロック状態のビットフラグ + デバウンスした `block_parser` の結果を併用（§6.3） |

---

## 12. 参考にすべき実装

| プロジェクト | 言語 | 見るべき点 |
|---|---|---|
| **ghostwriter** | C++/Qt | `MarkdownHighlighter` の実装。同じ Qt でのマーカー処理の実例 |
| **QOwnNotes** | C++/Qt | Qt での Markdown ハイライタとして最も成熟。ブロック状態の設計が参考になる |
| **MarkdownHighlighter (rupeshk)** | **Python/Qt** | `QSyntaxHighlighter` サブクラスの Python 実装。出発点として読む価値がある |
| **Obsidian Live Preview** | TS | リビール条件の UX 設計（何をいつ隠すか）の事実上の標準 |
| **Typora** | TS | インライン即時 / ブロック遅延の 2 段階反映 |

---

## Sources

- [Typora Markdown Reference | Markdown Guide](https://www.markdownguide.org/tools/typora/)
- [Quick Start - Typora Support](https://support.typora.io/Quick-Start/)
- [QTextDocument Class | Qt GUI](https://doc.qt.io/qt-6/qtextdocument.html)
- [QSyntaxHighlighter Class | Qt GUI](https://doc.qt.io/qt-6/qsyntaxhighlighter.html)
- [PySide6 QTextEdit - Qt for Python](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTextEdit.html)
- [Year of the Snake: Qt for Python 6.9 is out!](https://www.qt.io/blog/qt-for-python-release-6.9)
- [Using markdown_it — markdown-it-py](https://markdown-it-py.readthedocs.io/en/latest/using.html)
- [markdown_it.token module — markdown-it-py](https://markdown-it-py.readthedocs.io/en/latest/api/markdown_it.token.html)
- [SQLite FTS5 Extension](https://www.sqlite.org/fts5.html)
- [Full-text CJK Search with SQLite FTS5: Trigram Tokenizer and Hybrid Strategy](https://zenn.dev/kanseilink/articles/kanseilink-fts5-trigram-cjk-20260507)
- [How to Package PySide6 Apps for macOS with PyInstaller (.app & .dmg)](https://www.pythonguis.com/tutorials/packaging-pyside6-applications-pyinstaller-macos-dmg/)
- [Unable to Notarize PySide6 App for MacOS using PyInstaller --onedir · pyinstaller#8927](https://github.com/pyinstaller/pyinstaller/issues/8927)
- [MarkdownHighlighter (Python/Qt)](https://github.com/rupeshk/MarkdownHighlighter)
- [CuteMarkEd — Qt Markdown Editor](https://github.com/cloose/CuteMarkEd)
