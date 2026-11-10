// Odczyt tekstu z obrazu lub PDF-a wbudowanym w macOS silnikiem Vision. Wynik: JSON na stdout.
import Foundation
import Vision
import AppKit
import PDFKit
import ImageIO

func loadImages(_ url: URL) -> [CGImage] {
    if url.pathExtension.lowercased() == "pdf" {
        guard let doc = PDFDocument(url: url) else { return [] }
        var out: [CGImage] = []
        for i in 0..<min(doc.pageCount, 5) {
            guard let page = doc.page(at: i) else { continue }
            let b = page.bounds(for: .mediaBox)
            let scale = max(1.0, 2400.0 / max(b.width, b.height))
            let img = page.thumbnail(of: NSSize(width: b.width * scale, height: b.height * scale), for: .mediaBox)
            if let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) { out.append(cg) }
        }
        return out
    }
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return [] }
    let opts: [CFString: Any] = [
        kCGImageSourceCreateThumbnailFromImageAlways: true,
        kCGImageSourceCreateThumbnailWithTransform: true,   // uwzględnia obrót zapisany w zdjęciu
        kCGImageSourceThumbnailMaxPixelSize: 4000,
    ]
    if let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) { return [cg] }
    return []
}

let args = CommandLine.arguments
guard args.count > 1 else { FileHandle.standardError.write("brak pliku\n".data(using: .utf8)!); exit(2) }
var lines: [[String: Any]] = []
var pageIndex = 0
for cg in loadImages(URL(fileURLWithPath: args[1])) {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    let supported = (try? req.supportedRecognitionLanguages()) ?? []
    var langs: [String] = []
    if supported.contains("pl-PL") { langs.append("pl-PL") }
    langs.append("en-US")
    req.recognitionLanguages = langs
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([req]) } catch { continue }
    for obs in req.results ?? [] {
        guard let cand = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        lines.append(["text": cand.string, "x": Double(b.minX), "y": Double(pageIndex) + 1.0 - Double(b.maxY),
                      "w": Double(b.width), "h": Double(b.height)])
    }
    pageIndex += 1
}
let data = try JSONSerialization.data(withJSONObject: ["lines": lines], options: [])
FileHandle.standardOutput.write(data)
