import SwiftUI

struct LagerView: View {
    @Environment(Store.self) private var store
    @State private var suche = ""
    @State private var material = "Alle"
    @State private var leereZeigen = false

    private var materialien: [String] {
        ["Alle"] + Array(Set(store.sorten.map(\.material).filter { !$0.isEmpty })).sorted()
    }

    private var gefiltert: [Sorte] {
        store.sorten.filter { s in
            (leereZeigen || !s.leer)
                && (material == "Alle" || s.material == material)
                && (suche.isEmpty
                    || s.name.localizedCaseInsensitiveContains(suche)
                    || s.hersteller.localizedCaseInsensitiveContains(suche)
                    || s.farbe.localizedCaseInsensitiveContains(suche))
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(gefiltert) { s in
                        NavigationLink(value: s) { SorteZeile(sorte: s) }
                            .listRowBackground(Color.slKarte)
                    }
                } header: {
                    let summe = gefiltert.reduce(0) { $0 + $1.bestand }
                    Text("\(gefiltert.count) Sorten · \(Format.gramm(summe))")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.slHintergrund)
            .navigationTitle("Lager")
            .searchable(text: $suche, prompt: "Sorte, Hersteller, Farbe")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Picker("Material", selection: $material) {
                            ForEach(materialien, id: \.self) { Text($0) }
                        }
                        Toggle("Leere Sorten zeigen", isOn: $leereZeigen)
                    } label: {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                    }
                }
            }
            .navigationDestination(for: Sorte.self) { SorteDetailView(sorte: $0) }
            .refreshable { await store.lagerLaden() }
        }
    }
}

struct RollenSymbol: View {
    let hex: String
    var groesse: CGFloat = 34

    var body: some View {
        ZStack {
            Circle().fill(Color(hex: hex))
            Circle().stroke(Color.white.opacity(0.18), lineWidth: 1)
            Circle().fill(Color.slHintergrund).frame(width: groesse * 0.32, height: groesse * 0.32)
        }
        .frame(width: groesse, height: groesse)
    }
}

struct SorteZeile: View {
    let sorte: Sorte

    var body: some View {
        HStack(spacing: 12) {
            RollenSymbol(hex: sorte.hex)
            VStack(alignment: .leading, spacing: 2) {
                Text(sorte.name).font(.subheadline.weight(.medium)).lineLimit(1)
                Text([sorte.hersteller, sorte.material].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(Color.slText2).lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(Format.gramm(sorte.bestand))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(sorte.leer ? Color.slFehler : sorte.fastLeer ? Color.slWarnung : Color.slText)
                Text(sorte.spulen == 1 ? "1 Rolle" : "\(sorte.spulen) Rollen")
                    .font(.caption2).foregroundStyle(Color.slText3)
            }
        }
        .padding(.vertical, 2)
    }
}

struct SorteDetailView: View {
    let sorte: Sorte

    private var rollen: [Double] {
        guard sorte.spulen > 0 else { return [] }
        let r = Array(sorte.reste.filter { $0 > 0 && $0 < sorte.gewicht }.sorted().prefix(sorte.spulen))
        return r + Array(repeating: sorte.gewicht, count: sorte.spulen - r.count)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                HStack(spacing: 14) {
                    RollenSymbol(hex: sorte.hex, groesse: 64)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(sorte.name).font(.title3.weight(.semibold))
                        Text([sorte.hersteller, sorte.material, sorte.farbe].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.subheadline).foregroundStyle(Color.slText2)
                    }
                    Spacer()
                }
                .padding(.vertical, 6)

                HStack(spacing: 8) {
                    Kachel(titel: "Bestand", wert: Format.gramm(sorte.bestand),
                           farbe: sorte.fastLeer ? .slWarnung : .slText)
                    Kachel(titel: "Volle Rolle", wert: Format.gramm(sorte.gewicht), farbe: .slText)
                }

                Karte {
                    Text("Rollen").font(.subheadline.weight(.semibold))
                    if rollen.isEmpty {
                        Text("Keine Rolle mehr im Lager").foregroundStyle(Color.slText2)
                    }
                    ForEach(Array(rollen.enumerated()), id: \.offset) { i, g in
                        HStack {
                            Text("Rolle \(i + 1)").font(.caption).foregroundStyle(Color.slText2)
                                .frame(width: 56, alignment: .leading)
                            Balken(anteil: g / sorte.gewicht, farbe: Color(hex: sorte.hex))
                            Text(Format.gramm(g)).font(.caption.monospacedDigit())
                                .frame(width: 64, alignment: .trailing)
                        }
                    }
                }
            }
            .padding(14)
        }
        .background(Color.slHintergrund)
        .navigationTitle(sorte.material.isEmpty ? "Sorte" : sorte.material)
        .navigationBarTitleDisplayMode(.inline)
    }
}
