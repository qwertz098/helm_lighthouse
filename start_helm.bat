@echo off
setlocal

set "DIR=%~dp0"
set "VENV=%DIR%.venv"

cd /d "%DIR%"

:: ── Konfiguration ─────────────────────────────────────────────────────────────
set "APP_CONFIG=%DIR%config.yaml"
set "PORT=8081"
set "HELM_MODE=helm"

:: Optional: Web-UI Basic Auth (leer lassen = deaktiviert)
set "HELM_ADMIN_USER="
set "HELM_ADMIN_PASSWORD="

:: Optional: SMTP-Zugangsdaten (ueberschreiben config.yaml)
:: set "SMTP_HOST=mail.gmx.net"
:: set "SMTP_PORT=587"
:: set "SMTP_TLS=true"
:: set "SMTP_USERNAME=user@example.com"
:: set "SMTP_PASSWORD=geheim"
:: set "SMTP_FROM=user@example.com"
:: set "SMTP_TO=empfaenger@example.com"

:: Optional: Lighthouse-Verbindung (einzeln oder JSON-Array)
:: set "LIGHTHOUSE_URL=http://192.168.1.10:8082"
:: set "LIGHTHOUSE_TOKEN=..."
:: set "LIGHTHOUSES=[{"name":"LH1","url":"http://...","token":"..."}]"
:: ──────────────────────────────────────────────────────────────────────────────

:: Aktuelle Version aus Git holen. Danach startet das Skript sich einmal neu, weil
:: cmd die laufende Datei stueckweise liest und ein Update sie veraendert haben kann.
if not defined HELM_PULLED if exist "%DIR%.git" (
    where git >nul 2>&1
    if errorlevel 1 (
        echo [Helm] WARNUNG: git nicht gefunden, starte ohne Update.
    ) else (
        echo [Helm] Hole aktuelle Version ...
        git pull --ff-only
        if errorlevel 1 (
            echo [Helm] WARNUNG: git pull fehlgeschlagen, starte mit lokaler Version.
        )
        set "HELM_PULLED=1"
        call "%~f0" %*
        exit /b
    )
)

:: Venv anlegen falls nicht vorhanden
if not exist "%VENV%\Scripts\activate.bat" (
    echo [Helm] Erstelle virtuelle Umgebung ...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [FEHLER] Python nicht gefunden oder venv fehlgeschlagen.
        pause
        exit /b 1
    )
)

call "%VENV%\Scripts\activate.bat"

echo [Helm] Installiere/aktualisiere Abhaengigkeiten ...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [FEHLER] pip install fehlgeschlagen.
    pause
    exit /b 1
)

echo [Helm] Starte Server auf http://localhost:%PORT% ...
start "" http://localhost:%PORT%
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

endlocal
PAUSE
