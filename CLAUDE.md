# Hinweise für Claude

- Jede neue Server-Version (`schichtlohn/config.yaml` und `VERSION` in `server/app.py`) bekommt einen Eintrag oben in `schichtlohn/CHANGELOG.md`: Version, Datum, was sich für den Nutzer ändert – auf Deutsch, kurz, ohne Technik-Jargon. Home Assistant zeigt diese Datei beim Update an.
- Nach Änderungen an `app/index.html` immer `python3 tools/karte.py` ausführen (baut die HA-Karte neu).
- Commits als MitKIprogrammieren (`-c user.name="MitKIprogrammieren" -c user.email="MitKIprogrammieren@users.noreply.github.com"`).
- Bei allem Optischen erst eine Vorschau rendern und zeigen, dann einbauen.
