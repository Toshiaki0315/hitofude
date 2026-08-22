// 画像を文字にする小さな道具（ADR-0027）。
//
// macOS の Vision（Live Text の中身）に読ませる。**pyobjc は使わない**
// （30MB 入るうえ、実測では結果が返らなかった）。これは 63KB で済む。
//
// 使い方: hitofude-ocr <画像のパス>
// 読み取った行を改行で区切って標準出力へ。読めなければ終了コード 1。

import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("使い方: hitofude-ocr <画像のパス>\n".utf8))
    exit(2)
}

let path = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: path),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write(Data("画像を開けない: \(path)\n".utf8))
    exit(1)
}

let request = VNRecognizeTextRequest()
// **速さより正確さ。** 1 枚 0.85 秒で、待てない長さではない
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ja-JP", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("読み取れない: \(error)\n".utf8))
    exit(1)
}

// **Vision が返す並びのまま出す。** 並べ替えると「元と違う順で読める」
// 不具合を自分で作り込むことになる（ADR-0027 の「やらないこと」）
for observation in request.results ?? [] {
    if let candidate = observation.topCandidates(1).first {
        print(candidate.string)
    }
}
