# Zylinderabflug-Auswertetool

*(English version: [README.md](README.md))*

Wertet den Annex-A "Cylinder Start" (SC3A 7.4.4, Edition 2025) für einen
Wertungstag aus den rohen, von den Piloten eingesandten IGC-Dateien aus
(bevor diese von SeeYou Competition gewertet werden) und erzeugt:

- **Kopien** der IGC-Dateien (Originale bleiben unangetastet) mit hineingeschriebener
  Aufgabe. Sie werden im Zielordner gespeichert, **der möglichst der Ordner sein
  sollte, in dem SeeYou Competition die IGC-Dateien sucht**. Jede Kopie enthält
  die Streckenpunkte plus den korrigierten Startpunkt (1 m Mini-Zylinder genau
  am gewerteten PEV) im LSEEYOU-Format, zum Import in SeeYou Competition per
  "Aufgabe aus IGC-Datei nutzen". Enthält die Datei bereits einen
  SoaringSpot-Aufgabenblock (z. B. bei einem zweiten Lauf), wird darin nur die
  Start-Zeile ersetzt statt alles neu anzuhängen.
- **einen gemeinsamen Report** (`Zylinderabflug_Report.xlsx`, englisch:
  `Cylinder_Start_Report.xlsx`) mit Startmethode, Start-/Zielhöhe (Baro),
  Groundspeed, Höhenverlust, Strafpunkten und allen Besonderheiten je Pilot.

Tage mit Linien- oder Sektorstart werden von diesem Tool **nicht** bearbeitet
(das macht SeeYou selbst) - nur für Tage mit Zylinderabflug verwenden.

## Schnellstart: einen Wertungstag auswerten

**Einmalig vor der ersten Benutzung**
1. Programm besorgen (siehe [Installation](#installation)): am einfachsten die
   fertige `Zylinderabflug_Tool.exe` von der Seite **Releases** dieses
   Repositories - kein Python, kein Terminal.
2. Die **CUP-Datei** des Wettbewerbs (Wendepunkte mit Koordinaten) bereithalten.
   Das Tool fragt einmal danach und merkt sie sich.

**An jedem Wertungstag**
1. **Rohe IGC-Dateien** des Tages (nur eine Klasse) in einem Ordner sammeln -
   dem *Quellordner*. An einem echten Wertungstag sind das die Dateien so, wie
   die Piloten sie abgegeben haben. Zum **Testen mit einem alten, schon
   gewerteten Tag** funktionieren auch von SoaringSpot heruntergeladene
   IGC-Dateien: Sie enthalten bereits einen Aufgabenblock, den das Tool
   aktualisiert (nur die Start-Zeile wird ersetzt). Vom Tool bereits erzeugte
   Kopien (`..._cyl.igc`) nicht wieder als Eingabe verwenden.
2. **Programm starten** (Doppelklick auf die `.exe`).
3. **Ordner wählen:**
   - *Quellordner* = der Ordner aus Schritt 1.
   - *Zielordner* = der Ordner, in dem SeeYou Competition die IGC-Dateien dieses
     Tages sucht. Einen **anderen Ordner** als den Quellordner nehmen, damit
     Rohdateien und Kopien (Name `<Originalname>_cyl.igc`) nicht
     durcheinandergeraten.
4. **Aufgabe laden** - auf "Aufgabe von SoaringSpot-Webseite laden..." klicken,
   den Link der *Task*-Seite des Tages einfügen (ein Ergebnis-Link wird
   automatisch umgewandelt) und auf Nachfrage die CUP-Datei wählen. Der
   Wertungstag wird aus dem Link übernommen.
5. **Felder prüfen** - nicht alles steht auf der Webseite:
   - **Toröffnung (Ortszeit)**: gelb/fett bedeutet, dass noch der Standardwert
     (03:00:00) steht - die echte Zeit aus dem Task Sheet eintragen. Gibt es
     "Task notes", werden sie in einem Fenster angezeigt; Toröffnung, maximalen
     Groundspeed und maximalen Höhenverlust von dort übernehmen.
   - **Max. Groundspeed / max. Höhenverlust / Zeitzone**: müssen zum Task Sheet
     passen. Voreingestellt sind die Annex-A-Werte; bei nationalen Regeln ändern.
   - Optional: **Baro kalibrieren** auf die Platzhöhe (siehe unten).
6. Auf **"Auswertung starten"** klicken. Das Protokoll zeigt den Fortschritt;
   danach liegen im Zielordner die IGC-Kopien und der Excel-Report.
7. **Report lesen** (`Zylinderabflug_Report.xlsx`), bevor es weitergeht. Jeder
   Pilot hat eine Zeile, eingefärbt nach der schwersten Anmerkung:
   **rot** = Strafe oder ungültig, **gelb** = bitte manuell prüfen,
   **grau** = nur Hinweis (z. B. normale Außenlandung). Zuerst alle roten und
   gelben Zeilen ansehen.
8. **In SeeYou Competition werten:** die Aufgabe des Tages mit "Aufgabe aus
   IGC-Datei nutzen" setzen (eine der Kopien aus dem Zielordner wählen) und die
   Flüge aus dem Zielordner einlesen. Der Start jedes Piloten ist jetzt der
   1-m-Zylinder an seinem gewerteten Startfix, SeeYou berechnet Startzeit und
   -höhe also korrekt. (Die Menünamen können je nach SeeYou-Version leicht
   abweichen.)
9. **Strafen manuell in SeeYou eintragen:** der Report enthält je Pilot die
   Zeitstrafe (+5 min bei Exit-Start oder zu kurzem PEV-Abstand) und die Punkte
   für zu hohen Groundspeed und Höhenverlust.

Am nächsten Tag das Programm einfach wieder starten - Ordner, Parameter und
CUP-Datei sind gespeichert; nur das heutige Datum und die Toröffnung werden
zurückgesetzt.

## Woher die Aufgabe kommt - drei Wege

1. **SoaringSpot-Webseite** (Haupt-Weg): Button "Aufgabe von SoaringSpot-Webseite
   laden...", Link zur **Task**-Seite eingeben, z. B.
   `https://www.soaringspot.com/en_gb/<wettbewerb>/tasks/<klasse>/task-N-on-<datum>`.
   Wird versehentlich ein *Ergebnis*-Link eingefügt, wandelt das Tool ihn
   automatisch in die Task-Seite um; der Wertungstag wird aus dem Link
   übernommen. Diese Seite liefert Streckenpunkt-Reihenfolge, Zylinder-/Sektor-Radien
   und die AAT-Mindestzeit - aber **keine Koordinaten**. Deshalb wird nach einer
   **CUP-Datei** gefragt, aus der die Koordinaten anhand der Namen zugeordnet
   werden (die CUP-Datei wird dauerhaft gespeichert; nur wenn Namen einer
   Aufgabe nicht mehr passen, wird neu gefragt). Toröffnung, Max. Groundspeed
   und Max. Höhenverlust stehen (falls der Ausrichter sie eingetragen hat) nur in
   den freien "Task notes" der Seite - die werden nach dem Laden in einem Fenster
   angezeigt, zum Übertragen in die Felder.
2. **Aus einer bereits verarbeiteten IGC-Datei**: Button "Aufgabe aus IGC-Datei
   laden (SoaringSpot)...". Funktioniert nur, wenn die gewählte Datei bereits
   einen SoaringSpot-Aufgabenblock enthält - bei den **rohen Piloten-Dateien vor
   der Wertung ist das nicht der Fall**, ebenso **nicht** bei Dateien, deren
   Aufgabe schon mit persönlichem Startpunkt verändert wurde (der
   SoaringSpot-Block entsteht erst durch den SoaringSpot-Upload, meist NACH der
   Wertung).
3. **CUP-Datei + manuelle Eingabe**: falls SoaringSpot nicht wie erwartet
   erreichbar ist oder mit einem anderen Programm als SeeYou gewertet werden
   soll. Wendepunkte einzeln hinzufügen (Koordinaten aus einer CUP-Datei oder
   von Hand), dazu Radius, optional Sektor (Innenradius/Öffnungswinkel) und
   Maximalhöhe, Tagesparameter von Hand eintragen.

Alle drei Wege landen im selben Formular - was die Webseite nicht liefert
(Koordinaten, Toröffnung, max. Groundspeed/Höhenverlust ohne Notes), lässt sich
danach von Hand ergänzen oder korrigieren.

## Installation

Drei Möglichkeiten, keine braucht ein Terminal:

**1. Fertige .exe herunterladen (am einfachsten)**
Auf der Seite **Releases** dieses Repositories die Datei
`Zylinderabflug_Tool.exe` herunterladen und auf den Desktop kopieren - ein
Doppelklick startet das Programm. Windows zeigt eventuell eine
"SmartScreen"-Warnung, weil die Datei nicht digital signiert ist: auf
"Weitere Informationen" -> "Trotzdem ausführen" klicken.

**2. .exe selbst bauen (Windows, Python installiert)**
1. Alle Dateien in einen Ordner legen.
2. `build_exe.bat` doppelklicken (öffnet kurz ein Fenster, das alles
   automatisch installiert und baut - nichts eintippen, einfach warten).
3. Danach liegt `dist\Zylinderabflug_Tool.exe` als fertige, eigenständige
   Datei vor. Auf den Desktop kopieren (oder Verknüpfung anlegen) - ab dann
   genügt ein Doppelklick, **ohne Python und ohne Terminal**, auch auf einem
   anderen Windows-Rechner.

**3. Ohne Bauen, wenn Python schon installiert ist**
1. `install.bat` doppelklicken (einmalig; installiert `openpyxl`, `requests`
   und `beautifulsoup4`).
2. Danach startet ein Doppelklick auf `Zylinderabflug_Tool.pyw` die
   Oberfläche direkt, ohne Konsolenfenster.

**Nur falls Python komplett fehlt:** von python.org installieren und dabei
unbedingt "Add python.exe to PATH" anhaken - danach funktioniert Möglichkeit
2 oder 3.

Alle `.py`-Dateien (auch `i18n.py` und `en_dict.py`) müssen beim Start aus dem
Quellcode (Möglichkeiten 2 und 3) im selben Ordner liegen.

## Einstellungen im Detail

- **Tagesparameter** (max. Groundspeed, max. Höhenverlust, minimaler
  PEV-Abstand usw.): Die Annex-A-Standardwerte sind voreingestellt und können
  für nationale Wettbewerbe mit abweichenden Regeln direkt überschrieben werden.
- **Baro-Kalibrierung** (optional): "Baro auf Referenzhöhe kalibrieren"
  anhaken und die Platzhöhe (m MSL) eintragen. Die Standphase am Dateianfang
  wird dann auf diese Höhe gesetzt. Beginnt eine Datei in der Luft, bleibt sie
  unkalibriert (Hinweis im Report). Der Höhenverlust ändert sich durch die
  Kalibrierung nicht, nur die ausgewiesenen Start-/Zielhöhen. Höhen im Report
  sind immer barometrisch.
- **Parameter speichern/laden** sichert einen kompletten Datensatz als JSON,
  z. B. um die Aufgabe eines früheren Tages wiederzuverwenden.
- **Ist das Fenster größer als der Bildschirm**: den Scrollbalken rechts oder
  das Mausrad benutzen. Die Knöpfe "Parameter laden/speichern" und
  "Auswertung starten" unten bleiben immer sichtbar.

## Sprache

Deutsch / Englisch lässt sich oben rechts im Fenster wählen. Die Umstellung
wirkt sofort und wird gemerkt (Standard: Systemsprache). Der Excel-Report wird
in der gewählten Sprache geschrieben.

## Gemerkte Einstellungen

Beim Beenden speichert das Tool alle Werte (Geschwindigkeiten, Höhenverlust,
Platzhöhe + Kalibrier-Häkchen, Ordner, Start-Zylinder, Streckenpunkte, ...) und
je Auswahlfenster den zuletzt benutzten Ordner - auch nach einem Neustart.
Der Wertungstag wird nicht gemerkt (beim Start: heutiges Datum), ebenso nicht
die Toröffnung (Standard 03:00:00). Die CUP-Datei liegt im Ordner
`.zylinderabflug_tool` im Benutzerverzeichnis.

## Farben im Report

Jede Pilotenzeile hat die Farbe ihrer schwersten Anmerkung: **rot** = Strafe
oder ungültig, **gelb** = prüfen, **grau** = nur Hinweis (z. B. normale
Außenlandung, irrelevanter PEV). Strafpunkte sind ganze Zahlen (kaufmännisch
gerundet).

## Fehlersuche

| Problem | Was tun |
|---|---|
| "Seite konnte nicht gelesen werden" / keine Streckenpunkte gefunden | Prüfen, dass der Link auf eine *Task*-Seite eines Wertungstages zeigt (`.../task-N-on-<datum>`), oder die Aufgabe manuell eingeben (Weg 3). |
| Das Tool fragt erneut nach einer CUP-Datei | Einige Wendepunkt-Namen der Aufgabe passen nicht mehr zur gespeicherten CUP-Datei - die CUP-Datei dieses Wettbewerbs wählen. |
| Keine `.igc`-Dateien gefunden | Der Quellordner muss die Dateien direkt enthalten (Unterordner werden nicht durchsucht). |
| Ein Pilot hat "kein gültiger Start" | Anmerkung im Report lesen: kein PEV im Zylinder und kein Exit nach Toröffnung, oder Startgeschwindigkeit mehr als 50 km/h über dem Limit. |
| Feld Toröffnung ist gelb | Es steht noch der Standardwert 03:00:00 - den echten Wert eintragen. |

## Offene Punkte / bekannte Grenzen dieser Version

- Für die interne Prüfung der Reihenfolge der Streckenpunkte (wann wurde welcher
  Punkt erreicht, für den Höhenverlust) wird nur der Außenradius jeder Zone als
  Vollkreis geprüft, keine exakten Sektorwinkel - für die eigentliche Wertung
  unerheblich, die macht SeeYou mit den echten Sektorwerten.
- Die Kernlogik wurde gegen vier echte IGC-Dateien eines Wertungstages getestet
  (Normalfall, PEV außerhalb des Zylinders, Geschwindigkeitsüberschreitung,
  Höhenverlust-Grenzfall) - für den produktiven Einsatz in der
  Wettbewerbsleitung bitte trotzdem stichprobenartig gegen bekannte
  SeeYou-Ergebnisse prüfen.
- Linien- und Sektorstart-Tage fasst das Tool nicht an (die kann SeeYou schon) -
  für solche Tage einfach die Original-IGC-Dateien direkt in SeeYou verwenden
  und nicht durch dieses Tool schicken.
- Höhenverlust-Strafe: 1 Punkt pro 3 m ist eine Einstellung (Wert vom
  Auftraggeber vorgegeben; der Annex sagt nur "proportional"). Die Kappung
  (erreichte Geschwindigkeitspunkte / 15 % der Bestpunktzahl) übernimmt SeeYou.
- Die 10-Minuten-PEV-Intervallstrafe bei Wiederholung an einem weiteren
  Wertungstag kann das Tool nicht erkennen - der Report enthält nur den Hinweis
  "vorherige Fälle prüfen".
