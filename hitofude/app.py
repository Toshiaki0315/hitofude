"""QApplication のセットアップとテーマ適用（spec §5.3）。"""

import logging
import sys
from typing import cast

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QToolTip

from hitofude import APP_NAME, ORG_DOMAIN, ORG_NAME, __version__
from hitofude.theme import ThemeColors, ThemeMode, colors_for
from hitofude.ui.icons import MENU_FONT_STEP

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
    "set_macos_app_name",
    "set_macos_appearance",
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

    **`QPalette` だけでは足りない。** ネイティブの部品（環境設定の
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
    # **ボタン系も忘れない。** ネイティブのポップアップボタン（環境設定の
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


def create_application(argv: list[str] | None = None) -> QApplication:
    """QApplication を用意する。

    QApplication は 1 プロセスに 1 つしか存在できないため、既にあれば再利用する
    （pytest-qt が先に生成しているケースがこれに当たる）。
    """
    # QApplication より先に。Qt はメニューバーを作るときにバンドル名を読む
    set_macos_app_name(APP_NAME)
    enable_key_repeat()

    existing = QApplication.instance()
    app = cast(QApplication, existing) if existing is not None else QApplication(argv or sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    app.setApplicationVersion(__version__)

    apply_chrome_font(app)
    apply_theme(app, colors_for(ThemeMode.SYSTEM, system_is_dark=system_is_dark()))
    return app


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
