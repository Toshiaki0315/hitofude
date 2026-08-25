"""QApplication のセットアップとテーマ適用（spec §5.3）。"""

import logging
import sys
from pathlib import Path
from typing import cast

# QtWebEngine（Mermaid の描画・ADR-0021）は QApplication より先に import
# されている必要がある。忘れると WebEngine の初期化で警告や落ちが出る
import PySide6.QtWebEngineWidgets  # noqa: F401
from PySide6.QtCore import (
    QLibraryInfo,
    QLockFile,
    QObject,
    Qt,
    QTranslator,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QToolTip, QWidget

from hitofude import APP_NAME, ORG_DOMAIN, ORG_NAME, __version__
from hitofude.theme import ThemeColors, ThemeMode, colors_for

logger = logging.getLogger(__name__)

__all__ = [
    "APP_NAME",
    "ORG_DOMAIN",
    "ORG_NAME",
    "ThemeWatcher",
    "apply_theme",
    "create_application",
    "enable_key_repeat",
    "key_repeat_enabled",
    "macos_app_name",
    "macos_appearance",
    "menu_style",
    "set_macos_app_name",
    "set_macos_appearance",
    "style_menu",
    "system_is_dark",
]

BUNDLE_NAME_KEY = "CFBundleName"
# macOS は既定で、母音などを押し続けるとアクセント候補を出す。文章を書く
# アプリでは繰り返しのほうが要る
PRESS_AND_HOLD_KEY = "ApplePressAndHoldEnabled"
DARK_APPEARANCE = "NSAppearanceNameDarkAqua"
LIGHT_APPEARANCE = "NSAppearanceNameAqua"
CF_UTF8 = 0x08000100
NAME_BUFFER_BYTES = 512


def _core_foundation():
    """CoreFoundation を ctypes で開く。

    pyobjc を依存に足さないための措置。必要なのは 5 関数だけで、
    そのために 30MB 超のバインディングをバンドルに入れる価値はない。
    """
    import ctypes
    import ctypes.util

    path = ctypes.util.find_library("CoreFoundation")
    if path is None:
        return None

    cf = ctypes.cdll.LoadLibrary(path)
    pointer = ctypes.c_void_p
    cf.CFBundleGetMainBundle.restype = pointer
    cf.CFBundleGetInfoDictionary.restype = pointer
    cf.CFBundleGetInfoDictionary.argtypes = [pointer]
    cf.CFBundleGetValueForInfoDictionaryKey.restype = pointer
    cf.CFBundleGetValueForInfoDictionaryKey.argtypes = [pointer, pointer]
    cf.CFStringCreateWithCString.restype = pointer
    cf.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringGetCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFDictionarySetValue.argtypes = [pointer] * 3
    return cf


def _objc():
    """Objective-C ランタイムを ctypes で開く。

    `set_macos_app_name()` と同じ理由で pyobjc は足さない。
    """
    import ctypes
    import ctypes.util

    path = ctypes.util.find_library("objc")
    if path is None:
        return None

    runtime = ctypes.cdll.LoadLibrary(path)
    runtime.objc_getClass.restype = ctypes.c_void_p
    runtime.objc_getClass.argtypes = [ctypes.c_char_p]
    runtime.sel_registerName.restype = ctypes.c_void_p
    runtime.sel_registerName.argtypes = [ctypes.c_char_p]
    return runtime


def _send(runtime, target, selector: str, *args, types=(), returns=None):
    """`objc_msgSend` を型付きで呼ぶ。

    **引数と戻り値の型を毎回指定する。** 既定のままだとポインタとして
    扱われ、`BOOL` を渡したところで壊れる。
    """
    import ctypes

    signature = ctypes.CFUNCTYPE(
        returns or ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *types
    )
    call = signature(ctypes.cast(runtime.objc_msgSend, ctypes.c_void_p).value)
    return call(target, runtime.sel_registerName(selector.encode()), *args)


def _nsstring(runtime, text: str):
    import ctypes

    return _send(
        runtime,
        runtime.objc_getClass(b"NSString"),
        "stringWithUTF8String:",
        text.encode(),
        types=(ctypes.c_char_p,),
    )


def enable_key_repeat() -> bool:
    """押しっぱなしでキーが繰り返すようにする。

    macOS は既定で、母音などを押し続けると**アクセント候補**を出す
    （`ApplePressAndHoldEnabled`）。文章を書くアプリでは繰り返しのほうが要る。

    **`registerDefaults:` を使う。** 保存されている設定には触れないので、
    他のアプリにも次回以降の macOS の挙動にも影響しない。効くのはこの
    プロセスの間だけ。

    繰り返しの**速さ**は macOS のシステム設定（キーのリピート速度）で、
    アプリからは変えない。
    """
    if sys.platform != "darwin":
        return False
    try:
        import ctypes

        runtime = _objc()
        if runtime is None:
            return False

        defaults = _send(runtime, runtime.objc_getClass(b"NSUserDefaults"), "standardUserDefaults")
        disabled = _send(
            runtime,
            runtime.objc_getClass(b"NSNumber"),
            "numberWithBool:",
            False,
            types=(ctypes.c_bool,),
        )
        mapping = _send(
            runtime,
            runtime.objc_getClass(b"NSDictionary"),
            "dictionaryWithObject:forKey:",
            disabled,
            _nsstring(runtime, PRESS_AND_HOLD_KEY),
            types=(ctypes.c_void_p, ctypes.c_void_p),
        )
        _send(runtime, defaults, "registerDefaults:", mapping, types=(ctypes.c_void_p,))
        return True
    except Exception:
        # 繰り返さないだけ。起動を止める理由にはならない
        logger.debug("キーリピートを有効にできなかった", exc_info=True)
        return False


def key_repeat_enabled() -> bool:
    """押しっぱなしで繰り返す設定が**入っているか**。

    **`boolForKey:` だけでは足りない。** 未設定でも NO を返すため、
    「まだ登録していない」と「無効に登録した」を区別できない。
    macOS は未設定をアクセント候補ありとして扱うので、値の有無から見る。
    """
    if sys.platform != "darwin":
        return False
    try:
        import ctypes

        runtime = _objc()
        if runtime is None:
            return False

        defaults = _send(runtime, runtime.objc_getClass(b"NSUserDefaults"), "standardUserDefaults")
        key = _nsstring(runtime, PRESS_AND_HOLD_KEY)
        if not _send(runtime, defaults, "objectForKey:", key, types=(ctypes.c_void_p,)):
            return False  # 未設定 = macOS の既定（アクセント候補が出る）

        held = _send(
            runtime,
            defaults,
            "boolForKey:",
            key,
            types=(ctypes.c_void_p,),
            returns=ctypes.c_bool,
        )
        return not held
    except Exception:
        logger.debug("キーリピートの設定を読めなかった", exc_info=True)
        return False


def set_macos_appearance(*, dark: bool | None) -> bool:
    """アプリが明るい/暗いどちらの外観かを macOS へ伝える。`None` で解除。

    **`QPalette` だけでは足りない。** ネイティブの部品（設定の
    ポップアップボタンなど）は OS が chrome を描くので、こちらが背景色を
    指定しても明るいまま残る。そこへパレットの明るい文字色が乗って、
    白地に薄いグレーで読めなくなっていた（ユーザー報告）。

    塗り替えるのではなく**アプリの外観そのものを申告する**のが筋で、
    ネイティブ部品がまとめて追従する。

    **`None`（＝ OS に任せる）を忘れてはいけない。** Qt の
    `styleHints().colorScheme()` は OS の設定ではなく **NSApp の外観**を
    読む（実測）。固定したままだと、以後 Qt が見るのは自分で入れた値に
    なり、OS を切り替えても `colorSchemeChanged` が飛ばない。
    「システムに合わせる」ときは固定しないこと。
    """
    if sys.platform != "darwin":
        return False
    try:
        import ctypes

        runtime = _objc()
        if runtime is None:
            return False

        appearance = None
        if dark is not None:
            wanted = _nsstring(runtime, DARK_APPEARANCE if dark else LIGHT_APPEARANCE)
            appearance = _send(
                runtime,
                runtime.objc_getClass(b"NSAppearance"),
                "appearanceNamed:",
                wanted,
                types=(ctypes.c_void_p,),
            )
            if not appearance:
                return False

        application = _send(runtime, runtime.objc_getClass(b"NSApplication"), "sharedApplication")
        # nil を渡すと「OS に従う」に戻る
        _send(runtime, application, "setAppearance:", appearance, types=(ctypes.c_void_p,))
        return True
    except Exception:
        # 外観が変わらないだけ。アプリを落とす理由にはならない
        logger.debug("外観を切り替えられなかった", exc_info=True)
        return False


def macos_appearance() -> str | None:
    """いまアプリが名乗っている外観。確認用。"""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        runtime = _objc()
        if runtime is None:
            return None

        application = _send(runtime, runtime.objc_getClass(b"NSApplication"), "sharedApplication")
        appearance = _send(runtime, application, "appearance")
        if not appearance:
            return None
        name = _send(runtime, appearance, "name")
        text = _send(runtime, name, "UTF8String", returns=ctypes.c_char_p)
        return text.decode() if text else None
    except Exception:
        logger.debug("外観を読めなかった", exc_info=True)
        return None


def set_macos_app_name(name: str = APP_NAME) -> bool:
    """メニューバー先頭とドックに出る名前を差し替える。

    `python -m hitofude` で動かすと、主バンドルが Python.framework の
    `Python.app` になる（実測）。Qt は `qt_mac_applicationName()` で
    そのバンドルの `CFBundleName` を読むため、メニューが "Python" になる。
    `QApplication.setApplicationName()` では直らない。**バンドルの値のほうが
    優先される**ので、直すならバンドル側を書き換えるしかない。

    `CFBundleGetInfoDictionary()` が返す辞書は可変で、書き込むと Qt が読む
    `CFBundleGetValueForInfoDictionaryKey()` にも反映される（実測で確認）。

    **メニューバーが作られる前**に呼ぶこと。`.app` として起動したときは
    Info.plist が既に "Hitofude" なので、同じ値を書くだけで何も変わらない。
    """
    if sys.platform != "darwin":
        return False
    try:
        cf = _core_foundation()
        if cf is None:
            return False
        bundle = cf.CFBundleGetMainBundle()
        info = cf.CFBundleGetInfoDictionary(bundle) if bundle else None
        if not info:
            return False
        cf.CFDictionarySetValue(
            info,
            cf.CFStringCreateWithCString(None, BUNDLE_NAME_KEY.encode(), CF_UTF8),
            cf.CFStringCreateWithCString(None, name.encode(), CF_UTF8),
        )
        return True
    except Exception:
        # 名前が変わらないだけ。起動を止める理由にはならない
        logger.debug("メニューバーのアプリ名を差し替えられなかった", exc_info=True)
        return False


def macos_app_name() -> str | None:
    """主バンドルが名乗っている名前。Qt が読むのと同じ口から取る。"""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        cf = _core_foundation()
        if cf is None:
            return None
        bundle = cf.CFBundleGetMainBundle()
        if not bundle:
            return None
        key = cf.CFStringCreateWithCString(None, BUNDLE_NAME_KEY.encode(), CF_UTF8)
        value = cf.CFBundleGetValueForInfoDictionaryKey(bundle, key)
        if not value:
            return None
        buffer = ctypes.create_string_buffer(NAME_BUFFER_BYTES)
        if not cf.CFStringGetCString(value, buffer, NAME_BUFFER_BYTES, CF_UTF8):
            return None
        return buffer.value.decode("utf-8")
    except Exception:
        logger.debug("バンドル名を読めなかった", exc_info=True)
        return None


def system_is_dark() -> bool:
    """OS がダークモードかどうか。

    macOS のダークモード切り替えは `styleHints().colorSchemeChanged` で検知できる
    （Phase 2 で接続する）。ここでは現在値だけを読む。
    """
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


# ポップアップメニューの寸法（ユーザー指摘 2026-08-24）。Qt が描く既定は
# macOS のメニューより行が詰まっていて角も立っている。**押す前に読むもの**
# なので、OS のメニューと並べても浮かない余白と丸みにする
MENU_RADIUS = 10
"""メニューの角の丸み（px）。macOS のメニューに合わせた。"""

MENU_ITEM_RADIUS = 6
"""選んでいる行の丸み（px）。角の丸いメニューに角ばった帯は合わない。"""

MENU_PADDING = 5
"""メニューの上下の余白（px）。角丸のぶん、内側にも余白が要る。"""

MENU_ITEM_PADDING = (6, 24, 6, 6)
"""行の余白（上・右・下・左、px）。右は矢印とショートカットのぶん広い。"""


def menu_style(theme: ThemeColors) -> str:
    """ポップアップメニューの見た目（ユーザー指摘 2026-08-24）。

    メニューは Qt が描いていて、既定では行が詰まり角も立っている。
    余白と丸みは QPalette では決められないので QSS で書く。

    **アプリ全体には置かない。** 描画は変わらない（本体の窓を 256 万画素
    比べて差 0）が、`QApplication.setStyleSheet()` はすべてのウィジェットを
    QSS 経由の描画に切り替えるため**とても高い**（同じ試験が 5 秒 → 53 秒。
    実測）。開くたびに 1 つのメニューへ当てる（`style_menu`）。

    サブメニューは親の QSS を受け継ぐので、親に当てれば足りる。
    """
    top, right, bottom, left = MENU_ITEM_PADDING
    return f"""
    QMenu {{
        background-color: {theme.background};
        color: {theme.foreground};
        border: 1px solid {theme.rule};
        border-radius: {MENU_RADIUS}px;
        padding: {MENU_PADDING}px 0px;
    }}
    QMenu::item {{
        padding: {top}px {right}px {bottom}px {left}px;
        margin: 0px {MENU_PADDING}px;
        border-radius: {MENU_ITEM_RADIUS}px;
    }}
    QMenu::item:selected {{
        background-color: {theme.selection_background};
        color: {theme.foreground};
    }}
    QMenu::item:disabled {{ color: {theme.muted_foreground}; }}
    QMenu::icon {{ padding-left: 10px; }}
    QMenu::separator {{
        height: 1px;
        background-color: {theme.rule};
        margin: {MENU_PADDING}px 12px;
    }}
    """


def style_menu(menu: QWidget, theme: ThemeColors) -> None:
    """1 つのポップアップメニューに見た目を当てる。

    **開くところで呼ぶ。** アプリ全体に置くと描画の経路が丸ごと変わって
    重い（`menu_style` の説明）。メニューは右クリックのたびに作り直す
    ので、ここで当てれば常に今のテーマになる。
    """
    menu.setStyleSheet(menu_style(theme))


def apply_theme(app: QApplication, theme: ThemeColors) -> None:
    """配色を QPalette へ流し込む。"""
    background = QColor(theme.background)
    foreground = QColor(theme.foreground)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.WindowText, foreground)
    palette.setColor(QPalette.ColorRole.Base, background)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.code_background))
    palette.setColor(QPalette.ColorRole.Text, foreground)
    palette.setColor(QPalette.ColorRole.ToolTipBase, background)
    palette.setColor(QPalette.ColorRole.ToolTipText, foreground)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.muted_foreground))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.selection_background))
    palette.setColor(QPalette.ColorRole.HighlightedText, foreground)
    palette.setColor(QPalette.ColorRole.Link, QColor(theme.accent))
    # **ボタン系も忘れない。** ネイティブのポップアップボタン（設定の
    # 「テーマ」欄など）はここで描かれる。既定のままだと明るい chrome に
    # 明るい文字が乗って読めなくなる
    palette.setColor(QPalette.ColorRole.Button, background)
    palette.setColor(QPalette.ColorRole.ButtonText, foreground)

    # 無効な項目。既定のままだと暗い背景に黒い文字が乗って消える
    muted = QColor(theme.muted_foreground)
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
    app.setPalette(palette)


_TRANSLATORS: list[QTranslator] = []
"""読み込んだ翻訳。**参照を持ち続ける。** Qt は所有しないので、捨てると
その場で英語に戻る（Python が回収する）。"""

# 読む順に意味がある。あとに入れたものが先に引かれるので、細かいほうを後に
_CATALOGS = ("qt_ja", "qtbase_ja")


def install_translations(app: QApplication) -> list[QTranslator]:
    """Qt が出す言葉を日本語にする（ユーザー要望）。

    本文の右クリックは **Qt の標準メニュー**（Undo / Cut / Paste …）で、
    アプリの言葉と混ざって英語で出ていた。翻訳のカタログは PySide6 に
    同梱されているので、読み込んで当てるだけでよい。

    **二度読み込まない。** 設定を触るたびに呼ばれても積み上がらないよう、
    一度入れたらそれを返す。
    """
    if _TRANSLATORS:
        return _TRANSLATORS

    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in _CATALOGS:
        translator = QTranslator(app)
        if translator.load(name, directory):
            app.installTranslator(translator)
            _TRANSLATORS.append(translator)
        else:
            logger.info("翻訳を読めなかった: %s", name)
    return _TRANSLATORS


def create_application(argv: list[str] | None = None) -> QApplication:
    """QApplication を用意する。

    QApplication は 1 プロセスに 1 つしか存在できないため、既にあれば再利用する
    （pytest-qt が先に生成しているケースがこれに当たる）。
    """
    # QApplication より先に。Qt はメニューバーを作るときにバンドル名を読む
    set_macos_app_name(APP_NAME)
    enable_key_repeat()

    existing = QApplication.instance()
    if existing is None:
        # QtWebEngine の前提（ADR-0021）。QApplication を作る前に立てる
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = cast(QApplication, existing) if existing is not None else QApplication(argv or sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    app.setApplicationVersion(__version__)

    install_translations(app)
    apply_chrome_font(app)
    # **テーマより先に。** `setStyle()` はパレットを標準へ戻す
    apply_tooltip_margin(app)
    apply_tooltip_colors()
    apply_theme(app, colors_for(ThemeMode.SYSTEM, system_is_dark=system_is_dark()))
    return app


# ポップアップメニューの文字を大きくする量（ユーザー要望）。並び順・
# 一覧の右クリック・サイドバーの右クリックは**押す前に読むもの**で、
# 既定の大きさでは小さかった。画面上部のメニューバーは OS が描くので
# こちらからは変えられない
MENU_FONT_STEP = 2


def apply_menu_font(menu: QWidget) -> None:
    """ポップアップメニューの文字を `MENU_FONT_STEP` だけ大きくする。

    **親の大きさから決める。** 数字を直に置くと、本文フォントの設定を
    変えたときに置いていかれる。
    """
    font = QFont(menu.font())
    font.setPointSizeF(font.pointSizeF() + MENU_FONT_STEP)
    menu.setFont(font)


TOOLTIP_BACKGROUND = "#1F1F22"
"""ツールチップの地の色（ユーザー要望 2026-08-24）。

**テーマでは変えない。** 黒地に白は明るいテーマでも暗いテーマでも読めるし、
本文と同じ色で出すと「浮いている小さな窓」に見えず下の文字と混ざる。
"""

TOOLTIP_FOREGROUND = "#FFFFFF"
"""ツールチップの文字の色。"""


TOOLTIP_MARGIN = 7
"""ツールチップの内側の余白（px。ユーザー要望 2026-08-24）。

Qt の既定は 0 で、文字が縁に貼り付いて窮屈に見える。
"""


class _RoomyTooltipStyle(QProxyStyle):
    """ツールチップにだけ余白を足すスタイル。

    **Qt はこの余白をスタイルの寸法値から取る**（`QTipLabel` が作られる
    ときに `PM_ToolTipLabelFrameWidth` を読んで内側の余白にする）。
    そこだけ差し替えれば、スタイルシートを使わずに余裕を作れる。

    他の寸法は元のスタイルへそのまま渡す（実測: 窓の描画は 256 万画素中
    64 画素しか変わらない＝縁の丸め誤差、打鍵は 0.9ms → 1.1ms）。
    """

    def pixelMetric(self, metric, option=None, widget=None) -> int:
        if metric == QStyle.PixelMetric.PM_ToolTipLabelFrameWidth:
            return TOOLTIP_MARGIN
        return super().pixelMetric(metric, option, widget)


def apply_tooltip_margin(app: QApplication) -> None:
    """ツールチップの内側に余白を作る（ユーザー要望 2026-08-24）。

    **テーマを当てるより先に呼ぶ。** `setStyle()` はパレットを標準へ
    戻すので、あとから入れると配色が飛ぶ（実測: 窓の 11% の画素が変わった）。

    **入れ直さない。** 既に入っていれば何もしない（二重に包むと
    寸法の問い合わせが Python を 2 回通る）。
    """
    if isinstance(app.style(), _RoomyTooltipStyle):
        return
    app.setStyle(_RoomyTooltipStyle(app.style()))


def apply_tooltip_colors() -> None:
    """ツールチップを黒地に白にする（ユーザー要望 2026-08-24）。

    **`QToolTip` のパレットで塗る。スタイルシートは使わない。** 角丸と
    余白は QSS でしか書けないが、置ける場所がどこも壊れる:

    - `QApplication.setStyleSheet()` … 既にあるウィジェットを全部塗り直す。
      長い走行では**消えかけの相手まで塗り直して落ちる**（実測 segfault）
    - 窓に置く … その窓の中の**パレットの伝播が止まる**。テーマを暗くしても
      サイドバーと一覧が明るいままになった（既存の試験 5 件が捕まえた）

    角の丸みはここでは作れなかった。Qt はツールチップの窓を不透明に
    描くので、丸くするには出るたびに `WA_TranslucentBackground` を
    入れ直すしかなく、その足がかり（アプリ全体のイベントフィルタ）は
    **空でも**この試験群を落とす（PySide が消えかけの相手まで包むため）。
    そこで丸みは **Qt に描かせない**ことで実現した——`ui/tooltip.py` が
    自前の窓を描き、採用（`adopt`）したウィジェットではそちらが出る。
    ここの色とこの下の余白は、**採用していない場所に出るネイティブ**の保険。

    パレットなら壊れた 3 つの道のどれにも触らない。テーマを変えても残る（実測）。
    """
    palette = QToolTip.palette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(TOOLTIP_BACKGROUND))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TOOLTIP_FOREGROUND))
    QToolTip.setPalette(palette)


def apply_chrome_font(app: QApplication) -> None:
    """本文以外の文字（今はツールチップ）の大きさを決める。

    **ツールチップはアプリ全体で 1 つの設定**（`QToolTip.setFont`）。
    ボタンごとに当てて回る必要はないし、当てて回ると必ず当て漏れる。

    ポップアップメニューと同じだけ大きくする（`MENU_FONT_STEP`）。どちらも
    **押す前に読むもの**で、揃っていないほうが不自然に見える。
    """
    font = QFont(app.font())
    font.setPointSizeF(font.pointSizeF() + MENU_FONT_STEP)
    QToolTip.setFont(font)


class ThemeWatcher(QObject):
    """現在の配色を保持し、変わったときに通知する（spec §5.3）。

    `ThemeMode.SYSTEM` のときだけ OS のダークモード切り替えに追従する。
    ユーザーが明示的にライト/ダークを選んでいたら、OS が変わっても動かさない。

    配色の決定自体は GUI 非依存の `theme.colors_for()` が行い、ここは
    Qt のシグナルと繋ぐだけに留める。
    """

    changed = Signal(object)
    """新しい `ThemeColors` を載せて飛ぶ。"""

    def __init__(self, mode: ThemeMode = ThemeMode.SYSTEM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._colors = colors_for(mode, system_is_dark=system_is_dark())
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_qt_scheme_changed)

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    def set_mode(self, mode: ThemeMode) -> None:
        """テーマの選択を変える。

        **配色が同じでも通知する。** 受け手は macOS への外観の申告を
        出し直す（`MainWindow._apply_palette`）。「ダーク → システムに
        合わせる」と戻したとき、OS もダークなら配色は変わらないが、
        **固定を解かないと OS の切り替えに追従しなくなる**（ユーザー報告）。
        """
        if mode is self._mode:
            return  # 何も変わらない。無駄な rehighlight() を増やさない（R7）
        self._mode = mode
        self._colors = colors_for(mode, system_is_dark=system_is_dark())
        self.changed.emit(self._colors)

    def _on_qt_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        self._on_system_scheme_changed(is_dark=scheme == Qt.ColorScheme.Dark)

    def _on_system_scheme_changed(self, *, is_dark: bool) -> None:
        self._update(colors_for(self._mode, system_is_dark=is_dark))

    def _update(self, colors: ThemeColors) -> None:
        # 同じ配色なら通知しない。受け手は rehighlight() するので、
        # 無駄な通知がそのまま全体再ハイライトになる（R7）。
        if colors is self._colors:
            return
        self._colors = colors
        self.changed.emit(colors)


def acquire_vault_lock(managed_dir: Path) -> QLockFile | None:
    """vault 単位の二重起動ロック（H-1 層 2 / spec §6.1）。

    同じ vault を 2 つのウィンドウで開くと、watcher が互いの保存に反応し、
    競合ダイアログが行き来する。取れたら `QLockFile` を返すので、
    **アプリが生きている間は参照を保持し続けること**（手放すと GC で
    ロックが外れる）。取れなければ None。

    ロックは `.hitofude/` 内 = 捨ててよい（R9）。クラッシュの残骸は
    QLockFile が PID の死活で自動回収する。時間による stale 判定は
    切る（アプリは何時間でも開きっぱなしになる）。
    """
    managed_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(managed_dir / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        return None
    return lock
