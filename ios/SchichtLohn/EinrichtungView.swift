import SwiftUI

/// Erster Start: Serveradresse und Schlüssel eintragen
struct EinrichtungView: View {
    @Environment(Store.self) private var store
    @State private var adresse = "192.168.1.66:8093"
    @State private var schluessel = ""
    @State private var meldung: String?
    @State private var prueft = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Willkommen bei SchichtLohn").font(.title2.weight(.semibold))
                        Text("Trag die Adresse deines SchichtLohn-Servers ein. Unterwegs geht auch die Tailscale-Adresse.")
                            .foregroundStyle(Color.slText2)
                    }
                    .listRowBackground(Color.clear)
                }
                ServerFelder(adresse: $adresse, schluessel: $schluessel)
                if let meldung {
                    Section { Text(meldung).foregroundStyle(Color.slFehler) }
                }
                Section {
                    Button {
                        Task { await verbinden() }
                    } label: {
                        HStack {
                            Text("Verbinden")
                            Spacer()
                            if prueft { ProgressView() }
                        }
                    }
                    .disabled(prueft || adresse.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.slHintergrund)
            .navigationTitle("Einrichtung")
        }
    }

    private func verbinden() async {
        prueft = true
        defer { prueft = false }
        let altA = store.adresse, altS = store.schluessel
        store.adresse = adresse
        store.schluessel = schluessel
        if let f = await store.pruefen() {
            meldung = f
            store.adresse = altA
            store.schluessel = altS
            return
        }
        store.eingerichtet = true
        await store.allesLaden()
        store.liveStarten()
    }
}

struct ServerFelder: View {
    @Binding var adresse: String
    @Binding var schluessel: String

    var body: some View {
        Section {
            TextField("192.168.1.66:8093", text: $adresse)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            SecureField("Schlüssel (falls eingestellt)", text: $schluessel)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
        } header: {
            Text("Server")
        } footer: {
            Text("Den Schlüssel brauchst du nur, wenn in SchichtLohn unter Einstellungen ein Zugangsschlüssel gesetzt ist.")
        }
    }
}

struct EinstellungenView: View {
    @Environment(Store.self) private var store
    @State private var adresse = ""
    @State private var schluessel = ""
    @State private var meldung: String?
    @State private var ok = false

    var body: some View {
        NavigationStack {
            Form {
                ServerFelder(adresse: $adresse, schluessel: $schluessel)
                Section {
                    Button("Speichern und prüfen") {
                        Task {
                            store.liveStoppen()
                            store.adresse = adresse
                            store.schluessel = schluessel
                            meldung = await store.pruefen()
                            ok = meldung == nil
                            await store.allesLaden()
                            store.liveStarten()
                        }
                    }
                    if ok {
                        Label("Verbunden", systemImage: "checkmark.circle").foregroundStyle(Color.slAkzent)
                    }
                    if let meldung {
                        Text(meldung).foregroundStyle(Color.slFehler)
                    }
                }
                Section("Info") {
                    LabeledContent("Server-Version", value: store.version.isEmpty ? "–" : store.version)
                    LabeledContent("Live-Verbindung", value: store.liveVerbunden ? "verbunden" : "getrennt")
                    LabeledContent("App-Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "–")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.slHintergrund)
            .navigationTitle("Einstellungen")
            .onAppear {
                adresse = store.adresse
                schluessel = store.schluessel
                Task { _ = await store.pruefen() }
            }
        }
    }
}
