@echo off
REM Einmaliges Setup fuer das Zylinderabflug-Auswertetool.
REM Doppelklick genuegt - es muss nichts getippt werden.

echo Pruefe Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python wurde nicht gefunden. Bitte zuerst Python von python.org installieren
    echo ^(beim Setup unbedingt "Add python.exe to PATH" ankreuzen^) und dieses
    echo Skript danach erneut per Doppelklick starten.
    pause
    exit /b 1
)

echo Installiere/aktualisiere benoetigte Zusatzpakete...
python -m pip install --upgrade openpyxl requests beautifulsoup4

echo.
echo Fertig! Ab jetzt reicht ein Doppelklick auf "Zylinderabflug_Tool.pyw",
echo um das Tool zu starten ^(ohne Konsolenfenster^).
echo.
echo Tipp: Mit "build_exe.bat" laesst sich einmalig eine eigenstaendige .exe
echo erzeugen, die auch ohne installiertes Python laeuft.
pause
