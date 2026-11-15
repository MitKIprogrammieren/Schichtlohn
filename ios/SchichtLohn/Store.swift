import Foundation
import Observation

enum ServerFehler: LocalizedError {
    case keineAdresse
    case schluessel
    case http(Int, String)

    var errorDescription: String? {
        switch self {
        case .keineAdresse: return "Keine Serveradresse eingetragen."
        case .schluessel: return "Der Server will einen Schlüssel – der eingetragene fehlt oder stimmt nicht."
        case let .http(code, text): return "Server meldet \(code)\(text.isEmpty ? "" : ": \(text)")"
        }
    }
}

@MainActor
@Observable
final class Store {
    // Einstellungen
    var adresse: String {
        didSet { UserDefaults.standard.set(adresse, forKey: "adresse") }
    }
    var schluessel: String {
        didSet { UserDefaults.standard.set(schluessel, forKey: "schluessel") }
    }

    // Daten
    var sorten: [Sorte] = []
    var drucker: [Drucker] = []
    var rollen: [Rolle] = []
    var waagen: [String: WaageLive] = [:]
    var version = ""
    var fehler: String?
    var laedt = false
    var liveVerbunden = false

    private var liveAufgabe: Task<Void, Never>?
    private var druckerAufgabe: Task<Void, Never>?

    init() {
        adresse = UserDefaults.standard.string(forKey: "adresse") ?? ""
        schluessel = UserDefaults.standard.string(forKey: "schluessel") ?? ""
    }

    /// erst nach erfolgreicher Prüfung in der Einrichtung true
    var eingerichtet: Bool = UserDefaults.standard.bool(forKey: "eingerichtet") {
        didSet { UserDefaults.standard.set(eingerichtet, forKey: "eingerichtet") }
    }

    var basis: URL? {
        var a = adresse.trimmingCharacters(in: .whitespacesAndNewlines)
        while a.hasSuffix("/") { a.removeLast() }
        if a.isEmpty { return nil }
        if !a.lowercased().hasPrefix("http") { a = "http://" + a }
        // Ohne Port nehmen wir den Standard-Port des SchichtLohn-Servers
        if let u = URL(string: a), u.port == nil, u.scheme == "http", (u.path.isEmpty || u.path == "/") {
            a += ":8093"
        }
        return URL(string: a)
    }

    // MARK: Anfragen

    private func anfrage(_ pfad: String, timeout: TimeInterval = 15) throws -> URLRequest {
        guard let b = basis, let url = URL(string: b.absoluteString + pfad) else { throw ServerFehler.keineAdresse }
        var r = URLRequest(url: url, timeoutInterval: timeout)
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        let t = schluessel.trimmingCharacters(in: .whitespacesAndNewlines)
        if !t.isEmpty { r.setValue(t, forHTTPHeaderField: "X-Token") }
        return r
    }

    private func holen(_ pfad: String) async throws -> JSON {
        let (daten, antwort) = try await URLSession.shared.data(for: anfrage(pfad))
        let code = (antwort as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw ServerFehler.schluessel }
        let j = (try? JSONSerialization.jsonObject(with: daten)) as? JSON ?? [:]
        if code >= 400 { throw ServerFehler.http(code, text(j["fehler"] ?? j["message"])) }
        return j
    }

    /// Für die Einrichtung: erreicht die App den Server, und passt der Schlüssel?
    func pruefen() async -> String? {
        do {
            let s = try await holen("/status")
            version = text(s["version"])
            if (s["zugang"] as? Bool) == false { return ServerFehler.schluessel.localizedDescription }
            return nil
        } catch {
            return verstaendlich(error)
        }
    }

    func allesLaden() async {
        guard eingerichtet else { return }
        laedt = true
        defer { laedt = false }
        do {
            async let s = holen("/api/sorten")
            async let d = holen("/api/drucker")
            async let r = holen("/api/rollen")
            let (sj, dj, rj) = try await (s, d, r)
            sorten = ((sj["sorten"] as? [JSON]) ?? []).map(Sorte.init)
                .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            drucker = ((dj["drucker"] as? [JSON]) ?? []).map(Drucker.init)
            rollen = ((rj["rollen"] as? [JSON]) ?? []).map(Rolle.init)
            fehler = nil
        } catch {
            fehler = verstaendlich(error)
        }
    }

    func lagerLaden() async {
        if let j = try? await holen("/api/sorten") {
            sorten = ((j["sorten"] as? [JSON]) ?? []).map(Sorte.init)
                .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        }
    }

    func druckerLaden() async {
        if let j = try? await holen("/api/drucker") {
            drucker = ((j["drucker"] as? [JSON]) ?? []).map(Drucker.init)
        }
        if let j = try? await holen("/api/rollen") {
            rollen = ((j["rollen"] as? [JSON]) ?? []).map(Rolle.init)
        }
    }

    func rolle(drucker: String, ort: String) -> Rolle? {
        rollen.first { $0.drucker == drucker && $0.ort == ort }
    }

    // MARK: Live (Server-Sent Events) und Drucker-Abfrage

    func liveStarten() {
        guard eingerichtet else { return }
        if liveAufgabe == nil {
            liveAufgabe = Task { [weak self] in await self?.liveSchleife() }
        }
        if druckerAufgabe == nil {
            druckerAufgabe = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(5))
                    await self?.druckerLaden()
                }
            }
        }
    }

    func liveStoppen() {
        liveAufgabe?.cancel()
        liveAufgabe = nil
        druckerAufgabe?.cancel()
        druckerAufgabe = nil
        liveVerbunden = false
    }

    private func liveSchleife() async {
        while !Task.isCancelled {
            do {
                var r = try anfrage("/api/ereignisse", timeout: 3600)
                r.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                let (bytes, antwort) = try await URLSession.shared.bytes(for: r)
                if (antwort as? HTTPURLResponse)?.statusCode == 401 { throw ServerFehler.schluessel }
                liveVerbunden = true
                for try await zeile in bytes.lines {
                    if Task.isCancelled { break }
                    guard zeile.hasPrefix("data:") else { continue }
                    let roh = zeile.dropFirst(5).trimmingCharacters(in: .whitespaces)
                    if let d = roh.data(using: .utf8),
                       let ev = (try? JSONSerialization.jsonObject(with: d)) as? JSON {
                        ereignis(ev)
                    }
                }
            } catch {
                // Verbindung weg (Hintergrund, WLAN-Wechsel) – gleich neu versuchen
            }
            liveVerbunden = false
            if Task.isCancelled { break }
            try? await Task.sleep(for: .seconds(3))
        }
    }

    private var lagerNeuGeplant = false

    private func ereignis(_ ev: JSON) {
        switch text(ev["typ"]) {
        case "waage_live":
            let pre = text(ev["pre"])
            guard !pre.isEmpty, let g = zahl(ev["g"]) else { return }
            waagen[pre] = WaageLive(pre: pre, gramm: g, stabil: (ev["stabil"] as? Bool) ?? false, zeit: Date())
        case "liste", "abbuchung":
            // mehrere Änderungen kurz hintereinander nur einmal nachladen
            guard !lagerNeuGeplant else { return }
            lagerNeuGeplant = true
            Task {
                try? await Task.sleep(for: .milliseconds(400))
                await lagerLaden()
                await druckerLaden()
                lagerNeuGeplant = false
            }
        default:
            break
        }
    }

    /// Waagen, die in den letzten 30 s etwas geschickt haben
    var aktiveWaagen: [WaageLive] {
        waagen.values.filter { Date().timeIntervalSince($0.zeit) < 30 }.sorted { $0.pre < $1.pre }
    }

    private func verstaendlich(_ e: Error) -> String {
        if let s = e as? ServerFehler { return s.localizedDescription }
        let ns = e as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorTimedOut: return "Der Server antwortet nicht. Bist du im Heimnetz oder per Tailscale verbunden?"
            case NSURLErrorCannotConnectToHost, NSURLErrorCannotFindHost:
                return "Server nicht gefunden – Adresse und Port prüfen (meist :8093)."
            case NSURLErrorNotConnectedToInternet: return "Keine Netzverbindung."
            default: break
            }
        }
        return e.localizedDescription
    }
}
