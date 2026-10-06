@echo off
REM Erzeugt einmalig eine eigenstaendige Zylinderabflug_Tool.exe im Ordner "dist".
REM Danach reicht Doppelklick auf diese .exe - Python wird nicht mehr benoetigt,
REM auch nicht auf einem anderen PC.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python wurde nicht gefunden. Bitte zuerst Python installieren
    echo ^(mit Haken bei "Add python.exe to PATH"^) und dieses Skript erneut starten.
    pause
    exit /b 1
)

echo Entferne ggf. das veraltete "pathlib"-Backport-Paket ^(unvertraeglich mit PyInstaller,
echo kommt oft ungewollt mit Anaconda mit^)...
python -m pip uninstall -y pathlib >nul 2>&1

echo Installiere Zusatzpakete ^(einmalig, kann etwas dauern^)...
python -m pip install --upgrade openpyxl requests beautifulsoup4 pyinstaller
if errorlevel 1 (
    echo.
    echo FEHLER beim Installieren der Zusatzpakete - siehe Meldungen oben.
    pause
    exit /b 1
)

echo.
echo Baue Zylinderabflug_Tool.exe ...
python -m PyInstaller --onefile --windowed --name Zylinderabflug_Tool zylinderabflug_tool.py
if errorlevel 1 (
    echo.
    echo FEHLER beim Bauen der .exe - siehe Meldungen oben ^(rot/"ERROR:"-Zeilen^).
    echo Haeufigste Ursache: das alte "pathlib"-Paket ist noch da. Falls die Zeile
    echo   "ERROR: The 'pathlib' package is an obsolete backport..."
    echo erscheint, bitte in der Anaconda-Eingabeaufforderung einmal von Hand ausfuehren:
    echo   conda remove pathlib
    echo und dieses Skript danach erneut starten.
    echo Es wurde KEINE dist\Zylinderabflug_Tool.exe erzeugt.
    pause
    exit /b 1
)

if not exist "dist\Zylinderabflug_Tool.exe" (
    echo.
    echo Unerwartet: PyInstaller hat keinen Fehler gemeldet, aber die Datei
    echo dist\Zylinderabflug_Tool.exe existiert trotzdem nicht. Bitte die
    echo Ausgabe oben pruefen.
    pause
    exit /b 1
)

echo.
echo Fertig! Die fertige Datei liegt unter:
echo   dist\Zylinderabflug_Tool.exe
echo.
echo Diese .exe kannst du an einen beliebigen Ort ^(z. B. Desktop^) kopieren
echo und danach einfach per Doppelklick starten - kein Python, kein Terminal
echo mehr noetig, auch nicht auf einem anderen Windows-PC.
pause
