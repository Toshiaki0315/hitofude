"""メニューバーの組み立て（spec §5.4）。

**ショートカットの一覧をここ 1 か所に集める。** 散らばっていると、
重複や割り当て漏れに気づけない（実際に「表を整形」がメニューへ追加され
ないまま気づけなかった）。登録漏れと衝突は
`tests/ui/test_appearance.py::TestShortcutRegistration` が見ている。
"""

from functools import partial

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu

from hitofude import APP_NAME


def build_menus(window) -> None:
    """`MainWindow` のメニューを組む。

    `add` はメニューへ入れるのと同時にウィンドウへも登録する。
    メニューを開かなくてもショートカットが効くようにするため。
    """

    # 歯車メニュー（build_gear_menu）が同じアクションを使い回すための台帳。
    # 別のアクションを作ると、ショートカット表示や状態が二重管理になる
    window.menu_actions = {}

    def add(menu, label: str, shortcut, slot) -> QAction:
        action = QAction(label, window)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        window.addAction(action)
        window.menu_actions[label] = action
        return action

    file_menu = window.menuBar().addMenu("ファイル")
    add(file_menu, "新規ノート", QKeySequence.StandardKey.New, window.new_note)
    add(file_menu, "テンプレートから新規…", "Ctrl+Shift+N", window.new_from_template)
    # **キーは付けない。** 消す操作で急がない（読み込む… と同じ理由）
    add(file_menu, "テンプレートを削除…", "", window.delete_template)
    # triggered(checked) の checked=False が day 引数に流れ込まないよう遮断する。
    # `daily_note` 側の `when = day or now()` が偶然吸収しているだけの脆い結合だった
    add(file_menu, "今日のノート", "Ctrl+T", lambda: window.open_daily_note())
    # 日誌を日付順に辿る（ユーザー要望）。**書いた日だけを飛び石で辿る**
    add(
        file_menu,
        "前の日のノート",
        "Ctrl+Shift+[",
        lambda: window.open_adjacent_daily(forward=False),
    )
    add(
        file_menu,
        "次の日のノート",
        "Ctrl+Shift+]",
        lambda: window.open_adjacent_daily(forward=True),
    )
    add(file_menu, "保存", QKeySequence.StandardKey.Save, window.flush)
    file_menu.addSeparator()
    add(file_menu, "ピン留め", "Ctrl+Shift+P", window.toggle_pin_current)
    add(file_menu, "ゴミ箱へ移動", "Ctrl+Backspace", window.trash_current)
    # 版の履歴（ADR-0023）。**ファイルの仲間**（保存・ゴミ箱と同じ、
    # ノートそのものの扱い）
    add(file_menu, "版の履歴…", "Ctrl+Shift+H", window.show_history)
    file_menu.addSeparator()
    # 取り込み（F-2）。**キーは付けない。** ファイルを選ぶ操作で急がない
    add(file_menu, "読み込む…", "", window.import_document)
    file_menu.addSeparator()
    add(file_menu, "Markdown で書き出す…", "Ctrl+Shift+M", window.export_markdown)
    add(file_menu, "HTML で書き出す…", "Ctrl+Shift+E", window.export_html)
    # **`Cmd+P` は印刷に譲る（C-9）。** macOS では印刷が慣習で、その
    # パネルから「PDF として保存」も選べる。書き出しの入口はここに残す
    add(file_menu, "PDF で書き出す…", "", window.export_pdf)
    add(file_menu, "PowerPoint で書き出す…", "", window.export_pptx)
    file_menu.addSeparator()
    add(file_menu, "印刷…", QKeySequence.StandardKey.Print, window.print_note)
    file_menu.addSeparator()
    add(file_menu, "ブラウザで確認", "Ctrl+Shift+B", window.preview_in_browser)
    add(file_menu, "HTML をコピー", "", window.copy_as_html)

    # StandardKey.Preferences はこの環境で空を返し、キーボードから
    # 到達できなくなる。macOS の慣習どおり明示する
    file_menu.addSeparator()
    # **キーを割り当てない。** 押し間違いでファイルが動く操作（E-5）
    add(file_menu, "使っていない添付を片づける…", "", window.cleanup_attachments)

    add(file_menu, "環境設定…", "Ctrl+,", window.open_preferences)

    search_menu = window.menuBar().addMenu("検索")
    add(search_menu, "クイックオープン", "Ctrl+O", window.quick_open)
    add(search_menu, "全文検索", "Ctrl+Shift+F", window.full_text_search)
    add(search_menu, "見出しへ飛ぶ", "Ctrl+R", window.open_outline)
    # 保存した検索（K-4）。**キーは付けない。** 名前を打つ操作で急がない
    add(search_menu, "検索を保存…", "", window.save_search)
    search_menu.addSeparator()
    add(search_menu, "このノート内を検索", "Ctrl+F", window._pane.open_find)
    add(search_menu, "次を検索", "Ctrl+G", window._pane.find_again)
    add(search_menu, "前を検索", "Ctrl+Shift+G", lambda: window._pane.find_again(backward=True))

    edit_menu = window.menuBar().addMenu("編集")
    # **フォーカスのあるウィジェットへ渡す。** ここで登録した
    # ショートカットはウィンドウ全体に効くので、素通しにすると
    # 検索欄で Cmd+A を押したのに本文が全選択される
    for label, key, name in (
        ("取り消す", QKeySequence.StandardKey.Undo, "undo"),
        ("やり直す", QKeySequence.StandardKey.Redo, "redo"),
        ("切り取り", QKeySequence.StandardKey.Cut, "cut"),
        ("コピー", QKeySequence.StandardKey.Copy, "copy"),
        ("貼り付け", QKeySequence.StandardKey.Paste, "paste"),
        ("すべて選択", QKeySequence.StandardKey.SelectAll, "selectAll"),
    ):
        add(edit_menu, label, key, partial(window.dispatch_edit, name))
    edit_menu.addSeparator()
    # **Option を含むショートカットは使わない。** macOS では Option が
    # 文字合成に使われ、Cmd+Option+T は `†` を生む。ショートカットが
    # 発火せず、選択中だと選択範囲がその 1 文字に置き換わって消える
    add(edit_menu, "表を整形", "Ctrl+Shift+L", window._editor.format_table)

    view_menu = window.menuBar().addMenu("表示")
    # 開くたびに今の状態をチェック印へ写す（ユーザー要望）。トグルの
    # たびに印を追いかけるより、見せる瞬間に読むほうが取りこぼさない
    view_menu.aboutToShow.connect(lambda: sync_view_checks(window))
    add(view_menu, "直前のノートへ戻る", "Ctrl+[", window.open_previous_note)
    view_menu.addSeparator()
    for label, key, slot in (
        ("サイドバー", "Ctrl+1", window.toggle_sidebar),
        ("ノートリスト", "Ctrl+2", window.toggle_note_list),
        ("書式ツールバー", "Ctrl+3", window.toggle_toolbar),
        ("バックリンク", "Ctrl+4", window.toggle_backlinks),
        ("アウトライン", "Ctrl+5", window.toggle_outline),
    ):
        add(view_menu, label, key, slot).setCheckable(True)
    view_menu.addSeparator()
    # **`+` は Shift を押さないと打てない。** 実際に押されるのは `Cmd+=` の
    # ほうが多いので、両方受ける（macOS の他のアプリもそうしている）
    zoom_in = add(view_menu, "文字を大きく", "Ctrl++", window.zoom_in)
    zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
    add(view_menu, "文字を小さく", "Ctrl+-", window.zoom_out)
    add(view_menu, "標準の大きさ", "Ctrl+0", window.reset_zoom)
    view_menu.addSeparator()
    for label, key, slot in (
        ("ソースモード（Raw）", "Ctrl+/", window._editor.toggle_source_mode),
        ("フォーカスモード", "Ctrl+Shift+D", window._editor.toggle_focus_mode),
        ("タイプライタモード", "Ctrl+Shift+Y", window._editor.toggle_typewriter_mode),
    ):
        add(view_menu, label, key, slot).setCheckable(True)

    help_menu = window.menuBar().addMenu("ヘルプ")
    add(help_menu, "ショートカット一覧", "Ctrl+?", window.show_shortcuts)
    add(help_menu, "使い方のノートを置き直す", "", window.place_manual)
    help_menu.addSeparator()
    add(help_menu, f"{APP_NAME} について", "", window.show_about)


def sync_view_checks(window) -> None:
    """表示の切り替えとモードのチェック印を、今の状態に合わせる。

    チェック可能なアクションの checked は**表示のためだけ**に使う。
    真実は各ウィジェット側にあり、メニューを開く瞬間にそこから読む。
    トグル操作そのものは checked に関係なく反転する（handler は常に flip）。
    """
    states = {
        "サイドバー": not window._splitter.widget(0).isHidden(),
        "ノートリスト": not window._splitter.widget(1).isHidden(),
        "書式ツールバー": window._pane.toolbar_visible(),
        "バックリンク": window._pane.backlinks.expanded(),
        "アウトライン": not window.outline_pane.isHidden(),
        "ソースモード（Raw）": window._editor.source_mode,
        "フォーカスモード": window._editor.focus_mode,
        "タイプライタモード": window._editor.typewriter_mode,
    }
    for label, checked in states.items():
        window.menu_actions[label].setChecked(checked)


def build_gear_menu(window) -> QMenu:
    """ステータスバー右端の歯車が開くメニュー（ユーザー要望）。

    メニューバーの**同じアクションを使い回す**。よく使うものだけを選ぶ。
    全メニューの写しにすると、探す手間がメニューバーと変わらなくなる。
    """
    menu = QMenu(window)
    menu.aboutToShow.connect(lambda: sync_view_checks(window))
    groups = (
        ("環境設定…",),
        ("サイドバー", "ノートリスト", "書式ツールバー", "バックリンク", "アウトライン"),
        ("ソースモード（Raw）", "フォーカスモード", "タイプライタモード"),
        ("ショートカット一覧", f"{APP_NAME} について"),
    )
    for index, labels in enumerate(groups):
        if index:
            menu.addSeparator()
        for label in labels:
            menu.addAction(window.menu_actions[label])
    return menu
