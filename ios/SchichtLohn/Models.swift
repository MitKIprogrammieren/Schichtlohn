import Foundation

// Der Server liefert Zahlen mal als Zahl, mal als Text – darum lesen wir JSON von Hand und großzügig.
typealias JSON = [String: Any]

func zahl(_ w: Any?) -> Double? {
    switch w {
    case let d as Double: return d
    case let i as Int: return Double(i)
    case let n as NSNumber: return n.doubleValue
    case let s as String: return Double(s.replacingOccurrences(of: ",", with: "."))
    default: return nil
    }
}

func text(_ w: Any?) -> String {
    switch w {
    case let s as String: return s
    case let n as NSNumber: return n.stringValue
    default: return ""
    }
}

// MARK: Lager

struct Sorte: Identifiable, Hashable {
    let uid: String
    let name: String
    let hersteller: String
    let material: String
    let farbe: String
    let hex: String
    let gewicht: Double      // Gramm einer vollen Rolle
    let spulen: Int
    let reste: [Double]

    var id: String { uid }

    init(_ j: JSON) {
        uid = text(j["uid"])
        name = text(j["name"])
        hersteller = text(j["hersteller"])
        material = text(j["material"])
        farbe = text(j["farbe"])
        hex = text(j["hex"])
        let gw = zahl(j["gewicht"]) ?? 1000
        gewicht = gw > 0 ? gw : 1000
        spulen = Int(zahl(j["spulen"]) ?? 1)
        reste = ((j["reste"] as? [Any]) ?? []).compactMap { zahl($0) }
    }

    /// Wie abbuchen_rechnen auf dem Server: volle Rollen + angebrochene Reste
    var bestand: Double {
        guard spulen > 0 else { return 0 }
        let r = Array(reste.filter { $0 > 0 && $0 < gewicht }.sorted().prefix(spulen))
        return Double(spulen - r.count) * gewicht + r.reduce(0, +)
    }

    var fastLeer: Bool { spulen > 0 && bestand < 200 }
    var leer: Bool { bestand <= 0 }
}

// MARK: Drucker

struct Fach: Identifiable, Hashable {
    let ort: String
    let farbe: String
    let typ: String
    let name: String
    let rest: Int            // Bambu-Restanzeige in %, -1 = unbekannt
    let leer: Bool
    let ams: Int?
    var id: String { ort }

    init(_ j: JSON) {
        ort = text(j["ort"])
        farbe = text(j["farbe"])
        typ = text(j["typ"])
        name = text(j["name"])
        rest = Int(zahl(j["rest"]) ?? -1)
        leer = (j["leer"] as? Bool) ?? false
        ams = (j["ams"] is NSNull) ? nil : (zahl(j["ams"]).map { Int($0) })
    }
}

struct Drucker: Identifiable, Hashable {
    let serial: String
    let name: String
    let online: Bool
    let fehler: String
    let status: String
    let fortschritt: Int
    let restzeit: Int        // Minuten
    let aufgabe: String
    let faecher: [Fach]
    var id: String { serial.isEmpty ? name : serial }

    init(_ j: JSON) {
        serial = text(j["serial"])
        name = text(j["name"])
        online = (j["online"] as? Bool) ?? false
        fehler = text(j["fehler"])
        status = text(j["status"]).uppercased()
        fortschritt = Int(zahl(j["fortschritt"]) ?? 0)
        restzeit = Int(zahl(j["restzeit"]) ?? 0)
        aufgabe = text(j["aufgabe"])
        faecher = ((j["faecher"] as? [JSON]) ?? []).map(Fach.init)
    }

    var druckt: Bool { ["RUNNING", "PREPARE", "SLICING", "PAUSE"].contains(status) }

    var statusText: String {
        if !online { return fehler.isEmpty ? "Offline" : fehler }
        switch status {
        case "RUNNING": return "Druckt"
        case "PREPARE", "SLICING": return "Bereitet vor"
        case "PAUSE": return "Pausiert"
        case "FINISH": return "Fertig"
        case "FAILED": return "Abgebrochen"
        case "IDLE", "": return "Bereit"
        default: return status.capitalized
        }
    }

    /// Fächer nach AMS gruppiert (externe Spule zuletzt)
    var gruppen: [(titel: String, faecher: [Fach])] {
        var reihenfolge: [String] = []
        var map: [String: [Fach]] = [:]
        for f in faecher {
            let t: String
            if f.ams == nil { t = "Extern" }
            else if let r = f.ort.range(of: " Fach") { t = String(f.ort[..<r.lowerBound]) }
            else { t = f.ort }
            if map[t] == nil { reihenfolge.append(t) }
            map[t, default: []].append(f)
        }
        return reihenfolge.map { ($0, map[$0] ?? []) }
    }
}

/// Zuordnung Fach → Sorte und Rolle (aus /api/rollen)
struct Rolle: Hashable {
    let drucker: String
    let ort: String
    let sorte: String
    let gramm: Double?
    let voll: Double

    init(_ j: JSON) {
        drucker = text(j["drucker"])
        ort = text(j["ort"])
        sorte = text(j["sorte"])
        let v = zahl(j["gewicht"]) ?? 1000
        voll = v > 0 ? v : 1000
        if let r = j["rolle"] as? JSON, let g = zahl(r["g"]) {
            gramm = g
        } else {
            gramm = nil
        }
    }
}

// MARK: Waage

struct WaageLive: Identifiable, Hashable {
    let pre: String
    var gramm: Double
    var stabil: Bool
    var zeit: Date
    var id: String { pre }

    var name: String {
        let n = pre.replacingOccurrences(of: "_", with: " ")
        if n == "filamentwaage" { return "Filamentwaage" }
        return n.prefix(1).uppercased() + n.dropFirst()
    }
}
