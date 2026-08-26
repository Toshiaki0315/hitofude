"""保管フォルダが読めなくても起動する（ADR-0030 / 手動チェックの自動化）。

macOS は書類フォルダへの立ち入りを尋ねる。**断ると読めない**——そこで
落ちていた（ADR-0030。履歴の掃除が置き場を開けずに例外を上げていた）。

**図が出ないのは我慢できるが、起動しないのは我慢できない。** 読めない
ときは黙って諦め、**保管フォルダを選び直せる**ところまで進む。

`chmod` で読めない状態を作る（TCC の拒否そのものは作れないが、
アプリから見えるのは同じ「開けない」）。
"""

import os
import stat

import pytest

from hitofude.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def locked(config):
    """中身のある保管フォルダを**読めなく**する。"""
    root = config.vault_path
    root.mkdir(parents=True, exist_ok=True)
    (root / "会議メモ.md").write_text("# 会議メモ\n\n本文\n", encoding="utf-8")
    managed = root / ".hitofude" / "history"
    managed.mkdir(parents=True, exist_ok=True)
    (managed / "しるし").write_text("版", encoding="utf-8")

    root.chmod(0o000)
    yield config
    # **必ず戻す。** 戻さないと後片付けが消せず、次の実行に残る
    root.chmod(stat.S_IRWXU)


@pytest.mark.skipif(os.geteuid() == 0, reason="root は許可を無視して読めてしまう")
class TestStartsAnyway:
    def test_落ちずに窓ができる(self, locked, qtbot) -> None:
        """**これが本題。** 起動しないのがいちばん困る。"""
        window = MainWindow(locked)
        qtbot.addWidget(window)
        assert window.isEnabled()
        window.close()

    def test_一覧は空でも出る(self, locked, qtbot) -> None:
        """読めないのだから中身は出ない。**画面は出る。**"""
        window = MainWindow(locked)
        qtbot.addWidget(window)
        window.refresh()
        assert window.note_list.model().rowCount() == 0
        window.close()

    def test_設定を開ける(self, locked, qtbot) -> None:
        """**選び直す入口に辿り着ける。** ここが開かなければ行き止まり。"""
        from hitofude.ui.preferences import PreferencesDialog

        window = MainWindow(locked)
        qtbot.addWidget(window)
        try:
            dialog = PreferencesDialog(window._config, window)
            try:
                assert dialog.windowTitle() == "設定"
            finally:
                dialog.deleteLater()
        finally:
            window.close()

    def test_選び直せば元どおり使える(self, locked, qtbot, tmp_path) -> None:
        """**行き止まりにしない。** 保管フォルダの変更は次の起動から効く
        （設定に「再起動後」と出る作り）ので、選び直したあとの起動を見る。
        """
        window = MainWindow(locked)
        qtbot.addWidget(window)
        window.close()

        locked.vault_path = tmp_path / "べつの置き場"
        again = MainWindow(locked)
        qtbot.addWidget(again)
        try:
            note = again._vault.create("新しいノート", "# 新しいノート\n\n本文\n")
            assert note.path.is_file()
        finally:
            again.close()

    def test_開けないと知らせる(self, locked, qtbot) -> None:
        """**黙って空の一覧を出さない**（同期の失敗と同じ作法）。"""
        from hitofude.ui.main_window import LOCKED_VAULT_NOTICE

        window = MainWindow(locked)
        qtbot.addWidget(window)
        try:
            assert window.notice() == LOCKED_VAULT_NOTICE
        finally:
            window.close()

    def test_同期を押しても落ちない(self, locked, qtbot) -> None:
        """読めない場所を走査しにいっても、知らせて終わる（M-6）。"""
        window = MainWindow(locked)
        qtbot.addWidget(window)
        try:
            window.resync()
            window.wait_for_index_sync()
            qtbot.waitUntil(lambda: bool(window.notice()), timeout=5000)
        finally:
            window.close()
