# Helm

Intranet-Dashboard für Industrie- und OT-Umgebungen. Kombiniert einen Issue-Tracker, einen Dokumentenspeicher und ein Gerätedashboard in einer selbst gehosteten Web-App.

## Features

| Bereich | Funktionen |
|---|---|
| **Dashboard** | Geräte-Kacheln mit Link-Vorschau (OG-Image), MJPEG-Kamera-Streams, MP4-Video-Tiles, eingebettete Charts (z. B. OPC2InfluxDB) mit Ansichts-Umschalter, VNC- (noVNC) und RDP-Zugang (Guacamole) im Vollbild-Overlay, Gruppierung, Zugangsdaten |
| **Issues** | WYSIWYG-Editor (Tiptap), Statusverwaltung, Prioritäten, Tags, Fälligkeitsdatum, Anhänge, Archiv |
| **Dokumente** | Datei-Browser, Upload, ZIP-Extraktion, Vorschau (PDF, Bilder, Markdown) |
| **E-Mail** | Fälligkeitsalarme, tägliche/wöchentliche/monatliche/jährliche Digest-Mails |
| **Settings** | Grafische Konfiguration, SMTP-Test, manueller Index-Sync, Issue-De-Archivierung |

## Schnellstart (lokal)

```bat
start_helm.bat          :: Helm (Port 8081)
start_lighthouse.bat    :: Lighthouse
```

Öffnet automatisch `http://localhost:8081`.

**Voraussetzungen:** Python 3.12+

## Docker

```bash
docker compose up -d
```

Startet Helm auf Port `8001` und Lighthouse auf Port `8002` (im Container jeweils `8080`). Config und Daten liegen in den Volumes `helm-data` bzw. `lighthouse-data` (Pfad `/data` im Container).

SMTP-Passwort über Umgebungsvariable übergeben:

```bash
SMTP_PASSWORD=geheim docker compose up -d
```

## Konfiguration

`config.yaml` (wird beim ersten Start automatisch angelegt):

```yaml
issues_dir: ./data/issues
docs_dir:   ./data/docs
db_path:    ./data/helm.db
host:       0.0.0.0
port:       8081

smtp:
  enabled:      false
  host:         mail.example.com
  port:         587
  tls:          true
  username:     user@example.com
  password:     ""          # oder SMTP_PASSWORD env var
  from_address: user@example.com
  to_addresses:
    - empfaenger@example.com

notifications:
  base_url:     http://localhost:8081
  trigger_hour: 7           # Uhrzeit für Alarme und Digests
  due_tomorrow: true
  digest_daily: false
  digest_weekly: false
  digest_monthly: false
  digest_yearly: false
```

Pfad zur Config-Datei über Umgebungsvariable `APP_CONFIG` änderbar (Standard: `./config.yaml`).

## Datenformat Issues

Issues werden als ZIP-Dateien gespeichert:

```
data/issues/
├── issue-<uuid>.zip
│   ├── issue.md          ← YAML-Frontmatter + Markdown-Body
│   ├── images/           ← Eingebettete Bilder
│   └── attachments/      ← Dateianhänge
└── archive/              ← Archivierte Issues
```

Die ZIP-Dateien sind plain-text-lesbar und können direkt bearbeitet werden. Über **Settings → Maintenance → Sync** wird der SQLite-Index neu aufgebaut.

## Dashboard-Kacheln

| Typ | URL | Anzeige |
|---|---|---|
| `link` | Web-UI eines Geräts | Vorschaubild, öffnet in neuem Tab |
| `camera` | MJPEG-/Snapshot-URL | Live-Bild, Klick vergrößert |
| `video` | MP4-URL | Stummes Loop-Video, Klick vergrößert |
| `chart` | Embed-URL (iframe) | Eingebettet; optional mehrere Ansichten als `Label\|URL` pro Zeile (Umschalter auf der Kachel, Vollbild zeigt die gewählte Ansicht) |
| `vnc` | noVNC-Client-URL, z. B. `http://host:6080/vnc.html?autoconnect=1` | Button „Verbinden“ öffnet Vollbild-Overlay |
| `rdp` | Guacamole-Client-URL | Button „Verbinden“ öffnet Vollbild-Overlay |

Die Vorschau einer `link`-Kachel holt der Helm-Server selbst und speichert sie lokal (24 h): das `og:image`/`twitter:image` der Seite oder ein großes Icon (ab 120 px). Logos werden vollständig eingepasst, nur Screenshot-artige Bilder füllen die Kachel. Das Icon im Kachelkopf ist das, das die Seite ankündigt (auch SVG), sonst `/favicon.ico`. Selbstsignierte Zertifikate werden dafür akzeptiert. Liefert das Gerät nichts davon, zeigt die Kachel das Symbol ihres **Bereichs** (Network, Services, Controllers, Clients, Field devices, Meters). Den Bereich erkennt Helm am Gruppennamen; welche Gruppennamen zu welchem Bereich gehören, steht unter **Settings → Device areas**, und im Kachel-Detail lässt er sich fest setzen; ein eigenes Bild lässt sich im Kachel-Detail per URL oder mit „Bild hochladen…“ vom Rechner bzw. mit „Aus Zwischenablage“ setzen (wird auf 800 px verkleinert und neben `dashboard.yaml` in `tile_uploads/` gespeichert).

Kacheln lassen sich am Griff ⠿ per Drag & Drop umsortieren, auch in eine andere Gruppe. Ganze Gruppen verschiebt man an ihrer Überschrift. Die Reihenfolge wird in `dashboard.yaml` gespeichert (Reihenfolge der `entries`).

Overlays schließen über „✕ Schließen“ oder `Esc` (Bild/Video auch per Klick daneben). Eingebettete Seiten vom selben Host wie Helm laufen in einer strikten Sandbox ohne Zugriff auf Helm. Das Ziel muss das Einbetten erlauben (kein `X-Frame-Options: DENY` bzw. passende `frame-ancestors`).

## Aussehen

Unter **Settings → Appearance** lassen sich Look (Studio, Monochrome, Contrast) und Farbschema (System, Light, Medium, Dark, Solarized light/dark) wählen, wie in OPC2Influx. Die Wahl gilt pro Browser, so kann z. B. die Leitwarte dunkel und das Büro hell arbeiten.

Chart-Kacheln mit einem OPC2Influx-Embed (`…/chart/embed/<id>`) übernehmen Look und Farbschema automatisch. In der Kachel-URL wird nur noch `shaded` angegeben, falls die Fläche unter den Kurven gefüllt sein soll, z. B. `http://opc2influx:8000/chart/embed/<id>/shaded`. Andere Angaben zu Schema oder Look in der URL ersetzt Helm.

## Update (Docker)

Issues, Dokumente, Datenbank, `dashboard.yaml`, `config.yaml` und hochgeladene Kachelbilder liegen im Volume `/data` und überstehen ein Update. Das Datenformat ist seit der ersten Version kompatibel.

### Update von einer Version vor November 2026

Ältere Versionen haben zwei Dateien **im Container** statt im Volume abgelegt (`/app/data`). Beim Update wird der Container neu angelegt, und diese Dateien wären weg:

| Datei | Folge ohne Vorbereitung |
|---|---|
| `report_templates.yaml` (Berichtsvorlagen) | **Vorlagen gehen verloren** |
| `.lighthouse_state.json` (Sync-Merker) | kein Datenverlust; der erste Sync zieht einmal alle Issues neu, ohne Duplikate |

Neue Versionen speichern beides im Volume. Die Berichtsvorlagen deshalb **vor** dem Update ins Volume kopieren, solange der alte Container noch läuft:

```bash
docker compose exec helm sh -c 'test -f /app/data/report_templates.yaml && cp /app/data/report_templates.yaml /data/'
docker compose exec lighthouse sh -c 'test -f /app/data/report_templates.yaml && cp /app/data/report_templates.yaml /data/'
```

Ohne Shell-Zugang zum Container (z. B. auf dem IXON SecureEdge Pro) die Vorlagen nach dem Update unter **Settings → Report Templates** neu anlegen.

Empfohlen vor jedem Update: das Volume sichern. Den Namen zeigt `docker volume ls`, meist mit Projektpräfix:

```bash
docker run --rm -v helm_lighthouse_helm-data:/data -v "$PWD":/backup alpine tar czf /backup/helm-data.tgz -C /data .
```

Danach wie gewohnt aktualisieren: Image neu holen bzw. bauen, `docker compose up -d`.

### Helm und Lighthouse gemeinsam aktualisieren

Das Sync-Protokoll wurde geändert (die offenen Endpunkte `/api/sync/register` und `/api/sync/list` sind entfernt, der Helm baut die ZIP-URL selbst). **Helm- und Lighthouse-Instanzen müssen gemeinsam aktualisiert werden**, sonst schlägt der Sync fehl. Daten gehen dabei nicht verloren.

## IXON SecureEdge Pro

Siehe [IXON_DEPLOYMENT.md](IXON_DEPLOYMENT.md) für Cross-Compile und Deployment auf `linux/arm64`.

## Tech Stack

FastAPI · Uvicorn · HTMX · Jinja2 · Tiptap · SQLite (aiosqlite) · PyYAML · aiosmtplib
