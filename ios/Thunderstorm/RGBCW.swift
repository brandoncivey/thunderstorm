import Foundation

/// Port of pywizlight's rgb2rgbcw (pywizlight/rgbcw.py). WiZ bulbs mix five
/// LEDs — r, g, b, warm white, cold white — and pywizlight converts an RGB
/// color into RGB + a white-LED component before sending it. Without this,
/// "white" renders on the RGB diodes only: dimmer and tinted compared to the
/// Python version. Pure white (255,255,255) actually goes out as
/// r=0 g=0 b=0 w=128 — the dedicated white diode at its cap.
enum RGBCW {
    private static let epsilon = 1.0e-5
    private static let cwMax = 128.0
    /// Unit vectors at 0°, 120°, 240° — the r/g/b directions on the hue wheel.
    private static let basis: [(x: Double, y: Double)] = [
        (cos(0.0), sin(0.0)),
        (cos(2.0 * .pi / 3.0), sin(2.0 * .pi / 3.0)),
        (cos(4.0 * .pi / 3.0), sin(4.0 * .pi / 3.0)),
    ]

    /// rgb in 0-255 → (rgb out 0-255, white-channel value 0-128).
    static func convert(_ rgb: (Int, Int, Int)) -> (rgb: (Int, Int, Int), cw: Int) {
        let scaled = [Double(rgb.0) / 255, Double(rgb.1) / 255, Double(rgb.2) / 255]
        var hue = (x: 0.0, y: 0.0)
        for (component, vector) in zip(scaled, basis) {
            hue.x += vector.x * component
            hue.y += vector.y * component
        }
        // vecLen: zero unless the squared length clears epsilon.
        let lenSq = hue.x * hue.x + hue.y * hue.y
        let saturation = lenSq > epsilon ? sqrt(lenSq) : 0
        if saturation > epsilon {
            hue.x /= saturation
            hue.y /= saturation
        }
        return trapezoid(hue: hue, saturation: saturation)
    }

    private static func trapezoid(hue: (x: Double, y: Double), saturation: Double)
        -> (rgb: (Int, Int, Int), cw: Int)
    {
        var rgb: [Double]
        if saturation <= epsilon {
            rgb = [0, 0, 0]
        } else {
            // Which (at most two) basis vectors is the hue between?
            let maxAngle = cos((2.0 * .pi / 3.0) - epsilon)
            let mask = basis.map { (hue.x * $0.x + hue.y * $0.y) > maxAngle }
            if mask.filter({ $0 }).count == 1 {
                rgb = mask.map { $0 ? 1.0 : 0.0 }
            } else {
                // Ray-line intersection between the two, as in the Python.
                let sub = basis.enumerated().filter { mask[$0.offset] }.map(\.element)
                let ab = (x: sub[1].y, y: -sub[1].x)
                let coeff0 = (hue.x * ab.x + hue.y * ab.y)
                    / (sub[0].x * ab.x + sub[0].y * ab.y)
                let intersection = (x: hue.x - coeff0 * sub[0].x,
                                    y: hue.y - coeff0 * sub[0].y)
                var coeff = [coeff0,
                             intersection.x * sub[1].x + intersection.y * sub[1].y]
                let maxCoeff = coeff.max() ?? 1
                coeff = coeff.map { $0 / maxCoeff }
                var next = 0
                rgb = mask.map { on -> Double in
                    guard on else { return 0 }
                    defer { next += 1 }
                    return min(coeff[next], 1)
                }
            }
        }
        // Discontinuous white mixing: saturated colors scale the white LED
        // down; washed-out colors saturate the white LED and scale RGB down.
        let cw: Double
        if saturation >= 0.5 {
            cw = 1 - ((saturation - 0.5) * 2)
        } else {
            cw = 1
            rgb = rgb.map { $0 * saturation * 2 }
        }
        // Truncation (not rounding) matches the Python's vecInt()/int().
        let out = (Int(rgb[0] * 255), Int(rgb[1] * 255), Int(rgb[2] * 255))
        return (out, Int(max(0, cw * cwMax)))
    }
}
