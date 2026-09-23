// 本机抠人像：macOS Vision 的人物分割，不依赖任何外部服务。
// 用法：swift segment_person.swift <输入.png> <输出.png>
// 退出码：1 读不了图 / 分割失败，2 画面里没找到人，3 输出失败。
import Foundation
import Vision
import CoreImage
import AppKit

let args = CommandLine.arguments
let input = URL(fileURLWithPath: args[1]), output = URL(fileURLWithPath: args[2])
guard let src = CIImage(contentsOf: input) else { fputs("读不了图\n", stderr); exit(1) }
let req = VNGeneratePersonSegmentationRequest()
req.qualityLevel = .accurate
req.outputPixelFormat = kCVPixelFormatType_OneComponent8
let handler = VNImageRequestHandler(ciImage: src)
do { try handler.perform([req]) } catch { fputs("分割失败 \(error)\n", stderr); exit(1) }
guard let buf = req.results?.first?.pixelBuffer else { fputs("没找到人\n", stderr); exit(2) }
var mask = CIImage(cvPixelBuffer: buf)
mask = mask.transformed(by: CGAffineTransform(scaleX: src.extent.width / mask.extent.width, y: src.extent.height / mask.extent.height))
let out = src.applyingFilter("CIBlendWithMask", parameters: [kCIInputBackgroundImageKey: CIImage.empty(), kCIInputMaskImageKey: mask])
let ctx = CIContext()
guard let cg = ctx.createCGImage(out, from: src.extent) else { exit(3) }
let rep = NSBitmapImageRep(cgImage: cg)
try! rep.representation(using: .png, properties: [:])!.write(to: output)
print("ok \(Int(src.extent.width))x\(Int(src.extent.height))")
