import SwiftUI

struct DruckerListeView: View {
    @Environment(Store.self) private var store

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    if store.drucker.isEmpty {
                        Karte {
                            Text("Keine Drucker verbunden. Drucker trägst du in der SchichtLohn-Web-App unter Einstellungen ein.")
                                .foregroundStyle(Color.slText2)
                        }
                    }
                    ForEach(store.drucker) { d in
                        NavigationLink(value: d.id) { DruckerZeile(drucker: d) }
                            .buttonStyle(.plain)
                    }
                }
                .padding(14)
            }
            .background(Color.slHintergrund)
            .navigationTitle("Drucker")
            .navigationDestination(for: String.self) { DruckerDetailView(druckerID: $0) }
            .refreshable { await store.druckerLaden() }
        }
    }
}

struct DruckerZeile: View {
    let drucker: Drucker

    private var punktFarbe: Color {
        if !drucker.online { return .slText3 }
        if drucker.status == "FAILED" { return .slFehler }
        if drucker.status == "PAUSE" { return .slWarnung }
        return .slAkzent
    }

    var body: some View {
        Karte {
            HStack(spacing: 10) {
                Circle().fill(punktFarbe).frame(width: 10, height: 10)
                VStack(alignment: .leading, spacing: 2) {
                    Text(drucker.name).font(.subheadline.weight(.semibold))
                    Text(drucker.druckt && !drucker.aufgabe.isEmpty ? drucker.aufgabe : drucker.statusText)
                        .font(.caption).foregroundStyle(Color.slText2).lineLimit(1)
                }
                Spacer()
                if drucker.druckt {
                    Text("\(drucker.fortschritt) %").font(.subheadline.weight(.semibold)).foregroundStyle(Color.slAkzent)
                }
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(Color.slText3)
            }
            HStack(spacing: 4) {
                ForEach(drucker.faecher.filter { !$0.leer }) { f in
                    Circle().fill(Color(hex: f.farbe)).frame(width: 14, height: 14)
                        .overlay(Circle().stroke(Color.white.opacity(0.15), lineWidth: 1))
                }
            }
        }
    }
}

struct DruckerDetailView: View {
    @Environment(Store.self) private var store
    let druckerID: String

    var body: some View {
        ScrollView {
            if let d = store.drucker.first(where: { $0.id == druckerID }) {
                VStack(spacing: 10) {
                    Karte {
                        HStack {
                            Text(d.statusText).font(.headline)
                            Spacer()
                            if d.druckt {
                                Text("\(d.fortschritt) %").font(.headline).foregroundStyle(Color.slAkzent)
                            }
                        }
                        if d.druckt {
                            if !d.aufgabe.isEmpty {
                                Text(d.aufgabe).font(.subheadline).foregroundStyle(Color.slText2)
                            }
                            Balken(anteil: Double(d.fortschritt) / 100)
                            Text("Restzeit \(Format.dauer(minuten: d.restzeit))")
                                .font(.caption).foregroundStyle(Color.slText2)
                        }
                    }
                    ForEach(d.gruppen, id: \.titel) { g in
                        AMSKarte(drucker: d, titel: g.titel, faecher: g.faecher)
                    }
                }
                .padding(14)
                .navigationTitle(d.name)
            } else {
                Text("Drucker nicht mehr verbunden").foregroundStyle(Color.slText2).padding()
            }
        }
        .background(Color.slHintergrund)
        .navigationBarTitleDisplayMode(.inline)
    }
}
