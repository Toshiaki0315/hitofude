# 実装タスク一覧

仕様書 [spec.md](spec.md) §9 のロードマップを、**TDD で回せる粒度**まで分解したもの。
着手時に `[ ]` → `[~]`（作業中）→ `[x]`（完了）に更新する。

**進め方のルール**
- 1 タスク = 1 コミット（テスト + 実装）を基本とする
- 各タスクは「テスト」欄に書かれたテストを**先に**書いてから実装する
- フェーズの「完了条件」を満たすまで次のフェーズに進まない

凡例: `[ ]` 未着手 / `[~]` 作業中 / `[x]` 完了

---

## Phase 0: 開発環境の構築と足場（目安 0.5 日）

**ゴール**: `make run` でウィンドウが出て、`make check` が緑になる状態。

### 0-A. リポジトリと開発環境

| | タスク | 成果物 | テスト |
|---|---|---|---|
| [x] | 0-A-1 | git リポジトリ初期化、`.gitignore` | — |
| [x] | 0-A-2 | ディレクトリ骨格の作成（CLAUDE.md §4 の構成） | — |
| [x] | 0-A-3 | `pyproject.toml`（依存・ruff・pytest 設定） | — |
| [x] | 0-A-4 | `CLAUDE.md` / `README.md` / 本タスク表 | — |
| [x] | 0-A-5 | `Makefile`（setup / run / test / cov / fmt / check） | — |
| [x] | 0-A-6 | `uv sync` で仮想環境構築、PySide6 の import 確認 | `tests/test_environment.py` |
| [x] | 0-A-7 | `tests/conftest.py`（`QT_QPA_PLATFORM=offscreen` 強制） | 自身が全 GUI テストの前提 |
| [x] | 0-A-8 | CI ワークフロー（macOS runner で ruff + pytest） | — |

### 0-B. アプリの最小骨格

| | タスク | 成果物 | テスト |
|---|---|---|---|
| [x] | 0-B-1 | `hitofude/theme.py`: `ThemeColors` dataclass（ライト/ダーク定義のみ） | `tests/test_theme.py` |
| [x] | 0-B-2 | `hitofude/app.py`: `create_application()`（QApplication 生成、テーマ適用） | `tests/test_app.py` (gui) |
| [x] | 0-B-3 | `hitofude/ui/main_window.py`: 空の `MainWindow(QMainWindow)` | `tests/ui/test_main_window.py` (gui) |
| [x] | 0-B-4 | `hitofude/__main__.py`: `main()` エントリポイント | `tests/test_entrypoint.py` |
| [x] | 0-B-5 | `tests/test_architecture.py`: R3（core/storage が PySide6 非依存）の自動検査 | 自身がテスト |

### 0-C. リスク先出し（仕様書 §11 R6 対策）

| | タスク | 備考 |
|---|---|---|
| [ ] | 0-C-1 | 最小構成の `.app` を py2app でビルドできることを確認 | 署名・公証は 0-C-2 |
| [ ] | 0-C-2 | **最小アプリで一度だけ署名 → 公証を通しておく** | Apple Developer ID が必要。最後にまとめてやると詰む（R6） |

> 0-C は Apple Developer アカウントが要るため、取得済みになった時点で着手する。
> Phase 1 以降のブロッカーではない。

**Phase 0 完了条件**
- [x] `make run` で空のウィンドウが表示される
- [x] `make check`（ruff + pytest）が緑
- [ ] 0-C-2 が通っている（アカウント取得後）

---

## Phase 1: コア層（GUI なし）（目安 2 日）

**ゴール**: `hitofude/core/` のカバレッジ 90% 以上。PySide6 を一切 import せずに全テストが通る。

| | タスク | テストの主眼（spec §9 Phase 1 より） |
|---|---|---|
| [x] | 1-1 | `core/models.py`: `BlockType`, `SpanType`, `BlockInfo`, `InlineSpan`（§6.2） | dataclass の不変条件（`[start, end)` の半開区間） |
| [x] | 1-2 | `core/frontmatter.py`: `split(text) -> (dict, body, body_offset)` / `join()` | front matter 無し / 不正 YAML / `---` が本文中にある / CRLF |
| [x] | 1-3 | `core/tags.py`: `#tag` 抽出、階層分解、正規化 | `# 見出し` と `#タグ` の区別、`#親/子`、行中のタグ、`#` 直後が空白 |
| [x] | 1-4 | `core/inline_scanner.py` — インラインコード優先の骨格（§6.5 のマスク方式） | コード内の `**` が強調にならない |
| [x] | 1-5 | `inline_scanner`: リンク / 画像 / 自動リンク | `![alt](url)` と `[text](url)` の区別、URL 内の `*` |
| [x] | 1-6 | `inline_scanner`: 強調 `***`/`**`/`*`/`___`/`__`/`_` | **日本語で前後が空白でない `**強調**`（R4）**、`snake_case` が壊れない |
| [x] | 1-7 | `inline_scanner`: 取り消し線 `~~` / ハイライト `::` / タグ | 未閉じマーカー、連続マーカー |
| [x] | 1-8 | `inline_scanner`: 入れ子の強調（`**bold *em* here**`）(§6.5) | マーカーのみをマスクする設計で入れ子が構造的に成立する。段数制限は設けない |
| [x] | 1-9 | `core/block_parser.py`: markdown-it-py → `list[BlockInfo]`（行番号付き） | 見出し / リストの入れ子 / コードフェンス範囲 / 引用の深さ / 表の範囲 |
| [x] | 1-10 | `tests/fixtures/` 一式（`basic.md` / `japanese.md` / `edge_cases.md` / `large.md`）（§10） | 回帰テストの土台 |

**完了条件**: `make cov` で `hitofude/core/` が 90% 以上。`tests/test_architecture.py` が緑。

**結果**: カバレッジ 98%（基準 90%）、テスト 244 件全て緑。ADR-0001 を 1 件追加。

---

## Phase 2: エディタの装飾（目安 3 日） ← **山場**

**ゴール**: 日本語で `**太字**` を打つと確定と同時に太字になり `**` が消える。

| | タスク | 参照 |
|---|---|---|
| [x] | 2-1 | `editor/highlighter.py`: ブロック状態のビットフラグ（コードフェンス / front matter / 表 / 引用深さ） | §6.3 |
| [x] | 2-2 | 行頭マーカー判定 → `BlockInfo` 生成、`BlockData(QTextBlockUserData)` に格納 | §6.2 |
| [x] | 2-3 | `inline_scanner` の結果を `setFormat()` で適用 | §6.3 |
| [x] | 2-4 | マーカー隠蔽 `setFontPointSize(0.5)` | §3.3 / R4 |
| [x] | 2-5 | `editor/editor_widget.py`: `MarkdownEditor(QPlainTextEdit)` の骨格 | §4.1 |
| [x] | 2-6 | リビール: `cursorPositionChanged` → 旧/新 2 ブロックのみ `rehighlightBlock()` | §6.4 / R7 |
| [x] | 2-7 | リビール条件表の実装（インライン / 見出し / 引用 / フェンス / 水平線 / 選択範囲 / ソースモード） | §6.4 |
| ~~2-8~~ | — | ~~`editor/block_decorator.py`~~ **ADR-0002 で削除**。ブロック書式は効かず Undo を汚すため使わない | ADR-0002 |
| [x] | 2-9 | `editor/painter_overlay.py`: 引用の縦バー、コードブロック背景、水平線、チェックボックス | §5.2 |
| [x] | 2-10 | `theme.py` をライト/ダーク完全実装、システム追従 | §5.3 |
| [x] | 2-11 | ゴールデンテスト: サンプル `.md` → `(position, length, format名)` の JSON スナップショット | §10 |
| [x] | 2-12 | **日本語 IME 実機確認**（R2 の早期検証） | §11 R2。2026-08-08 に実機確認済み。変換候補は壊れず、装飾も正しく反映される |

**完了条件**（spec §9 より）
- [x] 日本語で `**太字**` → 確定と同時に太字、`**` が消える
- [x] カーソルを太字の中に入れると `**` が現れる
- [x] コードブロック内では装飾が一切効かない
- [x] `Cmd+Z` 1 回で直前の入力が戻る（Undo 汚染なし）
- [x] 10,000 語のファイルでカーソル移動が引っかからない

**実測（2,086 ブロック / 10,006 語、Apple Silicon・offscreen）**

| 操作 | 中央値 | 95%ile | 最大 | 基準 |
|---|---|---|---|---|
| ブロックをまたぐカーソル移動 | 1.71ms | 2.20ms | 8.84ms | < 16ms |
| 同一ブロック内のカーソル移動 | 0.95ms | 1.15ms | 1.50ms | < 16ms |
| 打鍵 → 反映 | 1.58ms | 2.33ms | 3.39ms | < 16ms |

---

## Phase 3: 入力補助（目安 1.5 日）

| | タスク | 参照 |
|---|---|---|
| [x] | 3-1 | `editor/input_handler.py`: リスト継続 / 空項目の 2 段階解除 / 番号リスト | §5.5 |
| [x] | 3-2 | 引用継続、Tab / Shift+Tab インデント（リスト行のみ） | §5.5 |
| [x] | 3-3 | オートペア（選択範囲を囲む）、URL ペーストでリンク化 | §5.5 |
| [x] | 3-4 | **IME ガード**: 変換中は Enter/Tab の特殊処理を全無効化 | §5.5 / R6 |
| [x] | 3-5 | `editor/commands.py`: `Cmd+B/I/E/K/Shift+X/Shift+H` のトグル（外す処理も必須） | §5.4 |
| [x] | 3-6 | 見出しレベル ±1、チェックボックス切替 | §5.4 |

**完了条件**: 「あいうえお」を変換中に Enter を押してもリストが増えない。`- ` で Enter 2 回で段落に戻る。

**結果**: 両方ともテストで固定済み（`test_editor_input.py`）。IME は 2026-08-08 に実機確認済み。

---

## Phase 4: ファイル層（目安 2 日）

| | タスク | 参照 |
|---|---|---|
| [x] | 4-1 | `storage/vault.py`: 走査、CRUD、ファイル名 sanitize、重複時 `-2` | §7.1 |
| [x] | 4-2 | `storage/vault.py`: `.trash` への移動、30 日経過での自動削除 | §7.6 |
| [x] | 4-3 | `storage/autosave.py`: `save_atomic()`（tmp + fsync + `os.replace`） | §7.4 |
| [x] | 4-4 | `storage/autosave.py`: デバウンス（800ms）と即時フラッシュ契機 | §7.4 |
| [x] | 4-5 | `storage/index_db.py`: スキーマ作成、`upsert_note()`、起動時の差分同期 | §7.3 |
| [x] | 4-6 | `storage/index_db.py`: `search()`（trigram + 2 文字以下は LIKE フォールバック） | §7.3 / R5 |
| [x] | 4-7 | `storage/index_db.py`: `tag_tree()`（階層タグの集計） | §7.3 |
| [x] | 4-8 | `storage/watcher.py`: watchdog → Qt シグナル、自己書き込みの抑制リスト | §7.5 |
| [x] | 4-9 | 競合検知（`mtime_ns` + blake2b）と競合ダイアログ | §7.5 |

**完了条件**
- [x] vault 指定 → 既存 `.md` が一覧に出る（`IndexDb.sync()`）
- [~] 編集 → 800ms 後にファイルが更新される（`Debouncer` は完成。UI への配線は Phase 5）
- [x] 外部エディタでの書き換えがアプリに反映される（`VaultWatcher`）
- [x] `.hitofude/index.sqlite` を消して再起動 → 完全に復元される（R9、`rebuild()`）

**実測（5,000 ノートの vault、Apple Silicon）**

| 操作 | 中央値 | 最大 | 基準 |
|---|---|---|---|
| 全文検索 6 文字（trigram） | 5.2ms | 5.9ms | < 200ms |
| 全文検索 2 文字（LIKE） | 1.1ms | 1.3ms | < 200ms |
| タグ絞り込み | 23.4ms | 32.2ms | < 200ms |
| 初回の索引構築 | 5,188ms | — | 別スレッド前提（§6.6） |
| 差分同期（変更なし） | 211ms | — | — |

---

## Phase 5: アプリ UI（目安 2.5 日）

| | タスク | 参照 |
|---|---|---|
| [x] | 5-1 | `ui/main_window.py`: 3 ペイン `QSplitter`、幅の永続化、メニューバー | §5.1 |
| [x] | 5-2 | `config.py`: `QSettings` ラッパと既定値 | §4 |
| [x] | 5-3 | `ui/note_list.py`: `QAbstractListModel` + `QStyledItemDelegate` | §5.1 / §6.6 |
| [x] | 5-4 | `ui/sidebar.py`: タグツリー、すべて / お気に入り / ゴミ箱 | §5.1 |
| [x] | 5-5 | `ui/quick_open.py`: `Cmd+O` ファジー検索パレット | §5.4 |
| [x] | 5-6 | 全文検索 `Cmd+Shift+F`（スニペット + ハイライト） | §5.4 |
| [x] | 5-7 | `ui/preferences.py`: フォント / テーマ / vault / ゴミ箱保持日数 | §5.4 |
| [x] | 5-8 | `scripts/gen_dummy_vault.py`: 5,000 件のダミーノート生成 | 性能検証用 |

**完了条件**: 5,000 件でリストのスクロールが滑らか、検索 200ms 以内。

**実測（5,000 ノートのダミー vault、Apple Silicon・offscreen）**

| 指標 | 実測 | 基準 |
|---|---|---|
| 起動 → ウィンドウ表示 | 658ms | < 1,500ms |
| ノート一覧のスクロール 1 フレーム | 3.79ms（中央値）/ 4.12ms（95%ile） | < 16.7ms（60fps） |
| 全文検索（UI 経由） | 4.8ms | < 200ms |
| 全文検索 2 文字（LIKE） | 2.7ms / 3.2ms（最大） | < 200ms |
| タグ絞り込み | 14.4ms / 22.2ms（最大） | < 200ms |
| クイックオープン | 37.1ms | — |
| 初回の索引構築 | 9,655ms | 別スレッド化は未了（下記） |

`uv run python scripts/gen_dummy_vault.py --notes 5000 --out /tmp/DummyVault --measure` で再現できる。

**完了**: 索引構築を別スレッド（`QThreadPool` + `QRunnable`）で回すようにした（§6.6）。

| 状況 | 操作可能になるまで | 一覧の件数 |
|---|---|---|
| 索引なし（初回起動、5,000 ノート） | **313ms** | 0 →（背景で 11.4 秒後に）5,000 |
| 索引あり（2 回目以降） | **159ms** | 5,000 |

走査中も一覧の更新・操作ができる（§7.3）。ワーカーは自分の SQLite 接続を開く。

---

## Phase 6: 仕上げと配布（目安 2 日）

| | タスク | 参照 |
|---|---|---|
| [x] | 6-1 | ソースモード `Cmd+/`、フォーカスモード、タイプライタモード | §5.4 |
| [x] | 6-2 | `Cmd+Shift+C`（プレーンテキストコピー） | §5.4 |
| [x] | 6-3 | HTML / PDF エクスポート（**ここでのみ `setMarkdown()` 可**） | §9 / R2 |
| [x] | 6-4 | アプリアイコン `.icns`、About ダイアログ | §8.1 |
| [~] | 6-5 | `setup.py`（py2app）→ **ビルドまで完了**。署名・公証・DMG は Apple Developer ID 待ち | §8.1–8.3 |
| [x] | 6-6 | クラッシュリカバリ（未保存バッファの退避） | §9 |
| [x] | 6-7 | 巨大ファイルガード（2MB / 20,000 行超は装飾無効化 + 警告） | §6.6 / R7 |
| [x] | 6-8 | 手動テストチェックリスト（IME / 配布）を `docs/manual_test.md` に | §10 |

**完了条件**: 署名済み DMG を別の Mac にコピーして Gatekeeper の警告なしに起動する。

---

## 追加で対応したもの（仕様書のタスク外）

ユーザー要望と、その過程で見つかった不具合。

| | 内容 | 記録 |
|---|---|---|
| [x] | ペインの区切り線（1px、テーマ追従） | — |
| [x] | 表の罫線描画・ヘッダ太字・行を離れたら自動整形 | ADR-0003 |
| [x] | 表の桁揃え（日本語の表示幅で計算） | ADR-0003 |
| [x] | 等幅フォントを実在するものへ（`SF Mono` は解決されない） | ADR-0003 |
| [x] | フォント設定の反映（等幅が未配線だった） | — |
| [x] | Option を含むショートカットの禁止（`Cmd+Option+T` でデータ消失） | ADR-0003 |
| [x] | 未処理の `Cmd` 組み合わせで文字を入れないガード | — |
| [x] | ショートカットの登録漏れ・衝突を検出するテスト | — |

## 進捗サマリ

| フェーズ | 進捗 | 状態 |
|---|---|---|
| Phase 0 開発環境・足場 | 13/15 | 0-C（署名・公証）のみ Apple Developer アカウント待ち |
| Phase 1 コア層 | 10/10 | 完了。core/ カバレッジ 98% |
| Phase 2 エディタ装飾 | 11/11 | 完了（2-8 は ADR-0002 で削除） |
| Phase 3 入力補助 | 6/6 | 完了 |
| Phase 4 ファイル層 | 9/9 | 完了。UI への配線は Phase 5 |
| Phase 5 アプリ UI | 8/8 | 完了 |
| Phase 6 仕上げ・配布 | 7/8 | 署名・公証・DMG のみ Apple Developer ID 待ち |
