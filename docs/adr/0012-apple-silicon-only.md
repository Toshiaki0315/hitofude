# ADR-0012: 対象は Apple Silicon だけにする

- **日付**: 2026-08-16
- **状態**: 採用
- **覆す対象**: spec.md §1「対象OS: macOS 13 Ventura 以降（Apple Silicon / **Intel**）」

## 背景

ユーザーの判断。**Intel Mac は今後発売されない**ので、支える理由が薄い。

調べたところ、**ビルドした `.app` はもともと Apple Silicon でしか動かなかった**。
文書が実態と食い違っていた。

| 部品 | 対応 CPU |
|---|---|
| `Hitofude`（本体） | arm64 |
| 同梱の `Python.framework` | arm64 |
| PySide6 の `QtCore.abi3.so` | x86_64 / arm64（wheel が universal） |

PySide6 だけが両対応で、**それを載せる Python が arm64 のみ**。つまり
`.app` として配れば arm64 専用になる。Intel でも動かすには universal2 の
Python を用意して両方の環境で組み直す必要があり、`.app` は今の 367MB から
さらに膨らむ。

## 決定

**対象は Apple Silicon（arm64）のみ。** Intel は未サポートとする。

## 根拠

- **確かめられないものは支えられない。** Intel Mac が手元に無く、動作を
  検証できない。「たぶん動く」と書いた対応表は、動かなかったときに
  いちばん困る
- universal2 にすると `.app` がさらに大きくなる（PySide6 が 291MB を
  占めており、両対応にすればその大半が倍になる）
- **既に arm64 専用の成果物しか作っていない。** 決定は実態に合わせる
  ものであって、機能を削るものではない

## 影響

- spec.md §1 と README の対象 OS 表記から Intel を外した
- `docs/manual_test.md` の「Intel Mac で起動」は**対象外**（`[-]`）にした。
  残る未実施は署名・公証・DMG の 3 件（Developer ID 待ち）
- ビルド設定は変えていない。**もともと arm64 のものが出ていた**
- 将来 Intel を支えるなら、universal2 の Python を用意して
  `.app` を組み直すところからになる
