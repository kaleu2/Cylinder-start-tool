# Zylinderabflug-Auswertetool

*(English version: [README_EN.md](README_EN.md))*

Wertet den Annex-A "Cylinder Start" (SC3A 7.4.4, Edition 2025) für einen
Wertungstag aus den rohen, von den Piloten eingesandten IGC-Dateien aus
(bevor diese zu SoaringSpot hochgeladen werden) und erzeugt:

- **Kopien** der IGC-Dateien (Original bleibt unangetastet) mit hineingeschriebener
  Aufgabe: Streckenpunkte plus korrigierter Startpunkt (1 m Mini-Zylinder genau am
  gewerteten PEV) im LSEEYOU-Format, zum Import in SeeYou Competition per
  "Aufgabe aus IGC-Datei nutzen". Enthält die Datei bereits einen SoaringSpot-
  Aufgabenblock (z. B. bei einem zweiten Lauf), wird darin nur die Start-Zeile
  ersetzt statt alles neu anzuhängen.
- **einen gemeinsamen Report** (`Zylinderabflug_Report.xlsx`, englisch: `Cylinder_Start_Report.xlsx`) mit Startmethode,
  Gültigkeit, Groundspeed, Loss of Height und allen Besonderheiten je Pilot

## Woher die Aufgabe kommt - drei Wege

1. **SoaringSpot-Webseite** (Haupt-Weg): Button "Aufgabe von SoaringSpot-Webseite
   laden...", Link zur **Task**-Seite eingeben (nicht die "results"-Seite!), z. B.
   `https://www.soaringspot.com/en_gb/<wettbewerb>/tasks/<klasse>/task-N-on-<datum>`.
   Diese Seite liefert Streckenpunkt-Reihenfolge, Zylinder-/Sektor-Radien und die
   AAT-Mindestzeit - aber **keine Koordinaten**. Deshalb wird direkt danach nach
   einer **CUP-Datei** gefragt, aus der die Koordinaten anhand der Namen zugeordnet
   werden. Toröffnung, Max. Groundspeed und Max. Loss of Height stehen (falls der
   Ausrichter sie eingetragen hat) nur in den freien "Task notes" der Seite - die
   werden nach dem Laden in einem Fenster angezeigt, zum manuellen Übertragen in
   die entsprechenden Felder.
2. **Aus einer bereits verarbeiteten IGC-Datei** (z. B. eigener zweiter Lauf, oder
   Vergleich): Button "Aufgabe aus IGC-Datei laden (SoaringSpot)...". Funktioniert
   nur, wenn die gewählte Datei schon einen SoaringSpot-Aufgabenblock enthält -
   das ist bei den **rohen Pilotendateien vor der Wertung nicht der Fall** (der
   Block entsteht erst durch den Upload zu SoaringSpot, meist NACH der Wertung).
3. **CUP-Datei + manuelle Eingabe**: für den Fall, dass SoaringSpot nicht wie
   erwartet erreichbar ist. Wendepunkte einzeln hinzufügen (Koordinaten aus einer
   CUP-Datei übernehmen oder eintippen), dazu Radius, optional Sektor
   (Innenradius/Öffnungswinkel) und maximale Höhe sowie die Tagesparameter von
   Hand eintragen.

Alle drei Wege führen ins selbe Formular - was die Webseite nicht liefert
(Koordinaten, Toröffnung, Max. Groundspeed/Loss of Height ohne Notizen), lässt
sich direkt danach von Hand ergänzen oder korrigieren.

## Bedienung ohne Terminal – drei Möglichkeiten

**Am wenigsten Aufwand im Dauerbetrieb: eigenständige .exe (einmalig einrichten)**
1. Alle Dateien in einen Ordner legen.
2. Doppelklick auf `build_exe.bat` (öffnet kurz ein Fenster, das automatisch
   alles Nötige installiert und baut – nichts eintippen, nur abwarten).
3. Danach liegt unter `dist\Zylinderabflug_Tool.exe` eine fertige, eigenständige
   Datei. Diese auf den Desktop kopieren (oder verknüpfen) – ab jetzt reicht
   Doppelklick, **kein Python, kein Terminal mehr nötig**, auch nicht auf
   einem anderen Windows-Rechner.

**Alternative ohne Vorab-Schritt, falls Python schon installiert ist:**
1. Doppelklick auf `install.bat` (einmalig, installiert `openpyxl`, `requests`
   und `beautifulsoup4`).
2. Danach reicht Doppelklick auf `Zylinderabflug_Tool.pyw` – startet die
   Oberfläche direkt, ganz ohne Konsolenfenster.

**Nur falls Python noch komplett fehlt:** von python.org installieren, dabei
unbedingt "Add python.exe to PATH" ankreuzen – danach funktioniert einer der
beiden Wege oben.

## Bedienung

1. **Quellordner** (rohe IGC-Dateien der Piloten für den Wertungstag) und
   **Zielordner** wählen.
2. Aufgabe laden (siehe oben, einer der drei Wege) und die Felder prüfen/ergänzen.
3. **Tagesparameter** (Max. Groundspeed, Max. Loss of Height, PEV-Mindestintervall
   etc.) prüfen/anpassen – Annex-A-Standardwerte sind vorbelegt, für nationale
   Wettbewerbe mit abweichenden Regeln direkt überschreibbar.
4. Mit "Parameter speichern/laden" lässt sich ein einmal eingegebener Datensatz
   als JSON sichern und am nächsten Wertungstag wiederverwenden (nur Toröffnung
   und ggf. abweichende Tagesparameter müssen dann noch angepasst werden).
5. "Auswertung starten" klicken.
6. Die erzeugten Kopien in SeeYou Competition per "Aufgabe aus IGC-Datei nutzen"
   einlesen; die Strafen aus dem Report (`Zylinderabflug_Report.xlsx`) manuell
   in SeeYou eintragen.

## Neu in dieser Version

- Startwahl nach Aufgabenfortschritt (kein falscher Start durch Wiedereinflug am Zylinderrand).
- PEV-Intervall-Strafe nur für den gewerteten PEV; Meldungen mit Abstand zum Zylinderrand.
- Zielhöhe/-zeit interpoliert; Report mit Abflug-/Ankunftshöhe und Höhenverlust (nur Baro).
- Loss-of-Height-Strafpunkte (1 Punkt je 3 m, einstellbar).
- Baro-Kalibrierung auf Platzhöhe (Feld im Tool).
- CUP-Datei wird dauerhaft gespeichert (Ordner `.zylinderabflug_tool` im Benutzerverzeichnis);
  nur wenn Namen einer Aufgabe nicht mehr passen, wird nach einer neuen CUP gefragt.
- Farben im Report: rot = Strafe/ungültig, gelb = prüfen, grau = nur Hinweis.
- Ergebnis-Links von SoaringSpot werden automatisch in die Task-Seite umgewandelt; das Datum kommt aus dem Link (beim Programmstart: heutiges Datum, Toröffnung 03:00:00).
- Alle Werte (Geschwindigkeit, Höhenverlust, Platzhöhe + Kalibrier-Häkchen, Ordner, Streckenpunkte …) und der zuletzt benutzte Ordner je Auswahlfenster werden beim Schließen gespeichert.
- Strafpunkte sind ganze Zahlen (kaufmännisch gerundet).
- Sprache Deutsch/English: Auswahl oben rechts im Tool, wirkt sofort, wird gemerkt (Standard: Systemsprache). Die Excel-Datei (`Zylinderabflug_Report.xlsx` bzw. `Cylinder_Start_Report.xlsx`) wird in der gewählten Sprache ausgegeben. Die Dateien `i18n.py` und `en_dict.py` müssen im selben Ordner liegen wie die anderen `.py`-Dateien.
- Das Fenster passt sich beim Öffnen der Bildschirmgröße an; „Auswertung starten“ bleibt immer sichtbar.

## Noch offen / bekannte Grenzen dieser Version

- Die Website-Analyse wurde gegen den tatsächlichen Seiteninhalt zweier echter
  SoaringSpot-Task-Seiten entwickelt und getestet - der eigentliche Netzwerk-
  abruf selbst (`requests.get`) konnte aus meiner Umgebung heraus nicht gegen
  die echte Seite laufen, da sie von dort nicht erreichbar ist. Bitte beim
  ersten echten Einsatz einmal gegenprüfen, ob der Abruf klappt.
- Für die interne Zielreihenfolge-Prüfung (wann wurde welcher Punkt erreicht,
  fürs Loss of Height) wird nur der Außenradius jeder Zone als Vollkreis
  geprüft, keine genaue Sektor-Winkelbegrenzung - für die eigentliche Wertung
  ist das ohne Belang, das macht SeeYou mit den echten Sektorwerten.
- Getestet wurde die Kernlogik gegen vier reale Wertungstag-IGC-Dateien
  (Normalfall, PEV außerhalb des Zylinders,
  Geschwindigkeitsüberschreitung, Höhendifferenz-Grenzfall) – für den
  produktiven Einsatz als Wettbewerbsleitung bitte trotzdem stichprobenartig
  gegen bekannte SeeYou-Ergebnisse gegenprüfen, bevor darauf vertraut wird.
- Linie- und Sektor-Start-Tage werden vom Tool nicht angefasst (das macht
  SeeYou bereits selbst) – für solche Tage einfach die Original-IGC-Dateien
  direkt in SeeYou verwenden, nicht durch dieses Tool laufen lassen.
