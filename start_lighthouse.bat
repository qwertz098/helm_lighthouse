@echo off
setlocal

set "DIR=%~dp0"
set "VENV=%DIR%.venv"

cd /d "%DIR%"

:: ── Konfiguration ─────────────────────────────────────────────────────────────
set "APP_CONFIG=%DIR%config_lighthouse.yaml"
set "PORT=8082"
set "HELM_MODE=lighthouse"
set "HELM_SITE_NAME=Lighthouse"

:: Optional: Web-UI Basic Auth (empfohlen bei Internet-Exposure)
set "HELM_ADMIN_USER="
set "HELM_ADMIN_PASSWORD="

:: Optional: SMTP-Zugangsdaten (ueberschreiben config_lighthouse.yaml)
:: set "SMTP_HOST=mail.gmx.net"
:: set "SMTP_PORT=587"
:: set "SMTP_TLS=true"
:: set "SMTP_USERNAME=user@example.com"
:: set "SMTP_PASSWORD=geheim"
:: set "SMTP_FROM=user@example.com"
:: set "SMTP_TO=empfaenger@example.com"
:: ──────────────────────────────────────────────────────────────────────────────

:: Aktuelle Version aus Git holen. Danach startet das Skript sich einmal neu, weil
:: cmd die laufende Datei stueckweise liest und ein Update sie veraendert haben kann.
if not defined HELM_PULLED if exist "%DIR%.git" (
    where git >nul 2>&1
    if errorlevel 1 (
        echo [Lighthouse] WARNUNG: git nicht gefunden, starte ohne Update.
    ) else (
        echo [Lighthouse] Hole aktuelle Version ...
        git pull --ff-only
        if errorlevel 1 (
            echo [Lighthouse] WARNUNG: git pull fehlgeschlagen, starte mit lokaler Version.
        )
        set "HELM_PULLED=1"
        call "%~f0" %*
        exit /b
    )
)

:: Config anlegen falls nicht vorhanden
if not exist "%APP_CONFIG%" (
    echo [Lighthouse] Erstelle Standard-Konfiguration: config_lighthouse.yaml ...
    (
        echo # Lighthouse-Konfiguration
        echo # Modus und Site-Name werden per Umgebungsvariable gesetzt ^(HELM_MODE, HELM_SITE_NAME^)
        echo.
        echo issues_dir: data_lighthouse\issues
        echo docs_dir: data_lighthouse\docs
        echo db_path: data_lighthouse\lighthouse.db
        echo dashboard_file: data_lighthouse\dashboard.yaml
        echo host: 0.0.0.0
        echo port: %PORT%
        echo.
        echo smtp:
        echo   enabled: false
        echo   host: mail.gmx.net
        echo   port: 587
        echo   tls: true
        echo   username: ""
        echo   password: ""
        echo   from_address: ""
        echo   to_addresses: []
        echo.
        echo notifications:
        echo   base_url: http://localhost:%PORT%
        echo   trigger_hour: 7
        echo   due_tomorrow: true
        echo   digest_daily: false
        echo   digest_weekly: false
        echo   digest_monthly: false
        echo   digest_yearly: false
    ) > "%APP_CONFIG%"
    echo [Lighthouse] Konfiguration erstellt.
    echo.
)

:: Venv muss bereits existieren (start_helm.bat zuerst ausfuehren)
if not exist "%VENV%\Scripts\activate.bat" (
    echo [FEHLER] Virtuelle Umgebung nicht gefunden.
    echo Bitte zuerst start_helm.bat ausfuehren um die Umgebung einzurichten.
    pause
    exit /b 1
)

call "%VENV%\Scripts\activate.bat"

:: Abhaengigkeiten aktualisieren (eine neue Version kann neue Pakete brauchen)
echo [Lighthouse] Installiere/aktualisiere Abhaengigkeiten ...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [FEHLER] pip install fehlgeschlagen.
    pause
    exit /b 1
)

echo [Lighthouse] Starte Server auf http://localhost:%PORT% ...
start "" http://localhost:%PORT%
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

endlocal
PAUSE
