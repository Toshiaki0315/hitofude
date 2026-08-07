# CLAUDE.md — Hitofude 開発ガイド

ライブプレビュー型 Markdown エディタ **Hitofude**（macOS 13+ / Python 3.12+ / PySide6）。

このファイルは Claude Code がセッション開始時に必ず読む作業規約。
**設計の根拠と詳細仕様は [docs/spec.md](docs/spec.md) にある**（節番号は仕様書のもの）。
実装タスクの一覧と進捗は [docs/TASKS.md](docs/TASKS.md)。

---

## 1. 開発プロセス（TDD 必須）

**このプロジェクトはテスト駆動開発で進める。例外はない。**

各タスクは必ず以下のサイクルで進める:

1. **RED** — 先にテストを書く。実行して**失敗することを確認する**（失敗しないテストは仕様を検証していない）
2. **GREEN** — テストを通す最小限の実装を書く
3. **REFACTOR** — テストが緑のまま整理する
4. **VERIFY** — `make check`（= ruff + pytest 全件）が緑
5. **COMMIT** — ここで初めてコミットする

### コミット前チェックリスト（絶対）

```bash
make check
```

- [ ] `ruff check` / `ruff format --check` が緑
- [ ] `pytest` が**全件**緑（新規テストだけでなく全体）
- [ ] `core/` を触ったならカバレッジ 90% 以上（`make cov`）
- [ ] 実装だけ、またはテストだけのコミットになっていない（機能追加はテストと同じコミットに入れる）

**テストが赤い状態でコミットしてはいけない。** 落ちるテストを一時的に `skip` して回避するのも禁止。
どうしても行き詰まったら、コミットせずに状況を報告すること。

### テストの書き方

- 1 テスト = 1 振る舞い。テスト名は `test_<対象>_<条件>_<期待>` の形で日本語混じり可
  例: `test_scan_日本語の強調は前後が空白でなくても検出する`
- パラメータ化できるケースは `@pytest.mark.parametrize` でまとめる
- **バグを直すときは、先にそのバグを再現する回帰テストを書く**
- GUI テストは `pytest-qt` の `qtbot` を使い、`@pytest.mark.gui` を付ける
- `QT_QPA_PLATFORM=offscreen` はテスト側で自動設定される（`tests/conftest.py`）
- **`qtbot.keyClicks()` に日本語を渡さない。** Qt の `qasciikey.cpp` が assert で
  abort し、pytest ごと落ちる（エラーではなくプロセス強制終了なので原因が分かりにくい）。
  日本語は `cursor.insertText()` で入れる。IME の確定もこの経路になる。
  裏を返すと**打鍵レベルの日本語入力は自動テストで再現できない**ので、
  IME 周りは手動チェックリストで担保する（§10）

---

## 2. コマンド

セットアップ（初回のみ）:

```bash
make setup
```

日常操作:

| 目的 | コマンド |
|---|---|
| アプリ起動 | `make run`（= `uv run python -m hitofude`） |
| テスト全件 | `make test` |
| テスト（GUI 除く／速い） | `make test-fast` |
| カバレッジ | `make cov` |
| Lint + Format 修正 | `make fmt` |
| Lint + テスト（コミット前） | `make check` |
| 依存追加 | `uv add <pkg>` / `uv add --dev <pkg>` |

素の `python` / `pip` は使わない。**必ず `uv run` 経由**で実行する。

---

## 3. アーキテクチャの不可侵ルール

以下は仕様書で技術検証済みの結論。**破ると設計が崩壊する**ので、変更したくなったら実装前に必ず相談すること。

### R1. ソース文字列が唯一の真実（§3.1）

`QPlainTextEdit.toPlainText()` がそのまま保存内容。往復変換を挟まない。

### R2. `QTextDocument.setMarkdown()` / `toMarkdown()` を編集モデルに使わない（§3.3）

実機検証でコードフェンス消失・表崩壊・`#tag` のエスケープが確認済み。
**使ってよいのは HTML/PDF エクスポート（Phase 6）だけ。**

### R3. `core/` と `storage/` は PySide6 に依存しない（§6.1）

パーサと保存ロジックをヘッドレスでテストするため。
唯一の例外は `storage/watcher.py` の Qt シグナル橋渡し部分。
この規約は `tests/test_architecture.py` で自動検査している。

### R4. マーカーの隠蔽は `setFontPointSize(0.5)`（§3.3）

文字を削除・置換しない。文字が実在し続けることで
`QTextCursor` の位置とソース文字列のオフセットが常に 1:1 で一致する。
位置マッピングテーブルを導入してはならない。

### R5. `QTextBlockFormat` を使わない（ADR-0002）

ブロックの余白・インデント・行高を設定してはいけない。理由は 2 つとも実測済み。

1. `QPlainTextDocumentLayout` は**ブロック書式を完全に無視する**（効果がゼロ）
2. 適用すると Undo スタックを 1 段消費する。仕様書 §3.3 が挙げていた
   `setUndoRedoEnabled(False)` で挟む対処は、**Undo 履歴ごと消す**ので使えない

ブロックレベルの見た目（引用の縦バー、コードブロック背景、水平線、
チェックボックス）は `editor/painter_overlay.py` の `paintEvent` で描く。

`Cmd+Z` が 1 回で直前の入力に戻ることは、Phase 2 の完了条件であり回帰テストがある。

### R6. IME ガード（§5.5, R2）

日本語変換中（プリエディット中）は Enter/Tab の特殊処理を**すべて無効化**する。
入力補助を追加するときは必ず IME 中のテストを一緒に書く。

### R7. 全体再ハイライトの禁止（§6.4, §6.6）

`rehighlight()` は起動時とテーマ変更時のみ。
カーソル移動では**旧/新の 2 ブロックだけ** `rehighlightBlock()` する。

### R8. インライン解析は自作スキャナ、ブロック解析は markdown-it-py（§3.4）

markdown-it のインライントークンは `map=None` で文字オフセットを持たないため、
`highlightBlock()` からは使えない。この分担は妥協ではなく必然。

### R9. `.hitofude/index.sqlite` は捨ててよいキャッシュ（§7.1）

削除しても `.md` から完全再構築できること。真実は常にファイル側にある。

---

## 4. ディレクトリ構成

```
hitofude/
├── CLAUDE.md                 # このファイル
├── README.md
├── Makefile                  # 開発コマンドの入口
├── pyproject.toml            # 依存・ruff・pytest 設定
├── docs/
│   ├── spec.md               # 仕様書（設計判断の根拠。真実はこちら）
│   ├── TASKS.md              # 実装タスクと進捗
│   └── adr/                  # 仕様書の決定を覆すときだけ追加する記録
├── hitofude/
│   ├── __main__.py           # エントリポイント
│   ├── app.py                # QApplication セットアップ、テーマ
│   ├── config.py             # QSettings ラッパ
│   ├── theme.py              # ThemeColors dataclass
│   ├── core/                 # GUI 非依存（純ロジック / 完全にテスト可能）
│   ├── storage/              # 永続化（vault, SQLite FTS5, watchdog, autosave）
│   ├── editor/               # エディタウィジェット層
│   ├── ui/                   # アプリケーション UI 層
│   └── resources/
├── tests/
│   ├── conftest.py           # offscreen 設定、共通フィクスチャ
│   ├── test_architecture.py  # R3 の自動検査
│   ├── core/ storage/ editor/ ui/
│   └── fixtures/             # basic.md, japanese.md, edge_cases.md, large.md
└── scripts/                  # 開発補助（ダミー vault 生成など）
```

各モジュールの責務は仕様書 §6.1 の表に従う。**勝手に階層を増やさない。**

---

## 5. コーディング規約

- Python 3.12+ の記法を使う（`match`、`X | None`、`type` 文）
- 型ヒントは公開関数・メソッドに必須。`from __future__ import annotations` は不要（3.12+）
- `dataclass` を優先。可変状態は最小限に
- **`core/` の関数は原則として純関数**（副作用なし・グローバル状態なし）
- 正規表現はモジュールレベルで `re.compile`（ループ内でコンパイルしない、§6.6）
- パス操作は `pathlib.Path`（`os.path` は使わない）
- コメントは「なぜ」を書く。「何を」はコードで表現する
- ログは `logging`（`print` はスクリプト以外で使わない）

---

## 6. コミット規約

Conventional Commits + 日本語本文。

```
feat(core): インラインスキャナで強調とコードを検出

日本語の **強調** が CommonMark の flanking 規則で効かない問題に対応し、
`*` のみ前後空白条件を緩めた（spec §6.5, R4）。`_` は snake_case を守るため緩めない。

テスト: tests/core/test_inline_scanner.py（32 ケース）
```

- type: `feat` / `fix` / `test` / `refactor` / `docs` / `chore` / `perf` / `build`
- scope: `core` / `storage` / `editor` / `ui` / `build` / `docs`
- 1 コミット = 1 つの意味のある変更。テストと実装は同じコミットに含める
- **コミットは明示的に指示されたとき、または上記チェックリストが全て緑のときだけ行う**

---

## 7. パフォーマンス受け入れ基準（§6.6）

新機能を入れるたびに劣化していないか意識する。

| 指標 | 基準 |
|---|---|
| キー入力 → 画面反映 | 95 パーセンタイル < 16ms（10,000 語のノート） |
| 全文検索 | < 200ms（5,000 ノートの vault） |
| 起動 → ウィンドウ表示 | < 1.5 秒（Apple Silicon） |

---

## 8. 作業の進め方

- **仕様書 §9 のフェーズ単位で進める。** 複数フェーズを同時に触らない
- タスクに着手したら [docs/TASKS.md](docs/TASKS.md) のチェックボックスを更新する
- 仕様書と実装が食い違ったら、**まず仕様書が正しいと考える**。仕様書のほうを変えるべきだと判断したら、
  実装する前に理由を述べて確認を取り、`docs/adr/` に記録を残す
- 検証していない性能・挙動を「できました」と報告しない。実測値かテスト結果を添える
