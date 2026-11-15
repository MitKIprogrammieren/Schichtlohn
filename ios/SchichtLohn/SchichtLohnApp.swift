import SwiftUI

@main
struct SchichtLohnApp: App {
    @State private var store = Store()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            Hauptansicht()
                .environment(store)
                .preferredColorScheme(.dark)
                .tint(.slAkzent)
        }
        .onChange(of: phase) { _, neu in
            switch neu {
            case .active:
                Task { await store.allesLaden() }
                store.liveStarten()
            case .background:
                store.liveStoppen()
            default:
                break
            }
        }
    }
}

struct Hauptansicht: View {
    @Environment(Store.self) private var store

    var body: some View {
        if store.eingerichtet {
            TabView {
                HeuteView()
                    .tabItem { Label("Heute", systemImage: "sun.max") }
                LagerView()
                    .tabItem { Label("Lager", systemImage: "square.stack.3d.up") }
                DruckerListeView()
                    .tabItem { Label("Drucker", systemImage: "printer") }
                EinstellungenView()
                    .tabItem { Label("Einstellungen", systemImage: "gearshape") }
            }
        } else {
            EinrichtungView()
        }
    }
}
