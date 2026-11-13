@echo off
setlocal
set "DIR=%~dp0"
cd /d "%DIR%"

:: Aktuelle Version aus Git holen. Danach startet das Skript sich einmal neu, weil
:: cmd die laufende Datei stueckweise liest und ein Update sie veraendert haben kann.
if not defined HELM_PULLED if exist "%DIR%.git" (
    where git >nul 2>&1
    if errorlevel 1 (
        echo [Build] WARNUNG: git nicht gefunden, baue lokale Version.
    ) else (
        echo [Build] Hole aktuelle Version ...
        git pull --ff-only
        if errorlevel 1 (
            echo [Build] FEHLER: git pull fehlgeschlagen, Abbruch damit keine veraltete Version gebaut wird.
            echo [Build] Lokale Aenderungen committen/verwerfen oder Netzwerk pruefen.
            pause
            exit /b 1
        )
        set "HELM_PULLED=1"
        call "%~f0" %*
        exit /b
    )
)

set EDGE_IP=192.168.1.1
set IMAGE_TAG=latest

:: Jede Version bekommt einen eigenen Image-Namen (helm_v<Anzahl Commits>, z. B. helm_v31):
:: der SecureEdge Pro erkennt ein Update unter gleichem Namen und Tag nicht.
set BUILD_NO=0
for /f %%n in ('git rev-list --count HEAD 2^>nul') do set BUILD_NO=%%n
set "IMAGE_NAME=helm_v%BUILD_NO%"
git diff --quiet HEAD 2>nul || (
    echo [Build] WARNUNG: nicht committete Aenderungen, Image heisst %IMAGE_NAME%-dirty
    set "IMAGE_NAME=%IMAGE_NAME%-dirty"
)

docker buildx inspect secure-edge-pro >nul 2>&1 || (
    docker buildx create --name secure-edge-pro --config buildkitd-secure-edge-pro.toml
)
docker buildx use secure-edge-pro
:: Release shown on the settings page, e.g. v1.0.0 or v1.0.0-3-gabc1234
set APP_RELEASE=dev
for /f "delims=" %%v in ('git describe --tags --always --dirty 2^>nul') do set APP_RELEASE=%%v
docker buildx build --platform linux/arm64/v8 --build-arg APP_RELEASE=%APP_RELEASE% --tag %EDGE_IP%:5000/%IMAGE_NAME%:%IMAGE_TAG% --push .
if errorlevel 1 (
    echo [Build] FEHLER: Build oder Push fehlgeschlagen.
) else (
    echo.
    echo [Build] Fertig. Im IXON-Portal einen Container mit diesem Image anlegen:
    echo     %EDGE_IP%:5000/%IMAGE_NAME%:%IMAGE_TAG%
    echo [Build] Volumes vom alten Container uebernehmen, danach alten Container und altes Image loeschen.
)

PAUSE
