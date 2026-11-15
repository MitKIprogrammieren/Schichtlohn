import SwiftUI

struct HeuteView: View {
    @Environment(Store.self) private var store

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    if let f = store.fehler {
                        Karte(rand: .slFehler) {
                            Label(f, systemImage: "exclamationmark.triangle").foregroundStyle(Color.slFehler)
                        }
                    }

                    ForEach(store.aktiveWaagen) { w in
                        WaageKarte(waage: w)
                    }

                    let laufend = store.drucker.filter(\.druckt)
                    if laufend.isEmpty && !store.drucker.isEmpty {
                        Karte {
                            Label("Gerade läuft kein Druck", systemImage: "moon.zzz")
                                .foregroundStyle(Color.slText2)
                        }
                    }
                    ForEach(laufend) { d in
                        NavigationLink(value: d.id) { DruckKarte(drucker: d) }
                            .buttonStyle(.plain)
                    }

                    ForEach(store.drucker.filter { $0.druckt || store.drucker.count == 1 }) { d in
                        ForEach(d.gruppen, id: \.titel) { g in
                            AMSKarte(drucker: d, titel: g.titel, faecher: g.faecher)
                        }
                    }

                    LagerKacheln()
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 20)
            }
            .background(Color.slHintergrund)
            .navigationTitle("Heute")
            .navigationDestination(for: String.self) { id in
                if let d = store.drucker.first(where: { $0.id == id }) {
                    DruckerDetailView(druckerID: d.id)
                }
            }
            .refreshable { await store.allesLaden() }
        }
    }
}

struct DruckKarte: View {
    let drucker: Drucker

    var body: some View {
        Karte {
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 10).fill(Color.slSpur)
                    .frame(width: 52, height: 52)
                    .overlay(Image(systemName: "cube").font(.title2).foregroundStyle(Color.slAkzent))
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(drucker.name) · \(drucker.aufgabe.isEmpty ? drucker.statusText : drucker.aufgabe)")
                        .font(.subheadline.weight(.semibold)).lineLimit(1)
                    Text(drucker.restzeit > 0 ? "noch \(Format.dauer(minuten: drucker.restzeit))" : drucker.statusText)
                        .font(.caption).foregroundStyle(Color.slText2)
                    Balken(anteil: Double(drucker.fortschritt) / 100)
                }
                Text("\(drucker.fortschritt) %")
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Color.slAkzent)
            }
        }
    }
}

struct AMSKarte: View {
    @Environment(Store.self) private var store
    let drucker: Drucker
    let titel: String
    let faecher: [Fach]

    var body: some View {
        Karte {
            Text(titel == "Extern" ? "\(drucker.name) · Externe Spule" : "\(drucker.name) · \(titel)")
                .font(.subheadline.weight(.semibold))
            HStack(spacing: 8) {
                ForEach(faecher) { f in
                    FachSaeule(fach: f, rolle: store.rolle(drucker: drucker.name, ort: f.ort))
                }
            }
        }
    }
}

struct FachSaeule: View {
    let fach: Fach
    let rolle: Rolle?

    /// Füllstand 0…1 und Beschriftung
    private var stand: (anteil: Double, text: String, knapp: Bool) {
        if fach.leer { return (0, "leer", false) }
        if let r = rolle, let g = r.gramm { return (min(g / r.voll, 1), Format.gramm(g), g < 150) }
        if fach.rest >= 0 { return (Double(fach.rest) / 100, "\(fach.rest) %", fach.rest < 15) }
        return (0.5, "?", false)
    }

    var body: some View {
        VStack(spacing: 4) {
            GeometryReader { g in
                ZStack(alignment: .bottom) {
                    RoundedRectangle(cornerRadius: 8).fill(Color.slSpur)
                    if !fach.leer {
                        Rectangle().fill(Color(hex: fach.farbe))
                            .frame(height: max(4, g.size.height * stand.anteil))
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            .frame(height: 56)
            Text(stand.text)
                .font(.caption2)
                .foregroundStyle(stand.knapp ? Color.slWarnung : Color.slText2)
            Text(fach.leer ? " " : (fach.name.isEmpty ? fach.typ : fach.name))
                .font(.caption2).foregroundStyle(Color.slText3).lineLimit(1)
        }
        .frame(maxWidth: .infinity)
    }
}

struct WaageKarte: View {
    let waage: WaageLive

    var body: some View {
        Karte(rand: .slAkzent, hintergrund: Color(hex: "0f2216")) {
            HStack(spacing: 10) {
                Image(systemName: "scalemass").font(.title2).foregroundStyle(Color.slAkzent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(waage.name).font(.subheadline.weight(.semibold))
                    Text(waage.stabil ? "stabil" : "wiegt …").font(.caption).foregroundStyle(Color.slText2)
                }
                Spacer()
                Text(Format.gramm(max(0, waage.gramm)))
                    .font(.title3.weight(.semibold).monospacedDigit())
                    .contentTransition(.numericText())
                    .animation(.snappy(duration: 0.12), value: waage.gramm)
            }
        }
    }
}

struct LagerKacheln: View {
    @Environment(Store.self) private var store

    var body: some View {
        let gesamt = store.sorten.reduce(0) { $0 + $1.bestand }
        let knapp = store.sorten.filter(\.fastLeer).count
        HStack(spacing: 8) {
            Kachel(titel: "Im Lager", wert: Format.gramm(gesamt), farbe: .slText)
            Kachel(titel: "Fast leer", wert: knapp == 1 ? "1 Sorte" : "\(knapp) Sorten",
                   farbe: knapp > 0 ? .slWarnung : .slText)
        }
    }
}

struct Kachel: View {
    let titel: String
    let wert: String
    let farbe: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(titel).font(.caption).foregroundStyle(Color.slText3)
            Text(wert).font(.title3.weight(.semibold)).foregroundStyle(farbe)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.slKarte, in: RoundedRectangle(cornerRadius: 12))
    }
}
