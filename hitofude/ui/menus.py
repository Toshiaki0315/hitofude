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
    # triggered(checked) の checked=False が day 引数に流れ込まないよう遮断する。
    # `daily_note` 側の `when = day or now()` が偶然吸収しているだけの脆い結合だった
    add(file_menu, "今日のノート", "Ctrl+T", lambda: window.open_daily_note())
    add(file_menu, "保存", QKeySequence.StandardKey.Save, window.flush)
    file_menu.addSeparator()
    add(file_menu, "ピン留め", "Ctrl+Shift+P", window.toggle_pin_current)
    add(file_menu, "ゴミ箱へ移動", "Ctrl+Backspace", window.trash_current)
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
    add(view_menu, "直前のノートへ戻る", "Ctrl+[", window.open_previous_note)
    view_menu.addSeparator()
    add(view_menu, "サイドバー", "Ctrl+1", window.toggle_sidebar)
    add(view_menu, "ノートリスト", "Ctrl+2", window.toggle_note_list)
    add(view_menu, "書式ツールバー", "Ctrl+3", window.toggle_toolbar)
    add(view_menu, "バックリンク", "Ctrl+4", window.toggle_backlinks)
    view_menu.addSeparator()
    # **`+` は Shift を押さないと打てない。** 実際に押されるのは `Cmd+=` の
    # ほうが多いので、両方受ける（macOS の他のアプリもそうしている）
    zoom_in = add(view_menu, "文字を大きく", "Ctrl++", window.zoom_in)
    zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
    add(view_menu, "文字を小さく", "Ctrl+-", window.zoom_out)
    add(view_menu, "標準の大きさ", "Ctrl+0", window.reset_zoom)
    view_menu.addSeparator()
    add(view_menu, "ソースモード（Raw）", "Ctrl+/", window._editor.toggle_source_mode)
    add(view_menu, "フォーカスモード", "Ctrl+Shift+D", window._editor.toggle_focus_mode)
    add(view_menu, "タイプライタモード", "Ctrl+Shift+Y", window._editor.toggle_typewriter_mode)

    help_menu = window.menuBar().addMenu("ヘルプ")
    add(help_menu, "ショートカット一覧", "Ctrl+?", window.show_shortcuts)
    add(help_menu, "使い方のノートを置き直す", "", window.place_manual)
    help_menu.addSeparator()
    add(help_menu, f"{APP_NAME} について", "", window.show_about)


def build_gear_menu(window) -> QMenu:
    """ツールバー右端の歯車が開くメニュー（ユーザー要望）。

    メニューバーの**同じアクションを使い回す**。よく使うものだけを選ぶ。
    全メニューの写しにすると、探す手間がメニューバーと変わらなくなる。
    """
    menu = QMenu(window)
    groups = (
        ("環境設定…",),
        ("サイドバー", "ノートリスト", "書式ツールバー", "バックリンク"),
        ("ソースモード（Raw）", "フォーカスモード", "タイプライタモード"),
        ("ショートカット一覧", f"{APP_NAME} について"),
    )
    for index, labels in enumerate(groups):
        if index:
            menu.addSeparator()
        for label in labels:
            menu.addAction(window.menu_actions[label])
    return menu
