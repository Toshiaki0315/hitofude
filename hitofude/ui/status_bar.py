"""ステータスバーの表示（C-5 / モード表示 / 文字数と行数）。

保存時刻・書き方のモード・分量の 3 つのラベルと、長い本文の集計を
背景へ回す仕組み（ユーザー要望）。`MainWindow` から切り出した
協調オブジェクトで、**挙動は変えない**。
"""

from datetime import datetime

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QLabel

from hitofude.core.stats import TextStats
from hitofude.core.stats import count as count_text
from hitofude.ui.index_sync import StatsReporter, StatsTask

# 文字数を数え直すまでの待ち。38,000 字のノートで 40ms 掛かる（実測）ので
# 1 打ごとには数えられない
STATS_DELAY_MS = 400

# この長さを超えたら、文字数の集計を背景へ回す（ユーザー要望）。
# **1 フレーム（16ms）に収まるうちはその場で数える。** 実測で
# 1,000 文字 1.5ms / 1 万文字 13.7ms / 1.3 万文字 17.0ms。短い本文を
# 投げると、返ってくるまでの往復のほうが長くつく
ASYNC_STATS_CHARS = 10_000

# ステータスバー右端の余白。ウィンドウの角が丸いので、右端ぴったりに置くと
# 最後の文字が欠ける（実際に欠けた）
STATUS_RIGHT_MARGIN = 14

# バーの高さ。既定のままだと歯車がつぶれて見えにくい（ユーザー指摘）
STATUS_BAR_HEIGHT = 32

# 一時通知を出す時間。showMessage の既定と同じ感覚
NOTICE_MS = 5000
STATS_TOOLTIP = "文字数と行数。\n装飾の記号（** など）と front matter、改行は数えません。"
MODE_TOOLTIP = "今入っている書き方のモード。\nRaw（⌘/）／ フォーカス（⇧⌘D）／ タイプライタ（⇧⌘Y）"


class StatusBarController:
    """3 つのラベルと集計の背景実行。`MainWindow` が薄く委譲する。"""

    def __init__(self, window) -> None:
        self._window = window
        window.statusBar().setMinimumHeight(STATUS_BAR_HEIGHT)
        # 左右に余白。端ぴったりだと窓の丸い角に埋もれる（ユーザー指摘。
        # 右端の余白は stats_label 側の STATUS_RIGHT_MARGIN も効く）
        window.statusBar().setContentsMargins(8, 0, 0, 0)

        # 一時通知（書き出した・取り込んだ等）。**showMessage を使わない。**
        # showMessage はバー左側の通常ウィジェットを一時的に隠すので、
        # 左に置いた歯車が通知のたびに消えてしまう
        self.notice_label = QLabel("", window)
        window.statusBar().addWidget(self.notice_label)
        self._notice_timer = QTimer(window)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self.notice_label.setText(""))

        self.mode_label = QLabel("", window)
        self.mode_label.setToolTip(MODE_TOOLTIP)
        window.statusBar().addPermanentWidget(self.mode_label)

        self.saved_label = QLabel("", window)
        self.saved_label.setToolTip("最後に保存した時刻。保存は自動で、打ち始めると消えます。")
        window.statusBar().addPermanentWidget(self.saved_label)

        self.stats_label = QLabel("", window)
        self.stats_label.setToolTip(STATS_TOOLTIP)
        self.stats_label.setContentsMargins(0, 0, STATUS_RIGHT_MARGIN, 0)
        window.statusBar().addPermanentWidget(self.stats_label)
        window.statusBar().setSizeGripEnabled(False)

        # **親を付けない。** ウィンドウの子にすると、ワーカーが結果を返す前に
        # ウィンドウごと破棄されて "Signal source has been deleted" で落ちる。
        # Python 側の参照（ここと QRunnable）が生存を保つ
        self.reporter = StatsReporter()
        self.reporter.counted.connect(self.on_stats_counted)
        self.token = 0

        self.stats_timer = QTimer(window)
        self.stats_timer.setSingleShot(True)
        self.stats_timer.setInterval(STATS_DELAY_MS)
        self.stats_timer.timeout.connect(self.update_stats)

    # ------------------------------------------------------------- 一時通知

    def show_notice(self, text: str, ms: int = NOTICE_MS) -> None:
        """一時通知。時間が経つと消える。"""
        self.notice_label.setText(text)
        self._notice_timer.start(ms)

    # ------------------------------------------------------------- 保存時刻

    def show_saved(self, at: "datetime | None") -> None:
        """保存済みの合図（C-5）。`None` で消す。

        **開いただけでは出さない。** まだ何も書いていないのに「保存しました」
        は嘘になる。打ち始めたら消す。
        """
        self.saved_label.setText(f"{at:%H:%M} に保存" if at is not None else "")

    def saved_text(self) -> str:
        return self.saved_label.text()

    # ------------------------------------------------------------- モード

    def mode_text(self) -> str:
        """今入っているモードの並び。何も入っていなければ空（ユーザー要望）。

        **有効なものだけ出す。** 「なし」と出しても場所を取るだけで、
        読む理由がない。Raw はツールバーを隠していると（`Cmd+3`）他に
        分かる場所が無いので、ここが唯一の手掛かりになる。
        """
        editor = self._window._editor
        modes = [
            ("Raw", editor.source_mode),
            ("フォーカス", editor.focus_mode),
            ("タイプライタ", editor.typewriter_mode),
        ]
        return " / ".join(name for name, active in modes if active)

    def update_modes(self) -> None:
        self.mode_label.setText(self.mode_text())

    # ------------------------------------------------------------- 分量

    def update_stats(self) -> None:
        """ステータスバーの「◯◯文字 / ◯◯行」を更新する。

        **長い本文は背景で数える**（ユーザー要望）。その場で数えると、
        打つ手を止めた 0.4 秒後に画面が 70ms（忙しいときは 285ms）止まる。
        数えるのは表示のためだけなので、待たせる理由がない。
        """
        window = self._window
        if window._note is None:
            self.stats_label.setText("")
            return

        text = window._editor.toPlainText()
        # 前に投げたぶんの結果を捨てるための合図
        self.token += 1
        if len(text) <= ASYNC_STATS_CHARS:
            self.show_stats(count_text(text))
            return
        QThreadPool.globalInstance().start(StatsTask(text, self.token, self.reporter))

    def on_stats_counted(self, token: int, stats: TextStats) -> None:
        """背景で数え終わった結果を出す。

        **古い結果は捨てる。** 数え終わる前に別のノートへ移れるので、
        遅れて届いた前のノートの数字を出すと、今見ているものと食い違う。
        """
        if self._window._closing or token != self.token:
            return
        self.show_stats(stats)

    def show_stats(self, stats: TextStats) -> None:
        self.stats_label.setText(f"{stats.characters:,} 文字 / {stats.lines:,} 行")

    def status_text(self) -> str:
        return self.stats_label.text()
