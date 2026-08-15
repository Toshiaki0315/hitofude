# ADR-0006: ダークテーマは `QPalette` だけでは届かない

- **日付**: 2026-08-09
- **状態**: 採用
- **覆す対象**: spec.md §5.3「テーマ」（覆すのではなく**補う**）

## 背景

仕様書 §5.3 はこう定めている。

> 色は `theme.py` に `dataclass` で定義し、**`QPalette` とハイライタの両方に
> 流し込む**。

これを満たしても、環境設定の「テーマ」欄が**白地に薄いグレー**で読めなかった。

macOS では、ポップアップボタンのようなネイティブ部品の chrome を **OS が描く**。
`QPalette` の `Button` / `Base` を暗くしても chrome は明るいまま残り、
そこへパレットの**明るい文字色**（ダークテーマの `foreground`）が乗る。
結果として「明るい地に明るい文字」になる。

同じダイアログの中で経路が分かれていたのが分かりにくかった。入力欄
（`QFontComboBox` の編集部）が読めていたのは、あちらが `Base` / `Text` を使って
Qt 側で描かれるため。

## 決定

塗り替えるのをやめ、**アプリの外観そのものを macOS へ申告する**。

    NSApplication.sharedApplication.appearance =
        NSAppearance(named: NSAppearanceNameDarkAqua / NSAppearanceNameAqua)

テーマ設定に合わせて、起動時と変更時の両方で切り替える
（`hitofude/app.py` の `set_macos_appearance()`）。

`pyobjc` は足さない。`set_macos_app_name()` と `enable_key_repeat()` で使っている
ctypes の Objective-C 呼び出しを流用する。失敗しても外観が変わらないだけで、
アプリは動く。

## 根拠

`QPalette` に不足していた役割を足しても直らなかった、という実測が決め手。

| 役割 | 修正前 | `Button`/`ButtonText` を足した後 | 見た目 |
|---|---|---|---|
| `Button` | `#ececec` | `#1c1c1e` | 変わらず明るいまま |
| `ButtonText` | `#000000` | `#e8e8ea` | 変わらず読めないまま |

パレットに届く経路（Qt が描く）と届かない経路（OS が描く）がある、という
事実がここで確定した。外観を申告する側に切り替えたところ、
`NSAppearanceNameAqua` ↔ `NSAppearanceNameDarkAqua` が実際に切り替わり、
ユーザーの実機で読めるようになったことを確認している。

## 追記（2026-08-15）: 「システムに合わせる」ときは申告しない

**申告のやりすぎで、OS のダークモード切り替えに追従しなくなっていた**
（ユーザー報告: 起動中は変わらず、再起動するとダークで立ち上がる）。

Qt の `styleHints().colorScheme()` は **OS の設定ではなく NSApp の外観**を
読む。実測:

```
起動直後      : Light | NSApp: None
ダークに固定後: Dark  | NSApp: NSAppearanceNameDarkAqua
ライトに固定後: Light | NSApp: NSAppearanceNameAqua
```

起動時に申告すると、以後 Qt が見るのは**自分で入れた値**になる。OS を
切り替えても NSApp の外観は変わらないので `colorSchemeChanged` が飛ばない。
再起動したときだけ、まだ申告していない一瞬に正しい値を読めていた。

そこで **`ThemeMode.SYSTEM` のときは申告しない**（`setAppearance:` に nil を
渡して OS に委ねる）ことにした。申告しなければネイティブ部品も OS に
付いていくので、この ADR の目的（ネイティブ部品を揃える）は損なわれない。
申告が要るのは**ユーザーが OS と違う外観を選んだとき**だけである。

あわせて `ThemeWatcher.set_mode()` は**配色が同じでも通知する**ようにした。
「ダーク → システムに合わせる」と戻したとき、OS もダークなら配色は変わら
ないが、**申告を解く合図が要る**（黙っていると固定されたまま残る）。

## 影響

- **`QPalette` は引き続き必要。** Qt が描く部分（エディタ・一覧・サイドバー）は
  こちらで色を決める。外観の申告は置き換えではなく**両方要る**
- **申告するのは明示的にライト/ダークを選んだときだけ**（上の追記）
- 「テーマ」欄だけでなく、入力欄・ボタン・スクロールバー・メニューまで揃う
- `hitofude/app.py` に macOS 依存が 3 つ目として増えた
  （名前・キーリピート・外観）。いずれも ctypes で、失敗しても起動を止めない

## 検証できないこと

`QT_QPA_PLATFORM=offscreen` ではネイティブの chrome が描かれないため、
**見た目そのものを自動テストで確かめられない**。外観の名前が切り替わるところ
までが機械で見られる範囲で、実際の見え方は `docs/manual_test.md` §2 に送った。

パレットの側は「主要な役割が全部テーマ由来か」を
`tests/test_app.py::TestPaletteRoles` が見る。1 つでもシステムの既定が残ると
そこだけ浮くため、役割を個別に確かめるのではなく**まとめて**検査する。
今回の抜け（`Button` / `ButtonText`）はまさにその形だった。
