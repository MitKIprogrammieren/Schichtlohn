import SwiftUI

// Farben wie in der SchichtLohn-Web-App (dunkler Stil)
extension Color {
    static let slHintergrund = Color(hex: "050706")
    static let slKarte = Color(hex: "0b100d")
    static let slRand = Color(hex: "1f2a23")
    static let slSpur = Color(hex: "1c2620")
    static let slText = Color(hex: "eef4f0")
    static let slText2 = Color(hex: "a9b7ae")
    static let slText3 = Color(hex: "6f7d74")
    static let slAkzent = Color(hex: "3fd47f")
    static let slWarnung = Color(hex: "f2b84b")
    static let slFehler = Color(hex: "ff6b5e")

    /// "#RRGGBB", "RRGGBB" oder "RRGGBBAA"; bei Unsinn Grau
    init(hex: String?) {
        var s = (hex ?? "").trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        if s.count >= 6, let wert = UInt64(s.prefix(6), radix: 16) {
            self.init(red: Double((wert >> 16) & 0xff) / 255,
                      green: Double((wert >> 8) & 0xff) / 255,
                      blue: Double(wert & 0xff) / 255)
        } else {
            self.init(red: 0.62, green: 0.62, blue: 0.62)
        }
    }
}

struct Karte<Inhalt: View>: View {
    var rand: Color = .slRand
    var hintergrund: Color = .slKarte
    @ViewBuilder var inhalt: () -> Inhalt

    var body: some View {
        VStack(alignment: .leading, spacing: 8) { inhalt() }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(hintergrund, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(rand, lineWidth: 0.5))
    }
}

struct Balken: View {
    var anteil: Double
    var farbe: Color = .slAkzent

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.slSpur)
                Capsule().fill(farbe).frame(width: max(4, g.size.width * min(max(anteil, 0), 1)))
            }
        }
        .frame(height: 6)
    }
}

enum Format {
    static func gramm(_ g: Double) -> String {
        if g >= 1000 {
            let f = NumberFormatter()
            f.locale = Locale(identifier: "de_DE")
            f.maximumFractionDigits = 2
            return (f.string(from: NSNumber(value: g / 1000)) ?? "\(g / 1000)") + " kg"
        }
        return "\(Int(g.rounded())) g"
    }

    static func dauer(minuten: Int) -> String {
        if minuten <= 0 { return "–" }
        let h = minuten / 60, m = minuten % 60
        return h > 0 ? "\(h) h \(m) min" : "\(m) min"
    }
}
