# ADR-0021: Mermaid ブロックをエディタ内で図にして表示する

日付: 2026-08-19
状態: 採用（ADR-0020 の続き。TASKS これから I-1 の残り半分）

## 文脈

```mermaid のフェンスは HTML 書き出し（B-4）でだけ図になっていた。
インライン展開の壁は QtWebEngine（+200MB）と見ていたが、実測で
**pyside6 メタパッケージが Addons ごと同梱しており支払い済み**と判明
（ADR-0020）。残る判断は JS アセットの扱いだけで、それも書き出し用に
**mermaid.min.js v11.16.1 が resources/vendor/ に同梱済み**だった。
新しい依存もダウンロードも実は不要で、同じファイルを実行するだけでよい。

## 決定

- 描画は `editor/mermaid_cache.py`。隠した QWebEngineView（Chromium）で
  同梱の mermaid.min.js を実行し、SVG を描かせて `grab()` で QPixmap に
  する。**ネットには繋がない**（JS もフォントも手元のもの）
- **描画は非同期**（1 枚 数百 ms〜1 秒台）。キャッシュは 3 状態:
  未依頼（頼んで None）/ 依頼中（None）/ 完了（絵、または失敗の記録）。
  出来るまでは生のまま見せ、`rendered` シグナルで該当ブロックだけ
  掛け直す（R7）
- 表示は数式（ADR-0020）と同じ: フェンスの行を 0.5pt に潰して高さを
  予約し、絵は paintEvent。リビールはブロック全体
- Chromium は**図のあるノートを開いて初めて**立ち上げる（遅延生成）。
  図を使わない人に起動コストを払わせない
- QtWebEngine は QApplication より先の import が必須。app.py と
  tests/conftest.py が済ませる（AA_ShareOpenGLContexts も同時に立てる）

## 実装の落とし穴（実測）

- **show() していない QWebEngineView は描画されず、grab() が無地になる。**
  `WA_DontShowOnScreen` を立てて show() する（画面には出ない）
- **GPU 合成でも grab() が真っ白になる**（実機 cocoa で再現。offscreen の
  テストはもともとソフトウェア描画なので気づけない）。Chromium が
  立ち上がる前に `--disable-gpu` を入れてソフトウェア描画に固定する。
  図のスナップショット用途に GPU は要らない
- 透明背景は grab で白に落ちる。テーマのコード背景色をページに敷いて
  馴染ませ、テーマが変わったら絵を捨てて描き直す
- mermaid の render 失敗はエラー図を DOM に残すことがある。後始末して
  「失敗」を記録し、同じ図を毎回試さない

## 影響

- 図のあるノートでは Chromium のプロセスが 1 組動く（メモリ数十 MB）。
  表示だけの機能なので、閉じれば消える
- ライセンス表記は既存の resources/vendor/mermaid-LICENSE.txt（MIT）が
  引き続き担う。エディタ内表示は複製・再配布を伴わないので追加条件は無い
