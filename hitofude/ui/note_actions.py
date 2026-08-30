"""ノートを増やす・減らす・付け替える操作の束（spec §7.6 / E-4 / E-5 / G-3 / ADR-0005）。

ゴミ箱（移動・復元・完全削除・空にする）、ピン留め、名前の変更、
テンプレートと今日のノート、右クリックメニュー、添付の片づけ。
`MainWindow` から切り出した協調オブジェクトで、**挙動は変えない**
（export_actions / search_actions / save_controller と同じ「友達」の作り）。
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox

from hitofude.app import style_menu
from hitofude.core import extract, template, textpos
from hitofude.core.document import Note, with_title
from hitofude.core.template import daily_title
from hitofude.storage.index_db import ROOT_FOLDER, NoteRow
from hitofude.storage.vault import MARKDOWN_SUFFIXES, sanitize_filename, unique_path
from hitofude.ui.icons import menu_icon
from hitofude.ui.note_list import NoteRole
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter
from hitofude.ui.sidebar import Filter, FilterKind

logger = logging.getLogger(__name__)

# 片づけの確認に並べる名前の数（E-5）。全部並べるとダイアログが画面を溢れる
CLEANUP_PREVIEW = 10

NO_TEMPLATE_NOTICE = "差し込めるテンプレートがまだありません"

# 「フォルダへ移動…」の先頭の選択肢。直下（フォルダから出す）を表す
ROOT_FOLDER_CHOICE = "（保管フォルダ直下）"


def _new_menu(window) -> QMenu:
    """右クリックのメニューを作る。**見た目もここで当てる**（ユーザー指摘）。

    Qt の既定は行が詰まっていて角も立っている。作る場所を 1 つに寄せて、
    足したメニューだけ素のまま、が起きないようにする。
    """
    menu = QMenu(window)
    style_menu(menu, window._theme_watcher.colors)
    return menu


def add_item(menu: QMenu, label: str) -> QAction:
    """メニューに 1 項目足す。**アイコンは OS からもらう。**"""
    action = menu.addAction(label)
    icon = menu_icon(label)
    if icon is not None:
        action.setIcon(icon)
    return action


PINNED_NOTICE = "お気に入りのノートは削除できません。先にお気に入りから外してください。"


class NoteActions:
    """ノートの CRUD まわり。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window

    # ------------------------------------------------------------- ゴミ箱

    def trash_rows(self) -> list[NoteRow]:
        """ゴミ箱の中身を並べる。

        `.trash` は索引の対象外（`vault.scan()` が除外する）なので、
        ここだけはファイルから直に読む。ゴミ箱は件数が少ない前提。
        """
        window = self._window
        rows: list[NoteRow] = []
        for path in sorted(window._vault.trash_dir.rglob("*.md")):
            try:
                note = window._vault.read(path)
            except OSError:
                continue
            rows.append(
                NoteRow(
                    id=str(path),
                    path=path.relative_to(window._vault.root),
                    title=note.title,
                    preview=note.preview,
                    modified_at=str(note.meta.get("modified", "")),
                    mtime_ns=note.mtime_ns,
                    size_bytes=note.size_bytes,
                    pinned=False,
                )
            )
        return rows

    def trash_current(self) -> bool:
        window = self._window
        if window._note is None:
            return False
        if window._note.pinned:
            self._notify_pinned()
            return False

        # **打ちかけを捨てない。** 自動保存は打ち終わって 0.8 秒で走るので、
        # 打った直後に捨てると、まだ書かれていない内容ごとゴミ箱へ行く
        # （戻しても消えている）。保存は見出しに合わせてファイル名を変える
        # ことがある（K-1）ので、**捨てる相手は保存後のパス**を取り直す
        window.flush()
        if window._note is None:
            return False  # 保存の途中で閉じられた（競合の解決など）

        path = window._note.path
        window._watcher.suppress(path)
        window._vault.trash(path)
        window._db.remove_path(window._vault.root, path)
        window._close_current()
        window.refresh()
        return True

    def trash_note(self, path: Path) -> bool:
        """ゴミ箱へ移す。移せたら True。

        **ピン留めしているノートは移さない。** ピン留めは「これは残す」と
        いう意思表示で、削除と噛み合わない。
        """
        window = self._window
        if window._note is not None and window._note.path == path:
            return self.trash_current()
        if self.is_pinned(path):
            self._notify_pinned()
            return False

        window._watcher.suppress(path)
        if not self._trash_file(path):
            return False
        window._db.remove_path(window._vault.root, path)
        window.refresh()
        return True

    def _trash_file(self, path: Path) -> bool:
        """ゴミ箱へ移す。**保管フォルダの外なら知らせて終わる。**

        `Vault` が境界で止めるようになった（レビュー指摘）ので、受け手も
        知らせて終わる。素通しにすると画面が落ちる。
        """
        window = self._window
        try:
            window._vault.trash(path)
        except (ValueError, OSError) as error:
            logger.warning("ゴミ箱へ移せなかった: %s", error)
            window.notify("保管フォルダの中のノートだけ移せます")
            return False
        return True

    def restore_note(self, path: Path) -> Path | None:
        """ゴミ箱から vault 直下へ戻す。戻した先を返す。

        **索引にも入れる。** ファイルを動かすだけでは一覧に出てこない。
        """
        window = self._window
        if not path.is_file():
            return None
        window._watcher.suppress(path)
        try:
            target = window._vault.restore(path)
        except (ValueError, OSError) as error:
            logger.warning("戻せなかった: %s", error)
            window.notify("ゴミ箱の中のノートだけ戻せます")
            return None
        window._watcher.suppress(target)
        window._db.upsert_note(window._vault.read(target), window._vault.root)
        window.refresh()
        logger.info("ゴミ箱から戻した: %s", target.name)
        return target

    def delete_permanently(self, path: Path) -> bool:
        """ゴミ箱の 1 件を完全に削除する（G-3）。消したら True。

        **戻せないので必ず名前を見せて確認する。** ゴミ箱へ移すときの
        「30 日は戻せます」とは別の文面にする。
        """
        window = self._window
        if not path.is_file():
            return False
        answer = QMessageBox.question(
            window,
            "完全に削除",
            f"「{path.stem}」を完全に削除しますか？\nこの操作は取り消せません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        # **開いたままにしない。** 消えたファイルに向けて自動保存が走ると、
        # 消したはずのノートが書き戻る
        if window._note is not None and window._note.path == path:
            window._close_current()
        window._watcher.suppress(path)
        try:
            window._vault.delete_permanently(path)
        except ValueError as error:
            # ゴミ箱の外を渡されたときだけ。押した人には落ちて見えないように
            logger.warning("完全に削除できなかった: %s", error)
            window.notify("ゴミ箱の中のノートだけ完全に削除できます")
            return False
        window.refresh()
        window.notify("完全に削除しました")
        logger.info("完全に削除した: %s", path.name)
        return True

    def empty_trash(self) -> int:
        """ゴミ箱を今すぐ空にする（G-3）。消した数を返す。

        **30 日待たずに消したいことがある。** 見られたくないノートを
        捨てたとき、残っているのは捨てたことにならない。

        E-5 の片づけと同じ作法で、**数を見せてから**消す。
        """
        window = self._window
        entries = self.trash_entries()
        if not entries:
            # ここへ来るのは、メニューを開いてから Finder などで空にされたとき
            QMessageBox.information(window, "ゴミ箱は空です", "消すものはありません。")
            return 0

        answer = QMessageBox.question(
            window,
            "ゴミ箱を空にする",
            f"ゴミ箱の {len(entries)} 件を完全に削除しますか？\n"
            "この操作は取り消せません（もう戻せません）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 0

        if window._note is not None and window._note.path.is_relative_to(window._vault.trash_dir):
            window._close_current()
        for path in entries:
            window._watcher.suppress(path)
        removed = window._vault.empty_trash()
        window.refresh()
        window.notify(f"{len(removed)} 件を完全に削除しました")
        logger.info("ゴミ箱を空にした: %d 件", len(removed))
        return len(removed)

    def trash_entries(self) -> list[Path]:
        """ゴミ箱の中身（ノートも添付も）。

        **奥まで数える。** K-5 でゴミ箱は階層を保つので、直下だけを見ると
        サブフォルダから捨てたノートしか無いときに 0 件と判断し、
        「ゴミ箱を空にする」が押せなくなる。フォルダ自体は数えない
        （見せた数と消える数が食い違う）。
        """
        return [path for path in self._window._vault.trash_dir.rglob("*") if path.is_file()]

    # ------------------------------------------------------------- ピン留め

    def is_pinned(self, path: Path) -> bool:
        try:
            return self._window._vault.read(path).pinned
        except OSError:
            return False

    def toggle_pin(self, path: Path) -> bool:
        """ピン留めを反転する。反転後の状態を返す。

        開いているノートなら、先に保存してから本文を読み直す。
        ピン留めは front matter を書き換えるので、**エディタが古い本文の
        ままだと次の保存でピン留めが黙って消える**。
        """
        window = self._window
        current = window._note is not None and window._note.path == path
        if current:
            window.flush()
            # 保存でタイトルが変わるとファイル名も変わる（`_rename_if_title_changed`）。
            # 古いパスを掴んだままだと、存在しないファイルを読みに行く
            if window._note is not None:
                path = window._note.path
        if not path.is_file():
            return False

        window._watcher.suppress(path)
        note = window._vault.set_pinned(path, not self.is_pinned(path))
        window._db.upsert_note(note, window._vault.root)
        if current:
            window._reload_open_note(note)
        window.refresh()
        window._sync_favorite()  # 本文の左の星に映す（どの入口からでも）
        return note.pinned

    def toggle_pin_current(self) -> bool:
        window = self._window
        return False if window._note is None else self.toggle_pin(window._note.path)

    def _notify_pinned(self) -> None:
        """黙って無視すると、押し間違いなのか壊れたのか分からない。"""
        window = self._window
        window.notify(PINNED_NOTICE)

    # ------------------------------------------------------------- 名前の変更

    def prompt_rename(self, path: Path) -> Path | None:
        window = self._window
        try:
            current = window._vault.read(path).title
        except OSError:
            return None
        title, accepted = QInputDialog.getText(window, "名前を変更", "新しい名前", text=current)
        return self.rename_note(path, title) if accepted else None

    def rename_note(self, path: Path, title: str) -> Path:
        """タイトルを付け替える（ADR-0005）。

        **本文の見出しを書き換える。** タイトルは本文から導かれるので、
        ファイル名だけ変えても一覧の表示は変わらず、真実が 2 つになる。
        ファイル名は保存時に見出しへ追従する（`_rename_if_title_changed`）。

        開いているノートはエディタ経由で書き換える。本文の編集なので、
        打ち間違えたら `Cmd+Z` で戻せるべき。
        """
        window = self._window
        if not title.strip():
            return path
        if window._note is not None and window._note.path == path:
            return self._rename_open_note(title)
        return self._rename_stored_note(path, title)

    def _rename_open_note(self, title: str) -> Path:
        window = self._window
        renamed = with_title(window._editor.toPlainText(), title)
        if renamed != window._editor.toPlainText():
            cursor = window._editor.textCursor()
            cursor.beginEditBlock()
            try:
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(renamed)
            finally:
                cursor.endEditBlock()
            window._debouncer.touch()
        window.flush()
        return window._note.path if window._note is not None else Path()

    def _rename_stored_note(self, path: Path, title: str) -> Path:
        window = self._window
        try:
            renamed = with_title(path.read_text(encoding="utf-8"), title)
        except OSError:
            return path

        window._watcher.suppress(path)
        window._vault.write(path, renamed)

        target = window._vault.rename(path, title)
        if target != path:
            window._watcher.suppress(target)
            window._db.remove_path(window._vault.root, path)
        window._db.upsert_note(window._vault.read(target), window._vault.root)
        window.refresh()
        logger.info("名前を変えた: %s → %s", path.name, target.name)
        return target

    # --------------------------------------------------- 右クリックメニュー

    def show_sidebar_menu(self, point) -> None:
        window = self._window
        target = window._sidebar.filter_at(point)
        menu = self.sidebar_menu_for(target) if target is not None else None
        if menu is None:
            return
        menu.exec(window._sidebar.viewport().mapToGlobal(point))
        menu.deleteLater()

    def sidebar_menu_for(self, target: Filter) -> QMenu | None:
        """サイドバーの右クリックメニュー。**今はゴミ箱だけ**（G-3）。

        「すべて」や「お気に入り」に出せる操作が無いのに空のメニューを
        出すと、押せる何かがあると誤解させる。
        """
        if target.kind is FilterKind.SEARCH:
            menu = _new_menu(self._window)
            add_item(menu, "この検索を削除…").triggered.connect(
                lambda: self.delete_saved_search(target)
            )
            return menu
        if target.kind is FilterKind.FOLDER:
            menu = _new_menu(self._window)
            add_item(menu, "新しいフォルダ…").triggered.connect(lambda: self.create_folder(target))
            add_item(menu, "Finder で開く").triggered.connect(
                lambda: self.open_folder_in_finder(target)
            )
            # **「直下」には出さない。** 保管フォルダそのものは消せない
            if target.folder != ROOT_FOLDER:
                # **消すより先に並べる。** 直したいだけのときに削除を通らせない
                add_item(menu, "名前を変更…").triggered.connect(lambda: self.rename_folder(target))
                add_item(menu, "フォルダを削除…").triggered.connect(
                    lambda: self.delete_folder(target)
                )
            return menu
        if target.kind is not FilterKind.TRASH:
            return None
        menu = _new_menu(self._window)
        action = add_item(menu, "ゴミ箱を空にする…")
        action.triggered.connect(self.empty_trash)
        # **押してから断らない。** 件数は開く前に分かるので、押せない状態で
        # 見せる（一覧の「ゴミ箱へ移動」がピン留め時にそうなっているのと同じ）
        action.setEnabled(bool(self.trash_entries()))
        return menu

    def open_folder_in_finder(self, target: Filter) -> None:
        """フォルダを Finder で開く（ユーザー要望）。「直下」は保管フォルダ。"""
        window = self._window
        relative = "" if target.folder in (None, ROOT_FOLDER) else target.folder
        window.open_in_finder(window._vault.root / relative if relative else window._vault.root)

    def create_folder(self, target: Filter) -> Path | None:
        """選んだフォルダの中に新しいフォルダを作る（ユーザー要望）。

        「直下」を選んでいるときは vault 直下に作る。作ったフォルダは
        空でもサイドバーに出る（`Vault.folders` がディスクから引く）。
        """
        window = self._window
        parent = "" if target.folder in (None, ROOT_FOLDER) else target.folder
        where = parent or "保管フォルダ直下"
        name, accepted = QInputDialog.getText(window, "新しいフォルダ", f"{where} の中に作る名前")
        if not accepted or not name.strip():
            return None

        relative = f"{parent}/{name.strip()}" if parent else name.strip()
        try:
            created = window._vault.create_folder(relative)
        except FileExistsError:
            window.notify(f"同じ名前のフォルダがあります: {name.strip()}")
            return None
        except (ValueError, OSError) as error:
            logger.warning("フォルダを作れなかった: %s", error)
            window.notify(f"フォルダを作れませんでした: {error}")
            return None

        window.refresh()
        shown = created.relative_to(window._vault.root).as_posix()
        window.notify(f"フォルダ「{shown}」を作りました")
        logger.info("フォルダを作った: %s", shown)
        return created

    def rename_folder(self, target: Filter) -> Path | None:
        """フォルダの名前を変える（ユーザー要望）。変えた先を返す。

        **中身は動かさない**（`Vault.rename_folder`）が、**中のノートの
        パスは全部変わる**。索引・一覧・開いているノート・絞り込みが
        そろって追いつかないと、消えた場所へ自動保存が走る。
        """
        window = self._window
        folder = target.folder or ""
        current = folder.rsplit("/", 1)[-1]
        name, accepted = QInputDialog.getText(
            window, "フォルダの名前を変更", "新しい名前", text=current
        )
        if not accepted or not name.strip():
            return None

        was_open = window.current_note is not None and window.current_note.path.is_relative_to(
            window._vault.root / folder
        )
        window.flush()
        try:
            moved = window._vault.rename_folder(folder, name)
        except FileExistsError:
            window.notify(f"「{name}」は同じ名前のフォルダが既にあります")
            return None
        except (ValueError, OSError) as error:
            logger.warning("フォルダの名前を変えられなかった: %s", error)
            window.notify(f"名前を変えられませんでした: {error}")
            return None
        if moved == window._vault.root / folder:
            return moved  # 同じ名前。何も変わらない

        # **索引を引き直す。** 中のノートのパスが全部変わっている
        window._db.sync(window._vault)
        renamed = str(moved.relative_to(window._vault.root))
        if was_open and window.current_note is not None:
            # 古いパスのまま持っていると、消えた場所へ自動保存が走る
            window.open_and_select(moved / window.current_note.path.name)
        if window.filter.kind is FilterKind.FOLDER and window.filter.folder == folder:
            window.show_folder(renamed)  # 見ていたフォルダに追いつく
        else:
            window.refresh()
        window.notify(f"フォルダ「{folder}」を「{renamed}」にしました")
        logger.info("フォルダの名前を変えた: %s -> %s", folder, renamed)
        return moved

    def delete_folder(self, target: Filter) -> bool:
        """空のフォルダを消す（ユーザー要望）。消したら True。

        フォルダは空になっても残る仕様（ADR-0024 追記 2）なので、
        消す出口をここに用意する。**ノートが入っていたら消さない**
        （中身ごと消える操作は用意しない）。
        """
        window = self._window
        folder = target.folder or ""
        answer = QMessageBox.question(
            window, "フォルダを削除", f"フォルダ「{folder}」を削除しますか？"
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return False

        try:
            window._vault.delete_folder(folder)
        except ValueError as error:
            window.notify(f"削除できませんでした: {error}")
            return False
        except OSError as error:
            logger.warning("フォルダを削除できなかった: %s", error)
            window.notify(f"削除できませんでした: {error}")
            return False

        # 選んでいたフォルダが消えたときは、サイドバーが「すべて」へ戻す
        window.refresh()
        window.notify(f"フォルダ「{folder}」を削除しました")
        logger.info("フォルダを削除した: %s", folder)
        return True

    def delete_saved_search(self, target: Filter) -> bool:
        """保存した検索を消す（K-4）。消したら True。

        検索式は作り直せるがゴミ箱を経由しないので、確認だけ挟む。
        """
        window = self._window
        answer = QMessageBox.question(
            window, "検索を削除", f"保存した検索「{target.name}」を削除しますか？"
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return False
        window._config.saved_searches = [
            found for found in window._config.saved_searches if found.name != target.name
        ]
        window.reload_saved_searches()
        window.notify(f"検索「{target.name}」を削除しました")
        return True

    def reveal_note(self, path: Path) -> None:
        """Finder でそのノートを選んだ状態にする（ユーザー要望）。

        書き出しには付いていたのに、ノート本体には無かった。**素の `.md`
        として置いてある**のが売りなので、実物への道は近いほうがよい。
        """
        self._window.reveal_in_finder(path)

    def duplicate_note(self, path: Path) -> Path | None:
        """ノートを複製して開く（ユーザー要望）。作った先を返す。

        雛形として使い回すときに、今までは手作業だった（Finder で複製して
        名前を変えて見出しも直す）。

        **見出しも新しい名前に揃える。** 題名は本文の見出しなので、写した
        だけだと一覧に同じ名前が 2 つ並んで見分けが付かない。
        """
        window = self._window
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("複製できなかった: %s", path)
            return None

        # **元と同じフォルダに作る**（K-1）。分類して置いたノートの複製が
        # vault 直下に出ると、片方だけ箱から外れる
        folder = path.parent
        relative = folder.relative_to(window._vault.root)
        in_folder = relative.as_posix() if relative.parts else None
        # **先に sanitize してから空きを探す。** create も同じ順で計算する
        # ので、2 回の unique_path が必ず同じ答えになる。生の stem から
        # 探すと、手作りのファイル名（sanitize で変わる名前）で -2-2 の
        # 二重接尾や H1 とファイル名の乖離が起きる（コードレビュー指摘）
        target = unique_path(folder, sanitize_filename(path.stem), path.suffix)
        note = window._vault.create(target.stem, with_title(text, target.stem), folder=in_folder)
        # **作成系の後始末は 1 か所に任せる**（`_open_created` の注記どおり。
        # 直に開くと一覧の帯が前のノートに残る）
        window._open_created(note)
        logger.info("複製した: %s -> %s", path.name, note.path.name)
        return note.path

    def copy_note_link(self, path: Path) -> str:
        """`[[名前]]` の形でクリップボードへ入れる（ユーザー要望）。

        別のノートから指すときに、名前を打ち直さずに済む。**知らせを出す**
        （クリップボードは目に見えないので、入ったかどうかが分からない）。
        """
        link = f"[[{path.stem}]]"
        QApplication.clipboard().setText(link)
        self._window.notify(f"{link} をコピーしました")
        return link

    def show_context_menu(self, point) -> None:
        window = self._window
        relative = window._note_list.indexAt(point).data(NoteRole.PATH)
        if relative is None:
            return
        menu = self.context_menu_for(Path(relative))
        try:
            menu.exec(window._note_list.viewport().mapToGlobal(point))
        finally:
            # **枠を残さない**（ユーザー指摘 2026-08-29）。閉じたのに囲みが
            # 残ると、まだ何かの対象に見える
            window._note_list.clear_mark()
        menu.deleteLater()

    def context_menu_for(self, relative: Path) -> QMenu:
        """一覧の右クリックメニュー。ゴミ箱かどうかで中身が変わる。

        ゴミ箱の中身にピン留めや改名を許すと、戻したときの状態が読めない。
        ここで出せる操作を絞っておく。
        """
        window = self._window
        path = window._vault.root / relative
        menu = _new_menu(window)
        if window._filter.kind is FilterKind.TRASH:
            add_item(menu, "元に戻す").triggered.connect(lambda: self.restore_note(path))
            menu.addSeparator()
            # 「…」は「押すと確認が出る」の合図（他のメニューと揃える）
            add_item(menu, "完全に削除…").triggered.connect(lambda: self.delete_permanently(path))
            return menu

        label = "お気に入りから外す" if self.is_pinned(path) else "お気に入りに入れる"
        add_item(menu, label).triggered.connect(lambda: self.toggle_pin(path))
        add_item(menu, "名前を変更…").triggered.connect(lambda: self.prompt_rename(path))
        add_item(menu, "複製").triggered.connect(lambda: self.duplicate_note(path))
        add_item(menu, "テンプレートに登録…").triggered.connect(
            lambda: self.register_template(path)
        )
        add_item(menu, "フォルダへ移動…").triggered.connect(lambda: self.move_note_to_folder(path))
        menu.addSeparator()
        # 横の参照ペインへ（U-1）。**本文は入れ替えない**ので「開く」とは分ける
        add_item(menu, "横に開く").triggered.connect(lambda: window.open_beside(path))
        add_item(menu, "リンクをコピー").triggered.connect(lambda: self.copy_note_link(path))
        add_item(menu, "Finder で表示").triggered.connect(lambda: self.reveal_note(path))
        menu.addSeparator()
        trash = add_item(menu, "ゴミ箱へ移動")
        trash.triggered.connect(lambda: self.trash_note(path))
        # 項目ごと消すと理由が分からない。押せない状態で見せる
        trash.setEnabled(not self.is_pinned(path))
        return menu

    # ------------------------------------------------------------- テンプレート

    def move_note_to_folder(self, path: Path) -> Path | None:
        """ノートをフォルダへ移す（K-3 / ADR-0024）。移した先を返す。

        移動先は既存フォルダの一覧から選ぶか、**新しい名前を打てば
        その時フォルダが作られる**（editable なコンボ）。空フォルダは
        ツリーに見えないので、「新しいフォルダ」の入口はここに集約する。
        """
        window = self._window
        # ルートの合図（"."）は選択肢の文字として見せない。直下は
        # 先頭の ROOT_FOLDER_CHOICE が担う
        folders = [
            count.folder for count in window._db.folder_tree() if count.folder != ROOT_FOLDER
        ]
        items = [ROOT_FOLDER_CHOICE, *folders]
        current_folder = path.parent.relative_to(window._vault.root).as_posix()
        current = items.index(current_folder) if current_folder in items else 0

        choice, accepted = QInputDialog.getItem(
            window,
            "フォルダへ移動",
            "移動先（新しい名前を入力すると作成）",
            items,
            current,
            True,
        )
        if not accepted:
            return None
        folder = "" if choice.strip() in ("", ROOT_FOLDER_CHOICE) else choice.strip()

        return self.move_note_to(path, folder)

    def move_note_to(self, path: Path, folder: str) -> Path | None:
        """ノートをフォルダへ移す（対話なし）。移した先を返す。

        入口は 2 つ（右クリックの「フォルダへ移動…」と、サイドバーへの
        ドラッグ＆ドロップ）。**移動の後始末はここ 1 か所**に置く
        （索引の付け替え・一覧の更新・開いているノートの追従・行き先を
        開くこと）。片方だけに置くと、入口によって画面の動きが変わる。
        """
        window = self._window
        was_open = window.current_note is not None and window.current_note.path == path
        window.flush()
        window._watcher.suppress(path)
        try:
            moved = window._vault.move_note(path, folder)
        except (ValueError, OSError) as error:
            logger.warning("フォルダへ移動できなかった: %s", error)
            window.notify(f"移動できませんでした: {error}")
            return None
        if moved == path:
            return path  # 同じ場所。何も変わらない

        window._watcher.suppress(moved)
        window._db.remove_path(window._vault.root, path)
        note = window._vault.read(moved)
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        if was_open:
            window._note = note  # 開いているノートの居場所を追いかける
            window._remember_note(moved)
        # **行き先を開く**（ユーザー決定 2026-08-22）。元のフォルダで絞った
        # ままだと、移したノートが画面から消える。次に見たいのは行き先のほう
        window.show_folder(folder)
        window._note_list.select_path(moved.relative_to(window._vault.root))
        shown = folder or "保管フォルダ直下"
        window.notify(f"「{note.title}」を {shown} へ移動しました")
        logger.info("移動した: %s -> %s", path.name, moved)
        return moved

    def register_template(self, path: Path) -> Path | None:
        """ノートを雛形として登録する（ユーザー要望）。登録先を返す。

        名前を聞いてから `Vault.register_template` へ。同名の雛形が
        あるときは上書きの確認を出す（黙って潰さない）。
        """
        window = self._window
        name, accepted = QInputDialog.getText(
            window, "テンプレートに登録", "テンプレートの名前", text=path.stem
        )
        if not accepted or not name.strip():
            return None

        try:
            target = window._vault.register_template(path, name.strip())
        except FileExistsError:
            answer = QMessageBox.question(
                window,
                "同じ名前のテンプレートがあります",
                f"テンプレート「{name.strip()}」を上書きしますか？",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return None
            try:
                target = window._vault.register_template(path, name.strip(), overwrite=True)
            except (ValueError, OSError) as error:
                logger.warning("テンプレートに登録できなかった: %s", error)
                return None
        except (ValueError, OSError) as error:
            logger.warning("テンプレートに登録できなかった: %s", error)
            return None

        window.notify(f"テンプレート「{target.stem}」に登録しました")
        return target

    def new_from_template(self) -> bool:
        """`Cmd+Shift+N`。雛形を選んで新しいノートを作る（E-4）。

        **題名は聞かない。** 雛形の名前をそのまま題名にして、見出しを
        直せばファイル名が追いかける（ADR-0005）。ダイアログを 2 枚
        重ねるより、開いてすぐ書けるほうが速い。
        """
        window = self._window
        if not window._vault.templates():
            QMessageBox.information(
                window,
                "テンプレートがありません",
                f"「{window._vault.templates_dir}」に `.md` を置くと、ここから使えます。",
            )
            return False

        palette = Palette(
            window, placeholder="テンプレートを選ぶ…", theme=window._theme_watcher.colors
        )
        palette.set_provider(self._template_items)
        palette.chosen.connect(lambda item: self.create_from_template(item.path))
        palette.finished.connect(palette.deleteLater)
        palette.open_with()
        return True

    def delete_template(self) -> bool:
        """テンプレートを選んで削除する（ユーザー要望）。入口を開けたら True。

        新規作成と同じパレットで選び、**確認してから**消す。テンプレートは
        ゴミ箱を経由しない（ノートではないので「戻す」の導線が無い）ぶん、
        確認は必須。
        """
        window = self._window
        if not window._vault.templates():
            QMessageBox.information(
                window,
                "テンプレートがありません",
                "削除できるテンプレートがまだありません。",
            )
            return False

        palette = Palette(
            window,
            placeholder="削除するテンプレートを選ぶ…",
            theme=window._theme_watcher.colors,
        )
        palette.set_provider(self._template_items)
        palette.chosen.connect(lambda item: self.delete_template_at(item.path))
        palette.finished.connect(palette.deleteLater)
        palette.open_with()
        return True

    def delete_template_at(self, path: Path) -> bool:
        """確認してからテンプレートを消す。消したら True。"""
        window = self._window
        answer = QMessageBox.question(
            window,
            "テンプレートを削除",
            f"テンプレート「{path.stem}」を削除しますか？\n元に戻せません。",
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return False
        try:
            window._vault.delete_template(path)
        except (ValueError, OSError) as error:
            logger.warning("テンプレートを削除できなかった: %s", error)
            return False
        window.notify(f"テンプレート「{path.stem}」を削除しました")
        return True

    def choose_template_to_insert(self) -> Palette | None:
        """差し込む雛形を選ぶ（U-6）。選べる雛形が無ければ None。

        **空のパレットを出さない**（文体チェックと同じ作法）。何も無い
        ことが分かればよい。
        """
        window = self._window
        if window._note is None:
            return None
        if not window._vault.templates():
            window.notify(NO_TEMPLATE_NOTICE)
            return None

        palette = Palette(
            window,
            placeholder="差し込むテンプレートを選ぶ…",
            theme=window._theme_watcher.colors,
            compact=True,
        )
        palette.set_provider(self._template_items)
        palette.chosen.connect(lambda item: self.insert_template(item.path.stem))
        palette.finished.connect(palette.deleteLater)
        palette.open_with()
        return palette

    def insert_template(self, name: str) -> bool:
        """雛形を**いま書いている場所へ差し込む**（U-6）。差し込めたら True。

        **新しい概念を増やさない。** 短い定型（日付・署名・表の骨）は
        `templates/` の `.md` で足りる——「新しいノートを作る」だけでなく
        「ここへ差し込む」にも使えればよい。

        支度（front matter 外し・表の桁揃え・印の展開）は**新規作成と
        同じ `Vault.expand_template`** が行う。別に書くと「新規では
        埋まるのに差し込みでは埋まらない」が起きる（レビュー指摘
        2026-08-31）。

        **1 回の編集にする**（R5 と同じ約束）。2 段に割れると `Cmd+Z` が
        1 回で戻らない。
        """
        window = self._window
        if window._note is None:
            return False
        found = next(
            (path for path in window._vault.templates() if path.stem == name),
            None,
        )
        if found is None:
            logger.warning("テンプレートが無い: %s", name)
            return False
        try:
            filled = window._vault.expand_template(found, title=window._note.title)
        except (ValueError, OSError) as error:
            logger.warning("テンプレートを読めない: %s", error)
            window.notify("テンプレートを読めませんでした")
            return False

        cursor = window._editor.textCursor()
        # **選択の始まりを覚える**（レビュー指摘 2026-08-30）。`position()` は
        # 選択の**終わり**を指すので、置き換えたあとのカーソルが選んだ長さ
        # ぶん後ろへずれていた。差し込みは選択の始まりから始まる
        at = cursor.selectionStart()
        cursor.insertText(filled.text)  # 1 回の編集 = Undo 1 段
        if filled.cursor is not None:
            # `expand` が数えるのは Python の文字数、`setPosition` は UTF-16
            # （絵文字を挟むとずれる。新規作成の `_open_created` と同じ換算）
            cursor.setPosition(at + textpos.py_to_utf16(filled.text, filled.cursor))
            window._editor.setTextCursor(cursor)
        return True

    def create_from_template(self, path: Path) -> Note | None:
        """雛形からノートを作って開く（E-4）。作れなければ None。"""
        window = self._window
        window.flush()
        try:
            created = window._vault.create_from_template(path, folder=window.creation_folder())
        except (ValueError, OSError):
            logger.warning("テンプレートから作れなかった: %s", path)
            return None

        window._open_created(created.note, created.cursor)
        return created.note

    def open_daily_note(self, day: datetime | None = None) -> Note | None:
        """`Cmd+T`。今日のノートを開く。無ければ作る（E-4）。

        **同じ日に何度押しても同じノートを開く。** 増えると、どちらに
        書いたか分からなくなる。

        **題名で探してから作る**（ユーザー報告）。`Vault.daily_note()` は
        ファイル名だけを見るので、「日次」テンプレートから作ったノート
        （ファイルは `日次-2.md` のまま、題名だけ `2026-08-20`）を
        見つけられず、同じ日のノートをもう 1 つ作っていた。
        """
        window = self._window
        window.flush()
        found = self._note_titled(daily_title(day or datetime.now()))
        if found is not None:
            window.open_and_select(found)
            return window.current_note

        created = window._vault.daily_note(day)
        window._open_created(created.note, created.cursor)
        return created.note

    def _note_titled(self, title: str) -> Path | None:
        """その題名のノートの場所。無ければ `None`。

        **索引が持っているパスをそのまま使う。** 題名からファイル名を
        組み直すと、両者が食い違うノートで別のファイルを指す。
        """
        window = self._window
        for row in window._db.notes():
            if row.title == title:
                found = window._vault.root / row.path
                # **索引はキャッシュ（R9）。** watcher の反映前は実態と
                # ずれうる。消えたファイルを盲信すると、Cmd+T が開きも
                # 作りもしないで終わる（コードレビュー指摘）
                return found if found.exists() else None
        return None

    def open_adjacent_daily(self, *, forward: bool) -> bool:
        """前後の日次ノートを開く（ユーザー要望）。開けたら True。

        **既にあるものだけを辿る。** 書かなかった日にも空のノートを作ると、
        一覧が空ノートで埋まる。端まで来たら知らせるだけで動かない。

        **書かなかった日は飛ばす。** 1 日ずつ止まると、間が空いたときに
        何度も押すことになる。

        日次でないノートを見ているときは**今日**を基準にする。日誌の外から
        でも入れるようにするため。
        """
        window = self._window
        current = window.current_note.title if window.current_note is not None else None
        reference = (
            template.parse_daily(current or "") if current is not None else None
        ) or datetime.now().date()

        titles = [row.title for row in window._db.notes()]
        found = template.daily_neighbour(titles, reference, forward=forward)
        if found is None:
            window.notify("これより" + ("後" if forward else "前") + "の日のノートはありません")
            return False

        # **索引が見つけたノートを、そのパスのまま開く。** 題名から
        # ファイル名を組み直すと、食い違うノートで複製ができる（ユーザー報告）
        path = self._note_titled(found)
        if path is None:
            return False
        window.open_and_select(path)
        return True

    def _template_items(self, query: str) -> list[PaletteItem]:
        items = [
            PaletteItem(title=path.stem, subtitle=self._template_hint(path), path=path)
            for path in self._window._vault.templates()
        ]
        return fuzzy_filter(query, items)

    def _template_hint(self, path: Path) -> str:
        """一覧に出す 1 行。雛形の最初の見出しを使う。

        読めなければ空にする。**候補が出ないより、説明が無いほうがまし**。
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        for line in text.split("\n"):
            if line.startswith("#"):
                return line.lstrip("# ").strip()
        return ""

    # ------------------------------------------------------------- 仮身化

    def extract_selection(self) -> Path | None:
        """選択範囲を別のノートに切り出し、跡に `[[題名]]` を残す（M-1）。

        BTRON の仮身化。**リンクを打鍵ではなく操作にする**のが狙いで、
        行き先の名前を覚えていなくても繋がる（TASKS.md の M を参照）。
        """
        window = self._window
        editor = window.editor
        # R6。プリエディットは本文に入っていないので、ここで切ると
        # 変換中の文字が行方不明になる
        if editor.is_composing():
            return None
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            return None

        # **`selectedText()` の改行は U+2029。** そのまま渡すと見出しも
        # 箇条書きも 1 行に潰れる（Qt の古くからの落とし穴）
        selection = cursor.selectedText().replace("\u2029", "\n")
        found = extract.extract(selection, taken=window._db.titles())
        if found is None:
            return None

        # **作ってから消す。** 先に本文を書き換えると、作成が失敗したときに
        # 選んだ文がどこにも無くなる
        try:
            note = window._vault.create(found.title, found.text, folder=window._link_folder())
        except OSError as error:
            logger.warning("切り出せなかった: %s", error)
            window.notify("切り出せませんでした（置き場を確かめてください）")
            return None

        # **1 回の編集で置き換える。** 消してから挿すと Undo が 2 段になり、
        # `Cmd+Z` 1 回で戻らない（R5 / Phase 2 からの約束）
        cursor.insertText(found.link)

        window._db.upsert_note(note, window._vault.root)
        window.flush()  # 元のノートも索引へ（切り出し先のバックリンクに要る）
        window.refresh()
        # **開かない。** 執筆の途中に呼ぶ操作なので、書いている流れを切らない
        window.notify(f"「{found.title}」に切り出しました")
        logger.info("切り出した: %s", note.path.name)
        return note.path

    # ------------------------------------------------------------- 取り込み

    def import_note_files(self, paths: list[Path]) -> list[Path]:
        """一覧へドロップされた `.md` を vault へ取り込む（ユーザー要望 2026-08-18）。

        **元のファイルは触らない**（F 群の取り込みと同じ約束）。コピーして
        vault のノートにする。front matter もそのまま持ち込む（id が既存
        ノートと重複していても、索引が別ノートとして扱う）。名前が衝突
        したら連番。最後の 1 件を開く。
        """
        window = self._window
        added: list[Note] = []
        refused = 0
        for source in paths:
            if source.suffix.lower() not in MARKDOWN_SUFFIXES or not source.is_file():
                continue
            # **選んでいるフォルダへ入れる**（ユーザー要望 2026-08-23）。
            # 直下に置くと、絞り込み中の一覧に現れもせず「取り込んだのに
            # 出てこない」になる（新規作成と同じ作法）。
            #
            # **置き場は `Vault` に確かめさせる**（レビュー指摘）。ここで
            # 決めていたので、予約フォルダを指すリンクの中へノートが入って
            # いた。場所を決めるところからコピーまで**同じ `try` に入れる**
            # ——`mkdir` や `exists` の失敗が画面まで出ていた（実測）
            try:
                folder = window._vault.writable_folder(window.creation_folder())
                target = unique_path(folder, sanitize_filename(source.stem))
                window._watcher.suppress(target)
                shutil.copyfile(source, target)
            except (ValueError, OSError) as error:
                logger.warning("取り込めなかった（%s）: %s", source, error)
                refused += 1
                continue
            added.append(window._vault.read(target))

        if not added:
            if refused:  # **黙って何も起きないのがいちばん分かりにくい**
                window.notify("取り込めませんでした（置き場を確かめてください）")
            return []
        for note in added[:-1]:
            window._db.upsert_note(note, window._vault.root)
        window._open_created(added[-1])  # upsert・一覧更新・開く・選択まで
        message = f"{len(added)} 件のノートを取り込みました"
        if refused:
            message += f"（{refused} 件は取り込めませんでした）"
        window.notify(message)
        logger.info("ドロップから取り込んだ: %d 件", len(added))
        return [note.path for note in added]

    # ------------------------------------------------------------- 添付の片づけ

    def cleanup_attachments(self) -> int:
        """使っていない添付をゴミ箱へ移す（E-5）。移した数を返す。

        **手で走らせる。** 起動のたびに動かすと、参照の取りこぼしが
        「気づかないうちにファイルが動く」に直結する。件数を見せて、
        押したときだけ動かす。

        **書きかけの本文も数える。** 先に保存しないと、貼ったばかりの
        画像が「どこからも指されていない」ことになって消える。
        """
        window = self._window
        window.flush()
        orphans = window._vault.unused_attachments()
        if not orphans:
            QMessageBox.information(
                window,
                "片づけるものはありません",
                "どの添付もノートから使われています。",
            )
            return 0

        names = "\n".join(f"・{path.name}" for path in orphans[:CLEANUP_PREVIEW])
        if len(orphans) > CLEANUP_PREVIEW:
            names += f"\n…ほか {len(orphans) - CLEANUP_PREVIEW} 件"
        answer = QMessageBox.question(
            window,
            "使っていない添付を片づける",
            f"どのノートからも使われていない添付が {len(orphans)} 件あります。\n"
            f"ゴミ箱へ移しますか？（{window._config.trash_days} 日は戻せます）\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 0

        moved = window._vault.trash_attachments(orphans)
        window.notify(f"{len(moved)} 件をゴミ箱へ移しました")
        logger.info("使っていない添付を片づけた: %d 件", len(moved))
        return len(moved)
