import AppKit
import CoreGraphics

guard CommandLine.arguments.count == 2 else {
    fputs("usage: make-icon.swift <output.iconset>\n", stderr)
    exit(2)
}

let iconsetDir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: iconsetDir, withIntermediateDirectories: true)

let specs: [(name: String, px: Int)] = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

func renderIcon(px: Int) -> Data? {
    let size = CGFloat(px)
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: px,
        pixelsHigh: px,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else { return nil }

    rep.size = NSSize(width: size, height: size)
    NSGraphicsContext.saveGraphicsState()
    guard let nsCtx = NSGraphicsContext(bitmapImageRep: rep) else { return nil }
    NSGraphicsContext.current = nsCtx
    let ctx = nsCtx.cgContext
    ctx.setShouldAntialias(true)
    ctx.interpolationQuality = .high

    // macOS squircle proportions (~9.5% inset, 22.5% corner radius of inner rect)
    let inset = size * 0.095
    let bgRect = CGRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset)
    let cornerRadius = bgRect.width * 0.225
    let bgPath = CGPath(roundedRect: bgRect, cornerWidth: cornerRadius, cornerHeight: cornerRadius, transform: nil)

    // Vibrant emerald-to-forest gradient background (distinct from Copy URL's cobalt)
    ctx.saveGState()
    ctx.addPath(bgPath)
    ctx.clip()
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let colors = [
        CGColor(red: 0.08, green: 0.78, blue: 0.48, alpha: 1.0),
        CGColor(red: 0.02, green: 0.45, blue: 0.30, alpha: 1.0),
    ] as CFArray
    if let gradient = CGGradient(colorsSpace: colorSpace, colors: colors, locations: [0.0, 1.0]) {
        ctx.drawLinearGradient(
            gradient,
            start: CGPoint(x: bgRect.midX, y: bgRect.maxY),
            end: CGPoint(x: bgRect.midX, y: bgRect.minY),
            options: []
        )
    }
    ctx.restoreGState()

    // Subtle crisp inner highlight border
    ctx.saveGState()
    ctx.addPath(bgPath)
    ctx.setStrokeColor(CGColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.22))
    ctx.setLineWidth(max(1.0, size * 0.015))
    ctx.strokePath()
    ctx.restoreGState()

    // Bold solid white clipboard body
    let boardW = bgRect.width * 0.62
    let boardH = bgRect.height * 0.68
    let boardX = bgRect.midX - boardW / 2
    let boardY = bgRect.minY + bgRect.height * 0.12
    let boardRect = CGRect(x: boardX, y: boardY, width: boardW, height: boardH)
    let boardRadius = bgRect.width * 0.09
    let boardPath = CGPath(roundedRect: boardRect, cornerWidth: boardRadius, cornerHeight: boardRadius, transform: nil)

    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -size * 0.015), blur: size * 0.03, color: CGColor(red: 0, green: 0, blue: 0, alpha: 0.28))
    ctx.addPath(boardPath)
    ctx.setFillColor(CGColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 1.0))
    ctx.fillPath()
    ctx.restoreGState()

    // Top clip tab
    let clipW = boardW * 0.48
    let clipH = bgRect.height * 0.13
    let clipX = bgRect.midX - clipW / 2
    let clipY = boardRect.maxY - clipH * 0.45
    let clipRect = CGRect(x: clipX, y: clipY, width: clipW, height: clipH)
    let clipPath = CGPath(roundedRect: clipRect, cornerWidth: clipH * 0.45, cornerHeight: clipH * 0.45, transform: nil)

    ctx.saveGState()
    ctx.addPath(clipPath)
    ctx.setFillColor(CGColor(red: 0.78, green: 0.96, blue: 0.88, alpha: 1.0))
    ctx.fillPath()
    ctx.addPath(clipPath)
    ctx.setStrokeColor(CGColor(red: 0.02, green: 0.45, blue: 0.30, alpha: 0.55))
    ctx.setLineWidth(max(1.0, size * 0.018))
    ctx.strokePath()
    ctx.restoreGState()

    // Bold arrow-up-right ("open") SF Symbol inside the clipboard in deep emerald
    let symbolSize = boardW * 0.56
    let config = NSImage.SymbolConfiguration(pointSize: symbolSize, weight: .heavy)
        .applying(NSImage.SymbolConfiguration(paletteColors: [NSColor(red: 0.02, green: 0.42, blue: 0.28, alpha: 1.0)]))
    if let openImg = NSImage(systemSymbolName: "arrow.up.right", accessibilityDescription: nil)?.withSymbolConfiguration(config) {
        let imgSize = openImg.size
        let bodyCenterY = boardRect.minY + (clipRect.minY - boardRect.minY) * 0.52
        let dest = NSRect(
            x: boardRect.midX - imgSize.width / 2,
            y: bodyCenterY - imgSize.height / 2,
            width: imgSize.width,
            height: imgSize.height
        )
        openImg.draw(in: dest, from: .zero, operation: .sourceOver, fraction: 1.0)
    }

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])
}

for spec in specs {
    guard let data = renderIcon(px: spec.px) else {
        fputs("failed to render \(spec.name)\n", stderr)
        exit(1)
    }
    try data.write(to: iconsetDir.appendingPathComponent(spec.name))
}
