# 同梱している他所のファイル

書き出した HTML は「外部リソースを参照しない」約束（`editor/exporter.to_html`）
なので、図の描画に要る JavaScript はここに置いて**中に埋め込む**。
CDN を参照すると、渡した相手がオフラインだと図が出ず、将来 CDN が消えれば
過去に書き出したファイルまで壊れる。

| ファイル | 中身 | 出どころ | ライセンス |
| --- | --- | --- | --- |
| `mermaid.min.js` | Mermaid 11.16.1（3.4MB） | https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js | MIT（`mermaid-LICENSE.txt`） |

**埋め込むのは図があるノートだけ。** 図の無いノートの書き出しは今まで通りの
大きさで出る。
