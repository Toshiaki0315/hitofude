# 機械が見ているもの

**もとは手動チェックだった項目**で、今は自動テストが担保しているもの。
人が通す必要は無い——[manual_test.md](manual_test.md) に残っているのが
**人にしかできない**ぶん。

ここは**索引**。何が守られていて、どのテストが守っているかを引くために
ある。手順や理由は自動テスト側の説明に書いてある（1 か所にまとめるため、
ここには写さない）。

**移すときの決まり。** 根拠のテストが実在し、**同じことを見ている**ことを
確かめてから移す。似ているだけのテストを当てにすると、守られていないのに
守られているつもりになる（実際に 1 度やりかけた——「右クリックが同じ
大きさ・同じ間隔」を、メニューの並び順のテストで担保したことにしていた）。


## 2. 見た目

| 確認していたこと | 期待・根拠 |
| --- | --- |
| 段落で Tab を打つ | 4 文字ぶんの幅で送られる（8 文字ぶん空かない）（自動: tests/editor/test_editor_widget.py） |
| **コードブロックの中**で Tab を打つ | **ちょうど 4 文字ぶん**（等幅の字幅で揃う）（自動: tests/editor/test_editor_widget.py） |
| 字下げした行の末尾で Enter | **同じ字下げで次の行が始まる**（自動: tests/editor/test_input_handler.py） |
| 字下げの途中（空白の中）で Enter | 字下げは足されない（自動: tests/editor/test_input_handler.py） |
| 変換中に Enter で確定 | 確定するだけ。字下げが増えない（自動: tests/editor/test_editor_input.py） |
| 環境設定の「タブ幅」 | 数字と「文字」が分かれ、矢印が数字の隣にある（自動: tests/ui/test_preferences.py） |
| 環境設定でタブ幅を 2 にする | すぐ狭くなる。ファイルの中身は変わらない（自動: tests/ui/test_preferences.py） |
| 文字サイズを大きくする | タブ幅も一緒に広がる（文字数の比が保たれる）（自動: tests/editor/test_editor_widget.py） |
| 設定を変えてから「デフォルトに戻す」 | 入力欄が既定に戻る。**保管フォルダはそのまま**（自動: tests/ui/test_preferences.py） |
| 上の状態で Cancel を押す | 変更前の設定のまま（戻した内容は捨てられる）（自動: tests/ui/test_preferences.py） |
| もう一度戻して OK を押す | 本文フォント・テーマ・保持日数が既定に変わる（自動: tests/ui/test_preferences.py） |
| ツールバーの並び | 11 個のアイコンが読める大きさで出ている（自動: tests/ui/test_format_toolbar.py） |
| 文字を選んで「太字」を押す | `**` で囲まれ、**選択が残る**（続けて押すと外れる）（自動: tests/ui/test_format_toolbar.py） |
| 何も選ばずに「太字」を押す | `****` が置かれ、間にカーソルが入る（自動: tests/editor/test_commands.py） |
| 3 行選んで「箇条書き」を押す | 3 行とも `- ` が付く。`Cmd+Z` **1 回**で戻る（自動: tests/ui/test_format_toolbar.py） |
| 続けて「番号付き」を押す | `- ` が `1. 2. 3.` に入れ替わる（入れ子にならない）（自動: tests/editor/test_commands.py） |
| 「見出し」を 4 回押す | 段落 → H1 → H2 → H3 → 段落 と一周する（自動: tests/editor/test_commands.py） |
| 変換中（未確定の文字がある状態）で押す | **何も起きない**。プリエディットが壊れない（自動: tests/editor/test_editor_commands.py） |
| ボタンを押したあとそのまま打つ | 本文に入る（フォーカスがボタンに移らない）（自動: tests/ui/test_format_toolbar.py） |
| `Cmd+3` | ツールバーが隠れる / 出る。終了して起動しても状態が残る（自動: tests/ui/test_pane_layout.py） |
| 表を書いて `Cmd+Shift+L` | 縦線が揃う。日本語混じりでもずれない（自動: tests/editor/test_table.py） |
| 表全体を選択して `Cmd+Shift+L` | 選択したままでも整形される（自動: tests/ui/test_appearance.py） |
| 表の 3 行目を打って改行 | 自動で揃い、罫線とヘッダ背景が現れる（自動: tests/editor/test_table_render.py） |
| セルの中身と罫線のあいだ | 上下左右に余白がある。文字が線に接しない（自動: tests/editor/test_table_render.py） |
| `Cmd+/`（ソースモード） | 表も生の Markdown に戻る（自動: tests/editor/test_painter_overlay.py） |
| 割り当てていない `Cmd+Option+英字` を選択中に押す | **何も入らず選択も消えない**（自動: tests/editor/test_editor_commands.py） |
| サイドバーの項目 | すべて / お気に入り / ゴミ箱 / タグにアイコンが付く（自動: tests/ui/test_sidebar.py） |
| 本文を右クリックする | 「元に戻す」「切り取り」などが日本語で出る（自動: tests/test_app.py::TestQtJapanese） |
| 窓を広げて本文の左右を見る（2026-08-26） | **書けない場所が少し沈んだ色**になる（自動: tests/ui/test_page_background.py） |
| 長いノートを開いた直後に下を見る（Q-3） | **横スクロールバーが出ない**（行が右へはみ出さない）（自動: tests/ui/test_wrap_on_open.py） |
| ダークテーマで同じところを見る | 外側が本文より**暗い**（光って見えない）（自動: tests/ui/test_page_background.py::test_暗いテーマでも外側が沈む） |
| 設定で本文の幅を「全幅」にする | 外側が無くなる（沈んだ色も出ない）（自動: tests/ui/test_page_background.py::test_幅いっぱいなら塗る場所が無い） |
| 「編集」→「書式」を開く（2026-08-25） | ツールバーと同じ 11 個が並び、⌘B などのキーも出る（自動: tests/ui/test_format_menu.py） |
| `Cmd+3` でツールバーを隠してから「編集」→「書式」→「太字」 | **隠していても書式が付く**（入口が消えない）（自動: tests/ui/test_format_menu.py::TestToolbarHidden） |
| 検索欄（`Cmd+F`）に焦点がある状態で `Cmd+B` | **何も起きない**（本文が太字にならない。今までと同じ）（自動: tests/ui/test_format_menu.py::test_他所に焦点があれば何もしない） |
| 「ファイル」を開く（2026-08-25 に整理） | 15 行に収まり、「書き出す」と「メンテナンス」に畳まれている（自動: tests/ui/test_file_menu_layout.py） |
| 「はい / いいえ」を聞くダイアログを出す | ボタンも日本語（例: ゴミ箱を空にする）（自動: tests/test_app.py::test_ダイアログのボタンも日本語） |
| ノートをピン留めして一覧を見る | **黄色い星**が付く。タイトルと重ならない（自動: tests/ui/test_note_list.py） |
| ダークに切り替える | **アイコンの色も追従する**（黒いまま残らない）（自動: tests/ui/test_icons.py） |
| `Cmd+1` で隠す → 再起動 → `Cmd+1` で戻す | **使える幅で戻る**（線だけにならない）（自動: tests/ui/test_pane_layout.py） |
| `Cmd+H` でアプリを隠す → `Cmd+Q` → 再起動 | **ペインが出たまま**（真っ白にならない）（自動: tests/ui/test_pane_layout.py） |
| 幅を変える → `Cmd+1` で隠す → `Cmd+1` で戻す | 変えた幅で戻る（自動: tests/ui/test_pane_layout.py） |
| ノートを開いて終了 → 再起動 | **前回のノートが開く**。一覧でも選ばれている（自動: tests/ui/test_last_note.py） |
| 再起動直後にそのまま打ち始める | front matter が壊れない（カーソルが本文の先頭）（自動: tests/editor/test_front_matter_guard.py） |
| 打っている最中のタイトル | `•` が付き、保存されると消える（自動: tests/ui/test_status_and_edit.py） |
| 右下の文字数 | 打ち終わって少し待つと更新される（自動: tests/ui/test_status_and_edit.py） |
| 右下の文字数の右端 | **最後の文字が角丸に欠けない**（自動: tests/ui/test_status_and_edit.py） |
| `- [ ]` と `- [x]` を並べる | **箱の大きさが同じ**。文字と重ならない（自動: tests/editor/test_painter_overlay.py） |
| チェックの行にカーソルを入れる | `[ ]` が現れ、広げた幅が戻る（間延びしない）（自動: tests/editor/test_painter_overlay.py） |
| `→` や `①` を含む表を書く | **桁が揃う**（C-1。以前は 20px ずれた）（自動: tests/editor/test_table_render.py） |
| `Cmd+R` を押す | 見出しの一覧が出る。選ぶとその行へ飛ぶ（自動: tests/ui/test_quick_open.py） |
| 長い本文のノートを一覧で見る | **プレビューの 2 行目が切れない**（自動: tests/ui/test_note_list.py） |
| 短い本文のノートと並べる | 行の高さが内容に合う（すかすかにならない）（自動: tests/ui/test_note_list.py） |
| 一覧左上の `⇅` と `＋` | **同じ見た目**（`⇅` だけ枠が出ていない）（自動: tests/ui/test_note_list_pane.py） |
| ツールバー右端の **Raw** を押す | 記号が全部出る。罫線・囲みの線・チェックの印が消える（自動: tests/ui/test_format_toolbar.py） |
| Raw のまま先頭までスクロールする | **`id` などが出ない**（管理情報は隠れたまま）（自動: tests/editor/test_highlighter.py） |
| `Cmd+/` で切り替える | **Raw ボタンの見た目も一緒に変わる**（自動: tests/ui/test_format_toolbar.py） |
| Raw のままノートを切り替える | 記号が出たまま（食い違わない）（自動: tests/ui/test_format_toolbar.py） |
| ツールバーと本文の境目 | 細い線で仕切られている（自動: tests/ui/test_format_toolbar.py） |
| 終了して起動し直す | 並び順が残っている（自動: tests/ui/test_note_actions.py） |
| 何か打って 1 秒待つ | 右下に**保存した時刻**が出る（自動: tests/ui/test_status_and_edit.py） |
| 続けて打つ | 時刻が消える（今の状態と食い違わない）（自動: tests/ui/test_status_and_edit.py） |
| ノートを全部ゴミ箱へ入れる | 一覧に「＋ で作れます」と出る（自動: tests/ui/test_note_list_pane.py） |
| `Cmd+?` | ショートカット一覧が出る。⌘ の記号で書かれている（自動: tests/ui/test_shortcut_sheet.py） |
| 3 つのノートを順に開いて `Cmd+[` を 2 回 | **1 つ目まで遡る**（往復しない）（自動: tests/ui/test_last_note.py） |
| 置き直したノートを一通り眺める | 囲み・脚注・ファイル名付きコードが見本として出ている（自動: tests/storage/test_seed.py） |
| `:::note info` と `:::` で囲んで本文を書く | 左に**青い縦線**が出る。`:::` の行は消える（自動: tests/core/test_block_parser.py） |
| `warn` / `alert` に書き換える | 黄 / 赤に変わる。3 つ並べても見分けが付く（自動: tests/editor/test_painter_overlay.py） |
| `:::note warm` と綴りを間違える | **灰色の線**になり、`:::note warm` の行が消えない（自動: tests/core/test_block_parser.py） |
| 同じノートを HTML で書き出す | 書き出しも灰色（画面と食い違わない）（自動: tests/core/test_html.py） |
| `:::note warn extra` と語を 2 つ書く | 囲みにならず、そのまま文字で出る（画面も書き出しも）（自動: tests/core/test_html.py） |
| 囲みの中に見出し・箇条書き・引用を書く | 今まで通り装飾される。引用の縦線が囲みの線と重ならない（自動: tests/core/test_block_parser.py） |
| 囲みの中でコードフェンスを開いて閉じる | フェンスの後も囲みが続いている（自動: tests/core/test_block_parser.py） |
| ` ```python ` でコードを書く | **予約語・文字列・コメントに色が付く**（自動: tests/editor/test_highlighter.py） |
| 同じものを HTML / PDF で書き出す | 画面と同じ配色で色が付く（自動: tests/core/test_html.py） |
| ダークモードで同じコードを見る | 黒地に黒い字にならない（自動: tests/core/test_code_tokens.py） |
| 言語を消す（` ``` ` だけにする） | 色が消える（自動: tests/editor/test_highlighter.py） |
| 色付きのコードの中で長文を打つ | **引っかからない**（200 行までが対象）（自動: tests/editor/test_highlighter.py） |
| ` ```js:index.js ` と書く | **画面でもコードの上にファイル名が出る**（自動: tests/editor/test_painter_overlay.py） |
| 同じものを書き出す | HTML にもファイル名が出る（自動: tests/core/test_html.py） |
| ` ```python ` とファイル名なしで書く | 名前は出ない。フェンスの行は潰れたまま（自動: tests/editor/test_painter_overlay.py） |
| コードブロックの左 | **アクセントバーが無い**（背景だけ。ADR-0008）（自動: tests/editor/test_painter_overlay.py） |
| 図の無いノートを書き出す | ファイルが 3.4MB 太っていない（自動: tests/editor/test_exporter.py） |
| 図のあるノートを PDF で書き出す | 図にはならないが、書いた内容は残る（自動: tests/editor/test_exporter.py） |
| `$E = mc^2$` と書く | 画面で等幅になる。HTML に書き出すと**組版される**（自動: tests/core/test_html.py） |
| 同じものを PDF で書き出す | `$E = mc^2$` と書いたまま出る（`E=mc2` にならない）（自動: tests/editor/test_exporter.py） |
| `$$` で囲んだ式を HTML で書き出す | 中央に大きく組まれる（自動: tests/core/test_html.py） |
| `$$` を複数行で書く | 画面でコードと同じ背景になる。`$$` の行は消える（自動: tests/core/test_block_parser.py） |
| `$$x$$` を 1 行で書く | 画面でも等幅になる（書き出しと食い違わない）（自動: tests/core/test_inline_scanner.py） |
| `価格は $100 と $200 です。定価 100$ から $200 まで。` | **どこも数式にならない**（画面も書き出しも）（自動: tests/core/test_html.py） |
| `[^1]` と `[^1]: 注釈` を書く | 画面で `[^1]` が色付き。書き出すと本文の下に注釈がまとまる（自動: tests/core/test_html.py） |
| チェックボックス入りのノートを HTML で書き出す | ブラウザで `☐` / `☑` が出る（以前は印が消えていた）（自動: tests/core/test_html.py） |
| 同じノートを PDF で書き出す | 表に罫線がある。コードブロックに背景がある（自動: tests/editor/test_exporter.py） |
| 画像入りのノートを HTML で書き出して別の場所へ移す | 画像が消えない（埋め込まれている）（自動: tests/editor/test_exporter.py） |
| 本文の一部を選んで `Cmd+Shift+K`（仮身化 / M-1） | 選んだ文が消えて `[[題名]]` が残る。**切り出した先は開かない**（書いている流れが切れない）（自動: tests/ui/test_extract_selection.py::TestExtract） |
| 続けて `Cmd+Z` を 1 回 | **1 回で元に戻る**（半端に戻らない）（自動: tests/ui/test_extract_selection.py::TestUndo） |
| 残った `[[題名]]` を Cmd+クリック | 切り出したノートが開く（**新しく作られない**）（自動: tests/ui/test_extract_selection.py::test_リンクを押すと切り出した先へ飛ぶ） |
| 何も選ばずに「編集」メニューを開く | 「選択範囲をノートにする」が灰色（自動: tests/ui/test_extract_selection.py::test_選んでいなければメニューは灰色） |
| `Cmd+Shift+R`（リンクの図 / M-2） | 別窓が開き、**今のノートが赤く大きい点**で中央にある（自動: tests/ui/test_graph_window.py::TestOpen・TestDrawing） |
| 図の「深さ」を 1 と 3 に変える | 点が減る / 増える。閉じて開き直しても**選んだ深さが残る**（自動: tests/ui/test_graph_window.py::TestDepth） |
| 図の点を押す | そのノートが開き、図は閉じる（自動: tests/ui/test_graph_window.py::TestClick） |
| **中抜きの点**（まだ無いノート）を押す | **作られない**。「まだ無いノートです」と出る（自動: tests/ui/test_graph_window.py::test_まだ無いノートの点では作らない） |
| `- 参考文献: [[どれか]]` と書いて図を開く（続柄 / M-3） | 「すべての続柄」の隣に**続柄の選択肢**が出る（自動: tests/ui/test_graph_window.py::TestRelationFilter） |
| 続柄を選ぶ | その関係のリンクだけの図になる。**起点は残る**（自動: tests/ui/test_graph_window.py::test_選ぶとその関係だけになる） |
| `- 10:30 の打ち合わせ [[どれか]]` と書く | 「10」が続柄にならない（選択肢に出ない）（自動: tests/core/test_wikilink_relations.py::test_時刻は続柄にしない） |
| 続柄を使っていない vault で図を開く | 続柄の選択肢そのものが出ない（自動: tests/ui/test_graph_window.py::test_続柄が無ければ選択肢も出さない） |
| 長い題名のノートを何本か指してから図を開く（M-4） | 題名が**窓からはみ出さない**。長いものは真ん中が `…` になる（自動: tests/ui/test_graph_window.py::TestLabels・TestNoClipping） |
| その `…` の付いた題名を読む | **末尾が残っている**（連番や日付で見分けられる）（自動: tests/ui/test_graph_window.py::test_見分けが付く末尾を残す） |
| 図の窓を小さくしてから開く | 題名がはみ出さない（自動: tests/ui/test_graph_window.py::test_どこに置いても枠の中） |
| 100 本以上と繋がったノートで図を開く | **題名同士が重ならない**（点は出るが題名の無いものがある）（自動: tests/ui/test_graph_window.py::TestNoOverlap） |
| 題名の出ていない点にカーソルを乗せる | その点の題名だけが出る（自動: tests/ui/test_graph_window.py::TestHover） |
| 窓を大きくする | 出る題名が増える（自動: tests/ui/test_graph_window.py::test_広いほど多く出せる） |
| 版を上げた後に初めて起動する（M-5） | **ノートが一覧に出る**（索引は作り直され、少し待つ）（自動: tests/storage/test_index_db.py::TestUpgradeFromOldShape） |
| `.OboeGaki` の索引ファイルを消してから起動 | 一覧が戻る（捨ててよいキャッシュ。R9）（自動: tests/storage/test_index_db.py::TestRebuildInPlace） |
| アプリを閉じている間に Finder で `.md` を足し、開いてから「ファイル」→「メンテナンス」→「最新の情報に同期」（M-6） | 足したノートが一覧に出る。「1 件増えました」と出る（自動: tests/ui/test_resync.py::test_外で足したファイルが出る） |
| 同じく Finder で 1 つ消してから「最新の情報に同期」 | 一覧から消える。「1 件消えました」と出る（自動: tests/ui/test_resync.py::test_外で消したファイルが消える） |
| 何も変えずに「最新の情報に同期」 | **「変わりはありません」**と出る（無反応に見えない）（自動: tests/ui/test_resync.py::test_変わっていなければそう言う） |
| 打ちかけの字がある状態で「最新の情報に同期」 | **打ちかけが消えない**（先に保存される）（自動: tests/ui/test_resync.py::test_打ちかけを先に保存する） |
| 「ファイル」→「メンテナンス」→「索引を作り直す」 | 一覧が保たれる。「N 件増えました」と出る。**ファイルは減らない**（自動: tests/ui/test_resync.py::TestRebuild） |
| 文字を選んで `Cmd+Shift+X` | **打ち消し線**（切り出しではない。M-1 で取り違えていたキー）（自動: tests/ui/test_extract_selection.py::test_打ち消し線は今まで通り） |
| 「ファイル」→「版の履歴…」 | 開く。**キーは表示されない**（`Cmd+Shift+H` はハイライトなので取り下げた）（自動: tests/ui/test_history_flow.py::TestOpenDialog） |
| 右下の表示 | **「N 文字 / N 行」**。単語数は出ない（自動: tests/ui/test_status_and_edit.py） |
| 右下の文字数にカーソルを乗せる | 何を数えているかの説明が出る（自動: tests/ui/test_status_and_edit.py） |
| 一覧の右上の `＋` を押す | 新規ノートができて開く。一覧でも選ばれる（自動: tests/ui/test_note_list_pane.py） |
| `＋` にカーソルを乗せる | 「新規ノート（Cmd+N）」と出る（自動: tests/ui/test_note_list_pane.py） |
| 一覧を右クリック | ピン留め / 名前を変更 / ゴミ箱へ移動 が出る（自動: tests/ui/test_note_actions.py） |
| `Cmd+Shift+F` の右上を見る | 「閉じる」ボタンがあり、押すと閉じる（自動: tests/ui/test_quick_open.py::TestCloseButton） |
| `×` を押さずに `Esc` | 今まで通り閉じる（自動: tests/ui/test_quick_open.py::TestCloseButton） |
| 「名前を変更」で名前を変える | 一覧の表示と本文の見出しが変わり、ファイル名も変わる（自動: tests/ui/test_note_actions.py） |
| 開いているノートの名前を変えて `Cmd+Z` | 元の見出しに戻る（自動: tests/ui/test_note_actions.py） |
| 見出しの無いノートの名前を変える | 先頭に見出しが足され、元の文章は残る（自動: tests/ui/test_note_actions.py） |
| ゴミ箱を開いて右クリック | 「元に戻す」と「完全に削除…」が出る（自動: tests/ui/test_note_actions.py） |
| スクリーンショットを撮って `Cmd+V` | `![](attachments/...)` が入り、`attachments/` にファイルができる（自動: tests/editor/test_paste_image.py） |
| 画像ファイルをウィンドウへドラッグ | 同上。拡張子はそのまま（JPEG が PNG にならない）（自動: tests/editor/test_paste_image.py） |
| 貼った直後の本文 | **その場に絵が出る**（リンク文字列ではなく）（自動: tests/editor/test_inline_image.py） |
| 画像行にカーソルを入れる | **高さが変わらない。絵も消えない**（下の行が飛ばない）（自動: tests/editor/test_inline_image.py） |
| `Cmd+/`（ソースモード） | 絵が消えて `![](...)` に戻る（自動: tests/editor/test_inline_image.py） |
| 画像ファイルを Finder で消してから開き直す | `![](...)` が文字で見える（空行にならない）（自動: tests/editor/test_inline_image.py） |
| 画像を貼ったノートを PDF で書き出す | **画像が出る**（抜け落ちない）（自動: tests/editor/test_exporter.py） |
| 同じノートを HTML で書き出し、別の場所へ移して開く | 画像が出る（埋め込まれている）（自動: tests/editor/test_exporter.py） |
| 貼った直後に `Cmd+Z` | 1 回でリンクが消える（自動: tests/editor/test_paste_image.py） |
| `samples/会議メモ.pdf` を読み込む | 速い（読み取りに回らない）（自動: tests/editor/test_import_samples.py::TestTextPdf） |
| フォルダを選んだ状態で読み込む | そのフォルダの中にノートができる（自動: tests/ui/test_note_list_folder.py::TestImportIntoFolder） |
| フォルダを選んだ状態で `.md` をドロップ | 同じくそのフォルダに入る（自動: tests/ui/test_note_list_folder.py::TestImportIntoFolder） |
| `samples/会議メモ-図つき.pdf` を読み込む | 図が `attachments/` に入り、本文の後ろに出る（自動: tests/editor/test_import_samples.py::TestFigures） |
| スキャンした PDF を読み込む | 紙の写真は添付されない（文字だけ）（自動: tests/editor/test_import_samples.py::test_紙の写真は添付しない） |
| `samples/会議メモ-混在.pdf` を読み込む | どちらのページも中身が入る（自動: tests/editor/test_import_samples.py::TestMixedPdf） |
| 読み取りができない状態で画像を読み込む | ノートを作らず、確かめる場所を知らせる（自動: tests/editor/test_import_samples.py::TestUnavailable） |
| `Cmd+Shift+M` で書き出し → 他のエディタで開く | 打った通りの Markdown。front matter は付かない（自動: tests/editor/test_exporter.py） |

## 3. 外部エディタとの併用

| 確認していたこと | 期待・根拠 |
| --- | --- |
| 開いているノートを外部で書き換える（アプリ側も編集中） | 競合ダイアログが出る（自動: tests/ui/test_conflict_flow.py） |
| 競合ダイアログで「両方残す」 | `名前 (競合 日付).md` ができ、内容が両方残る（自動: tests/ui/test_conflict_flow.py） |
| 保管フォルダにサブフォルダを作り `.md` を置く | 一覧に出る（自動: tests/storage/test_vault.py） |
| フォルダを右クリックする | 「名前を変更…」が「フォルダを削除…」の上にある（自動: tests/ui/test_folder_sidebar.py::test_削除の上に出る） |
| 名前を変えて OK | サイドバーも一覧も新しい名前になる（自動: tests/ui/test_folder_sidebar.py::test_名前が変わる・test_索引が追いつく） |
| そのフォルダのノートを開いたまま名前を変える | 開いたまま編集でき、保存も通る（自動: tests/ui/test_folder_sidebar.py::test_開いているノートも追いつく） |
| 既にある名前に変えようとする | 断られ、フォルダは元のまま（自動: tests/ui/test_folder_sidebar.py::test_同じ名前があれば知らせる） |
| 保管フォルダの外を指すシンボリックリンクを置く | **一覧に出ない**（外のノートを取り込まない）（自動: tests/storage/test_vault.py） |
| アプリで編集して保存する | **外部変更として通知が来ない**（自己書き込みの抑制）（自動: tests/storage/test_watcher.py） |

## 4. データを失わないこと

| 確認していたこと | 期待・根拠 |
| --- | --- |
| `Cmd+A` で全選択 | **本文だけが選ばれる**（`id:` などが現れない）（自動: tests/editor/test_front_matter_guard.py） |
| `Cmd+A` → `Cmd+X`（切り取り）→ ファイルを確認 | front matter が残っている（自動: tests/editor/test_front_matter_guard.py） |

## 5. 配布（Phase 6 完了後）

| 確認していたこと | 期待・根拠 |
| --- | --- |
| 許可を**断って**から起動し直す | 落ちない（保管フォルダを選び直せる）（自動: tests/ui/test_locked_vault.py） |

