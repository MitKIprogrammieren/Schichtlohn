# SchichtLohn für das iPhone

Eigene SwiftUI-App, die mit dem SchichtLohn-Server spricht (Lager, Drucker mit AMS, Live-Gewicht der Waagen).

## Installieren mit SideStore (ohne bezahltes Apple-Konto)

1. Einmalig SideStore einrichten (iloader auf dem Mac, LocalDevVPN auf dem iPhone).
2. Auf dem iPhone unter GitHub → Releases → **iOS-App (neueste)** die Datei `SchichtLohn.ipa` laden.
3. Datei teilen → **SideStore**. SideStore signiert und installiert die App.
4. Beim ersten Start Serveradresse eintragen (z. B. `192.168.1.66:8093`, unterwegs die Tailscale-Adresse) und – falls gesetzt – den Schlüssel.

SideStore erneuert die App alle 7 Tage selbst (LocalDevVPN muss dafür an sein).

## Wie die App gebaut wird

Jede Änderung unter `ios/` startet die GitHub-Aktion `iOS-App`: Sie erzeugt das Xcode-Projekt mit XcodeGen
(`ios/project.yml`), baut ohne Signatur und legt `SchichtLohn.ipa` in das Release `ios-neueste`.

Lokal auf dem Mac geht es auch: `brew install xcodegen`, dann in `ios/` `xcodegen generate` und `SchichtLohn.xcodeproj` öffnen.

## Grenzen mit kostenlosem Apple-Konto

- Keine Push-Meldungen vom Server (dafür ntfy), kein NFC in der App (die NTAG-Aufkleber öffnen ihren Link trotzdem über das iPhone).
- Mit dem Apple Developer Program (99 €/Jahr) gehen beide – der Code bleibt gleich.
