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

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox

from hitofude.app import apply_menu_font
from hitofude.core import template
from hitofude.core.document import Note, with_title
from hitofude.core.template import daily_title
from hitofude.storage.index_db import NoteRow
from hitofude.storage.vault import MARKDOWN_SUFFIXES, sanitize_filename, unique_path
from hitofude.ui.note_list import NoteRole
from hitofude.ui.quick_open import Palette, PaletteItem, fuzzy_filter
from hitofude.ui.sidebar import Filter, FilterKind

logger = logging.getLogger(__name__)

# 片づけの確認に並べる名前の数（E-5）。全部並べるとダイアログが画面を溢れる
CLEANUP_PREVIEW = 10

PINNED_NOTICE = "ピン留めしているノートは削除できません。先にピン留めを外してください。"


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
        for path in sorted(window._vault.trash_dir.glob("*.md")):
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
        window._vault.trash(path)
        window._db.remove_path(window._vault.root, path)
        window.refresh()
        return True

    def restore_note(self, path: Path) -> Path | None:
        """ゴミ箱から vault 直下へ戻す。戻した先を返す。

        **索引にも入れる。** ファイルを動かすだけでは一覧に出てこない。
        """
        window = self._window
        if not path.is_file():
            return None
        window._watcher.suppress(path)
        target = window._vault.restore(path)
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
        window._vault.delete_permanently(path)
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

        if window._note is not None and window._note.path.parent == window._vault.trash_dir:
            window._close_current()
        for path in entries:
            window._watcher.suppress(path)
        removed = window._vault.empty_trash()
        window.refresh()
        window.notify(f"{len(removed)} 件を完全に削除しました")
        logger.info("ゴミ箱を空にした: %d 件", len(removed))
        return len(removed)

    def trash_entries(self) -> list[Path]:
        """ゴミ箱の中身（ノートも添付も）。"""
        return [path for path in self._window._vault.trash_dir.glob("*") if path.is_file()]

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
        if target.kind is not FilterKind.TRASH:
            return None
        menu = QMenu(self._window)
        apply_menu_font(menu)
        action = menu.addAction("ゴミ箱を空にする…")
        action.triggered.connect(self.empty_trash)
        # **押してから断らない。** 件数は開く前に分かるので、押せない状態で
        # 見せる（一覧の「ゴミ箱へ移動」がピン留め時にそうなっているのと同じ）
        action.setEnabled(bool(self.trash_entries()))
        return menu

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

        target = unique_path(window._vault.root, path.stem, path.suffix)
        note = window._vault.create(target.stem, with_title(text, target.stem))
        window._db.upsert_note(note, window._vault.root)
        window.refresh()
        window.open_note(note.path)
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
        menu.exec(window._note_list.viewport().mapToGlobal(point))
        menu.deleteLater()

    def context_menu_for(self, relative: Path) -> QMenu:
        """一覧の右クリックメニュー。ゴミ箱かどうかで中身が変わる。

        ゴミ箱の中身にピン留めや改名を許すと、戻したときの状態が読めない。
        ここで出せる操作を絞っておく。
        """
        window = self._window
        path = window._vault.root / relative
        menu = QMenu(window)
        apply_menu_font(menu)
        if window._filter.kind is FilterKind.TRASH:
            menu.addAction("元に戻す").triggered.connect(lambda: self.restore_note(path))
            menu.addSeparator()
            # 「…」は「押すと確認が出る」の合図（他のメニューと揃える）
            menu.addAction("完全に削除…").triggered.connect(lambda: self.delete_permanently(path))
            return menu

        label = "ピン留めを外す" if self.is_pinned(path) else "ピン留め"
        menu.addAction(label).triggered.connect(lambda: self.toggle_pin(path))
        menu.addAction("名前を変更…").triggered.connect(lambda: self.prompt_rename(path))
        menu.addAction("複製").triggered.connect(lambda: self.duplicate_note(path))
        menu.addSeparator()
        menu.addAction("リンクをコピー").triggered.connect(lambda: self.copy_note_link(path))
        menu.addAction("Finder で表示").triggered.connect(lambda: self.reveal_note(path))
        menu.addSeparator()
        trash = menu.addAction("ゴミ箱へ移動")
        trash.triggered.connect(lambda: self.trash_note(path))
        # 項目ごと消すと理由が分からない。押せない状態で見せる
        trash.setEnabled(not self.is_pinned(path))
        return menu

    # ------------------------------------------------------------- テンプレート

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

        palette = Palette(window, placeholder="雛形を選ぶ…", theme=window._theme_watcher.colors)
        palette.set_provider(self._template_items)
        palette.chosen.connect(lambda item: self.create_from_template(item.path))
        palette.finished.connect(palette.deleteLater)
        palette.open_with()
        return True

    def create_from_template(self, path: Path) -> Note | None:
        """雛形からノートを作って開く（E-4）。作れなければ None。"""
        window = self._window
        window.flush()
        try:
            created = window._vault.create_from_template(path)
        except (ValueError, OSError):
            logger.warning("雛形から作れなかった: %s", path)
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
                return window._vault.root / row.path
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
        for source in paths:
            if source.suffix.lower() not in MARKDOWN_SUFFIXES or not source.is_file():
                continue
            target = unique_path(window._vault.root, sanitize_filename(source.stem))
            window._watcher.suppress(target)
            try:
                shutil.copyfile(source, target)
            except OSError:
                logger.warning("取り込めなかった: %s", source, exc_info=True)
                continue
            added.append(window._vault.read(target))

        if not added:
            return []
        for note in added[:-1]:
            window._db.upsert_note(note, window._vault.root)
        window._open_created(added[-1])  # upsert・一覧更新・開く・選択まで
        window.notify(f"{len(added)} 件のノートを取り込みました")
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
