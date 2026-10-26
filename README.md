# Helm

Intranet-Dashboard für Industrie- und OT-Umgebungen. Kombiniert einen Issue-Tracker, einen Dokumentenspeicher und ein Gerätedashboard in einer selbst gehosteten Web-App.

## Features

| Bereich | Funktionen |
|---|---|
| **Dashboard** | Geräte-Kacheln mit Link-Vorschau (OG-Image), MJPEG-Kamera-Streams, MP4-Video-Tiles, Gruppierung, Zugangsdaten |
| **Issues** | WYSIWYG-Editor (Tiptap), Statusverwaltung, Prioritäten, Tags, Fälligkeitsdatum, Anhänge, Archiv |
| **Dokumente** | Datei-Browser, Upload, ZIP-Extraktion, Vorschau (PDF, Bilder, Markdown) |
| **E-Mail** | Fälligkeitsalarme, tägliche/wöchentliche/monatliche/jährliche Digest-Mails |
| **Settings** | Grafische Konfiguration, SMTP-Test, manueller Index-Sync, Issue-De-Archivierung |

## Schnellstart (lokal)

```bat
start.bat
```

Öffnet automatisch `http://localhost:8081`.

**Voraussetzungen:** Python 3.12+

## Docker

```bash
docker compose up -d
```

App läuft auf Port `8080`. Daten liegen in den Volumes `helm_config` und `helm_data`.

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

## IXON SecureEdge Pro

Siehe [IXON_DEPLOYMENT.md](IXON_DEPLOYMENT.md) für Cross-Compile und Deployment auf `linux/arm64`.

## Tech Stack

FastAPI · Uvicorn · HTMX · Jinja2 · Tiptap · SQLite (aiosqlite) · PyYAML · aiosmtplib
