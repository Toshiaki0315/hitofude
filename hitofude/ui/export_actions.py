"""書き出し・印刷・取り込みの束（spec §9 Phase 6 / E-2 / E-3 / F-2 / G-4）。

`MainWindow` から切り出した協調オブジェクト。1,900 行を超えた
main_window の責務を分けるためのもので、**挙動は変えない**。
ウィンドウの状態（開いているノート・エディタ・vault）には
`self._window` 経由で触る。同じパッケージ内の「友達」クラスとして、
window の内部属性へのアクセスを許している。

G-4 の知らせ（ステータスバーの「Finder で表示」ボタンとタイマ）は
書き出しの一部なので、部品ごとこちらが持つ。
"""

import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QToolButton

from hitofude.editor import exporter, importer, pptx_export

logger = logging.getLogger(__name__)

# 知らせを出しておく長さ。main_window の NOTICE_MS と揃える
# （循環 import を避けるため値をここに持つ。ずらしたいときは両方見ること）
NOTICE_MS = 5000


def short_path(path: Path) -> str:
    """ステータスバーに収まる長さにする。

    絶対パスはたいてい `/Users/名前/` で始まり、その分だけ肝心の場所が
    見えなくなる。**見えない知らせは無いのと同じ**なので `~` にする。
    """
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


class ExportActions:
    """書き出しの入口と G-4 の通知。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window
        self._exported: Path | None = None

        self.reveal_button = QToolButton(window)
        self.reveal_button.setText("Finder で表示")
        self.reveal_button.setAutoRaise(True)
        self.reveal_button.hide()
        self.reveal_button.clicked.connect(self._reveal_exported)
        window.statusBar().addPermanentWidget(self.reveal_button)

        self.export_timer = QTimer(window)
        self.export_timer.setSingleShot(True)
        self.export_timer.setInterval(NOTICE_MS)
        self.export_timer.timeout.connect(self.hide_notice)

    # ------------------------------------------------------------- 書き出し

    def export_markdown(self) -> Path | None:
        """Markdown のまま書き出す。変換を挟まない。"""
        return self._export("Markdown で書き出す", "Markdown (*.md)", ".md", self._write_markdown)

    def export_html(self) -> Path | None:
        """spec §9 Phase 6。R2 の例外はエクスポート層に閉じている。"""
        return self._export("HTML で書き出す", "HTML (*.html)", ".html", self._write_html)

    def export_pdf(self) -> Path | None:
        return self._export("PDF で書き出す", "PDF (*.pdf)", ".pdf", self._write_pdf)

    def export_pptx(self) -> Path | None:
        """PowerPoint で書き出す（F-5）。**ざっくり作って手で整える**前提。"""
        return self._export(
            "PowerPoint で書き出す", "PowerPoint (*.pptx)", ".pptx", self._write_pptx
        )

    def print_note(self) -> bool:
        """`Cmd+P`。印刷ダイアログを出す（C-9）。

        **macOS では `Cmd+P` は印刷が慣習。** ここは PDF 書き出しに
        割り当てていたが、印刷パネルから「PDF として保存」も選べるので、
        慣習に合わせても PDF への道は残る。書き出しはメニューにある。

        刷る前に保存する。書き出しと同じで、打った直後の内容が出ないと
        「今見えているもの」と違うものが出てしまう。
        """
        window = self._window
        if window._note is None:
            return False
        window.flush()
        printer = exporter.new_printer()
        dialog = QPrintDialog(printer, window)
        dialog.setWindowTitle("印刷")
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()  # exec() 後も親の子リストに残るため
        if not accepted:
            return False
        exporter.print_document(
            printer,
            window._editor.toPlainText(),
            theme=window._theme_watcher.colors,
            base_point_size=window._config.font_point_size,
            base_path=window._vault.root,
        )
        return True

    def preview_in_browser(self) -> None:
        """書き出さずに既定のブラウザで確認する（E-2）。

        **画面では図にならない Mermaid・数式・コードの色**が、ここで見える。
        押した時点の本文を書き出すので、直後の内容がそのまま出る。
        """
        window = self._window
        if window._note is None:
            return
        target = exporter.write_preview(
            window._editor.toPlainText(),
            theme=window._theme_watcher.colors,
            base_path=window._vault.root,
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def copy_as_html(self) -> None:
        """書式付きでクリップボードへ入れる（E-3）。メールやチャットへ貼る用。"""
        window = self._window
        if window._note is None:
            return
        exporter.copy_html(
            window._editor.toPlainText(),
            theme=window._theme_watcher.colors,
            base_path=window._vault.root,
        )

    def _export(self, caption: str, filter_: str, suffix: str, writer) -> Path | None:
        """保存先を尋ねて書き出す。`writer` は `(Path, str) -> Path`。"""
        window = self._window
        if window._note is None:
            return None
        window.flush()
        suggested = str(Path.home() / f"{window._note.title}{suffix}")
        chosen, _ = QFileDialog.getSaveFileName(window, caption, suggested, filter_)
        if not chosen:
            return None
        try:
            target = writer(Path(chosen), window._editor.toPlainText())
        except OSError:
            # ディスクフルや権限。黙って無反応だと「書けたのかどうか」が
            # 画面から分からない（G-4 と同じ理由で、失敗も知らせる）
            logger.warning("書き出せなかった: %s", chosen, exc_info=True)
            QMessageBox.warning(
                window,
                "書き出せませんでした",
                f"{short_path(Path(chosen))} に書き出せませんでした。\n"
                "保存先に書き込めるか、空き容量があるかを確かめてください。",
            )
            return None
        self._notify(target)
        return target

    def _write_markdown(self, target: Path, text: str) -> Path:
        return exporter.write_markdown(target, text)

    def _write_html(self, target: Path, text: str) -> Path:
        window = self._window
        return exporter.write_html(
            target,
            text,
            title=window._note.title if window._note else "",
            theme=window._theme_watcher.colors,
            base_path=window._vault.root,
        )

    def _write_pptx(self, target: Path, text: str) -> Path:
        return pptx_export.write_pptx(target, text, base_path=self._window._vault.root)

    def _write_pdf(self, target: Path, text: str) -> Path:
        window = self._window
        return exporter.write_pdf(
            target,
            text,
            theme=window._theme_watcher.colors,
            base_point_size=window._config.font_point_size,
            base_path=window._vault.root,
        )

    # ------------------------------------------------------------- 通知（G-4）

    def _notify(self, target: Path) -> None:
        """どこへ書いたかを見せ、Finder への道を添える（G-4）。

        **書き出しても画面が変わらなかった。** 保存先を選んだ直後、
        何も起きないように見えて、書けたのかどうかも分からない。

        知らせは残さない。前のファイルを指すボタンが居座ると、今のノートと
        関係のないものを開くことになる。
        """
        self._exported = target
        self._window.notify(f"{short_path(target)} に書き出しました")
        self.reveal_button.show()
        self.export_timer.start()

    def hide_notice(self) -> None:
        self.reveal_button.hide()
        self._exported = None

    def _reveal_exported(self) -> None:
        if self._exported is not None:
            self.reveal_in_finder(self._exported)

    def reveal_in_finder(self, path: Path) -> None:
        """Finder で場所を開き、そのファイルを選んだ状態にする（G-4）。

        **フォルダを開くだけにしない。** 同じ名前が並ぶ場所だと、どれを
        書いたのか分からない。`open -R` は選択まで面倒を見てくれる。

        書き出したあとに消された場合は何もしない（空振りさせない）。
        """
        if not path.exists():
            logger.info("書き出したファイルが見つからない: %s", path)
            return
        subprocess.run(["open", "-R", str(path)], check=False)

    # ------------------------------------------------------------- 取り込み

    def import_document(self) -> Path | None:
        """「ファイル」→「読み込む…」。資料をノートにして開く（F-2）。

        **元のファイルは触らない。** 読むだけで、移動も複製もしない。
        題名はファイル名を使う（`講演資料.pdf` → `講演資料`）。

        **読めなければノートを作らない。** 空のノートが増えるほうが困る。
        """
        window = self._window
        window.flush()
        chosen, _ = QFileDialog.getOpenFileName(
            window, "読み込む", str(Path.home()), importer.FILE_FILTER
        )
        if not chosen:
            return None

        source = Path(chosen)
        text = importer.to_markdown(source, save_image=window.save_attachment)
        if not text.strip():
            QMessageBox.warning(
                window,
                "読み込めませんでした",
                f"「{source.name}」から文字を取り出せませんでした。\n"
                "画像だけの資料や、保護されたファイルかもしれません。",
            )
            return None

        note = window._vault.create(source.stem, text)
        window._open_created(note)
        logger.info("取り込んだ: %s → %s", source.name, note.path.name)
        return note.path
