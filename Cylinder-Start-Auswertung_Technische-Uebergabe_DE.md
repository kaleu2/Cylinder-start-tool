# Technische Übergabe: Cylinder-Start-Auswertung (Annex A 7.4.4)

*(English version: [Cylinder-Start-Evaluation_Technical-Handover_EN.md](Cylinder-Start-Evaluation_Technical-Handover_EN.md))*

Zweck dieses Dokuments: alle Regeln, Formeln und Algorithmus-Entscheidungen, die
für die Auswertung des Annex-A-"Cylinder Start" nötig sind, damit sie sich in
PySoar nachbauen lassen. Quelle: FAI Sporting Code Section 3, Annex A, Edition
2025, Abschnitt 7.4.4 ("Cylinder Start Procedures"), sowie die allgemeinen
Abschnitte 7.4.2 ("Common Start Procedures") und 5.4.1 (Höhenbestimmung). Alle
Regeltexte unten sind paraphrasiert, nicht wörtlich zitiert - im Zweifel gegen
die Originalquelle gegenprüfen, falls eine neuere Edition als 2025 gilt.

Eine lauffähige Referenzimplementierung (Python, Standardbibliothek + reines
WGS84-Vincenty, keine Abhängigkeit von opensoar nötig) existiert bereits als
Grundlage: `zylinder_core.py` (Kernlogik), `soaringspot_block.py` /
`soaringspot_web.py` (Aufgaben-Import). Dieses Dokument beschreibt, *was* und
*warum* dort passiert, damit es sich 1:1 in PySoar portieren lässt.

## 1. Geodätisches Modell

Annex A definiert Distanzen, Radien und Linien ausdrücklich als **Geodäten auf
dem WGS84-Ellipsoid** - nicht als Kugelnäherung (Haversine) und nicht als die
vereinfachte "FAI-Sphäre", die anderswo für reine Streckenwertung verwendet
wird. Für Zylinder-Radius-Prüfungen (10+ km) und die Start-Groundspeed-Messung
macht das einen spürbaren Unterschied (mehrere Meter bis niedrige
zweistellige Meter), gerade an der Zylindergrenze.

Verwendet wird die **Vincenty-Invers-Formel** (iterativ, WGS84-Halbachsen
a=6378137 m, Abplattung f=1/298.257223563). Reine Python-Implementierung ohne
Abhängigkeiten liegt in `zylinder_core.vincenty_distance_m()` vor - kann 1:1
übernommen werden, falls PySoar nicht schon eine äquivalente Funktion hat
(z. B. via `geographiclib`/`pyproj`, falls das als Abhängigkeit akzeptabel ist
- liefert praktisch identische Ergebnisse).

Performance-Hinweis: Die Referenzimplementierung nutzt Haversine nur als
Vorfilter (außerhalb eines ±1-%-Bandes um den Radius ist das Ergebnis sicher)
und rechnet nur innerhalb dieses Bandes mit Vincenty.

## 2. Ablauf der Start-Ermittlung (Annex A 7.4.4)

Eingaben: Zylindermittelpunkt (lat/lon), Zylinderradius (Task Sheet, Annex-A-
Minimum 10 km), Toröffnungszeit (Ortszeit, Task Sheet), Zeitzonen-Offset,
die Liste der PEV-Events (E-Records, Code `PEV`) aus der IGC-Datei, sowie alle
B-Record-Fixe.

**Schritt 1 - PEVs vor Toröffnung verwerfen.** Nur PEVs mit Zeitstempel ≥
Toröffnungszeit (in UTC umgerechnet) werden betrachtet. Ein PEV vor
Toröffnung zählt nicht als Start-Ereignis.

**Schritt 2 - 30-Sekunden-Cluster-Regel.** Mehrere PEVs innerhalb von 30
Sekunden werden als **ein** PEV behandelt (Zeitpunkt des ersten der Gruppe).
Die Reihenfolge ist wichtig: **erst** nach Zylinder-Zugehörigkeit filtern
(Schritt 3), **dann** clustern - ein PEV außerhalb startet keine
30-s-Sequenz, sie beginnt mit dem ersten PEV im Zylinder.
Diese Regel gilt für Cylinder Start genauso wie für die Line-Start-PEV-Option,
die PySoar schon nutzt - **nicht verwechseln mit dem Mindestintervall** (siehe
Schritt 4): die 30-Sekunden-Regel ist reines Entprellen von Mehrfachklicks,
kein Gültigkeits-Kriterium.

**Schritt 3 - Zylinder-Zugehörigkeit je PEV prüfen** (geodätische Distanz
PEV-Fix ↔ Zylindermittelpunkt, WGS84):
- Distanz ≤ Zylinderradius → PEV gültig, zählt als möglicher Start
- Distanz > Zylinderradius → PEV wird **ignoriert**. Die Meldung nennt den
  Abstand zum **Rand** (Distanz − Radius), nicht zum Mittelpunkt.
- Optional (Parameter `tolerance_m`, Default **0 = aus**): PEV bis x m außerhalb
  bleibt gültig mit 50 Punkten Strafe. Die 0,5-km/50-Punkte-Regel (8.7) bezieht
  sich laut Annex-Text auf "kein Fix im Zylinder" und ist hier **nicht** als
  PEV-Toleranz implementiert - nur für nationale Sonderregeln gedacht.

**Schritt 4 - Mindest-PEV-Intervall (nur für den GEWERTETEN PEV).** Der
gewertete PEV wird mit dem davor liegenden gültigen PEV verglichen. Liegen
weniger als **10 Minuten** dazwischen, bleibt der Start gültig, aber es gibt
**+5 Minuten Zeitstrafe**. Die 10 Minuten gelten erst bei Wiederholung an einem
weiteren Wertungstag - das kann das Tool nicht wissen, daher steht im Report
der Hinweis "vorherige Fälle prüfen". Verstöße zwischen anderen, nicht
gewerteten PEV-Paaren haben keine Wirkung (im Report nur grau).

**Schritt 5 - Startpunkt bestimmen.** Unter den gültigen PEVs (nach
Toröffnung, geclustert) wird der **späteste mit dem größten Aufgabenfortschritt**
gewählt (Fortschritt = Anzahl der Zonen, die ab diesem Start der Reihe nach
erreicht werden). Normalfall: das ist der letzte PEV. Ist der letzte PEV
schlechter als ein früherer (z. B. erst nach dem Ziel gedrückt), wird ein
Prüfhinweis erzeugt. Credited Start Time/Point/Altitude = Zeitstempel/Position/
Höhe des zugehörigen B-Record-Fixes (der Mini-Zylinder braucht einen echten Fix,
keine Interpolation).

**Schritt 6 - Fallback ohne gültigen PEV.** Liegt kein PEV im Zylinder, ist der
Start ein **Ausflug aus dem Zylinder** nach Toröffnung (letzter Fix innen →
erster Fix außen) mit +5 Minuten Zeitstrafe. Es gibt oft mehrere Ausflüge
(Randflug, Wiedereinflug, Ausflug nach dem Ziel!). Gewählt wird daher
**nicht** blind der letzte Ausflug, sondern der späteste Ausflug mit dem
größten Aufgabenfortschritt - sonst wird z. B. ein Ziel am Zylinderrand
(Ausflug nach dem Zielüberflug) fälschlich zum Start.

Falls nach Toröffnung nie ein Ausflug aus dem Zylinder stattfindet: kein
gültiger Start.

## 3. Groundspeed am Abflug

Eigene, vom Line-Start abweichende Formel (7.4.4.1): Strecke zwischen dem
**Credited-Start-Fix** und dem Fix **circa 8 Sekunden davor** (nicht
gemittelt über davor+danach wie beim Linienstart), geteilt durch die
verstrichene Zeit zwischen beiden Fixen. Ergebnis in km/h.

Strafstaffel (8.7): Überschreitung der im Task Sheet festgelegten maximalen
Abfluggeschwindigkeit → **2 Punkte je km/h** Überschreitung, bis 50 km/h über
dem Limit. Darüber: **kein gültiger Start mehr**. Alle Strafpunkte werden
**kaufmännisch auf ganze Zahlen gerundet** (x,5 wird aufgerundet).

## 4. Loss of Height (Höhenverlust Start → Ziel)

Definiert als **Start-Höhe minus Ziel-Höhe** (7.4.4.1/7.4.4.7), beides MSL.
**Wichtig:** MSL-Höhe wird laut Annex A 5.4.1 aus der **barometrischen**
Höhendifferenz zum Startpunkt plus Feldhöhe abgeleitet - **nicht** aus der
rohen GPS-Höhe (in den Testdaten: "1 m über dem Limit" Baro vs. "27 m" GPS).
Immer `baro_alt` der B-Records verwenden. Die **Zielhöhe wird zwischen dem Fix
vor und dem Fix nach dem Einflug in den Zielzylinder interpoliert** (Schnittpunkt
per Bisektion gegen den geodätischen Radius, Zeit und Druckhöhe linear).

Baro-Kalibrierung (optional): die Standphase am Anfang der Datei (Flugzeug
steht: < 100 m Weg, ±10 m Höhe) wird auf die Platzhöhe gesetzt. Der
Höhenverlust ändert sich dadurch nicht (Offset kürzt sich), nur die
ausgewiesenen Abflug-/Ankunftshöhen.

Überschreitet der Loss of Height das Maximum, gibt es eine Strafe proportional
zum Überschuss: im Tool **1 Punkt je 3 m** (Parameter `loh_m_per_point`, Wert
aus der Vorgabe des Auftraggebers - im Annex-Auszug steht nur "proportional"),
gedeckelt auf die erreichten Speed-Punkte bzw. 15 % des Tagesbestwerts
(7.4.4.7). Die Deckelung übernimmt SeeYou; der Report nennt die ungedeckelte
Punktzahl.

## 5. Zielankunft-Ermittlung - ein Fallstrick

Für Loss-of-Height und Report muss bekannt sein, **wann** das Ziel erreicht
wurde. Eine reine "ist der Pilot innerhalb des Zielradius"-Prüfung über den
ganzen Flug ist **falsch** und liefert False-Positives: Bei Cylinder-Start-
Taktik ("Start-anywhere") liegt der gewertete Startpunkt oft geografisch
bereits innerhalb des Zielradius (nahe am Flugplatz) - eine naive
Abstandsprüfung meldet dann sofort "Ziel erreicht", obwohl noch kein einziger
Wendepunkt/AAT-Bereich abgeflogen wurde.

Richtig: **Reihenfolge-abhängige Prüfung.** Erst wenn alle Wende-/AAT-Zonen in
der deklarierten Reihenfolge je einmal durch einen Fix bestätigt wurden
(einfacher Abstandstest reicht dafür, Annex A 7.9.1 "Completed Task"), zählt
der erste danach folgende Eintritt in die Zielzone als Zielankunft. Vereinfachung in der Referenzimplementierung: nur der Außenradius jeder Zone
wird als Vollkreis geprüft, keine exakte Sektor-Winkelbegrenzung - für die
Zeit-/Höhenermittlung ausreichend genau, die eigentliche Wertung macht ohnehin
SeeYou mit den echten Sektorwerten.

## 6. Abgrenzung zur bestehenden Line-Start-PEV-Logik in PySoar

PySoar wertet nach bisherigem Stand die PEV-Option des **Linienstarts**
(7.4.3) aus, mit der Regel "ein PEV ist ungültig, wenn er weniger als 30
Sekunden nach dem letzten validen PEV liegt". Das ist ein **separates
Regelwerk** mit eigener Mechanik (PEV Wait Time, Start Window) und hat
**nichts mit dem Cylinder-Start-Mindestintervall von 10 Minuten** zu tun.
Für eine Erweiterung um Cylinder Start empfiehlt sich ein eigener Codepfad
statt der Versuch, beide PEV-Mechanismen in eine Funktion zu pressen - die
Gültigkeitsbedingungen, Zeitfenster und Strafmechanik unterscheiden sich an
mehreren Stellen (siehe Abschnitte 2-4).

## 7. Woher die Aufgaben-Parameter kommen

Zwei nutzbare Quellen, beide bereits implementiert und gegen echte Daten
getestet:

- **SoaringSpot-Task-Seite** (`.../tasks/<klasse>/task-N-on-<datum>`, NICHT
  die `results`-Seite - ein Ergebnis-Link lässt sich umwandeln, indem `/results/`
  durch `/tasks/` ersetzt und alles nach `task-N-on-<datum>` abgeschnitten wird): HTML-Tabelle mit Wendepunkt-Namen, Entfernung,
  Richtung und Beobachtungszone (Radius/Sektor-Winkel als Text, z. B.
  `Cylinder R=10.00 km` oder `Rmin=0.50 km, Rmax=10.00 km, Angle=90.0°`).
  Liefert **keine Koordinaten** - die müssen zusätzlich aus einer CUP-Datei
  über den Namen zugeordnet werden (Normalisierung nötig: Groß-/Kleinschreibung,
  Leerzeichen/Unterstriche, siehe `soaringspot_web.match_names_to_cup()`).
  Freitext-"Task notes" (falls vom Ausrichter gepflegt) enthalten oft
  Toröffnung, Max. Groundspeed, Max. Loss of Height - aber nicht
  strukturiert, nur als Fließtext zum manuellen Übertragen.
- **SoaringSpot-IGC-Kommentarblock**: Jede über SoaringSpot heruntergeladene
  IGC-Datei enthält die Aufgabe bereits als `LCU::C...`/`LSEEYOU OZ=...`/
  `LSEEYOU TSK...`-Kommentarzeilen (siehe `soaringspot_block.py`, Format
  entspricht `opensoar.competition.soaringspot`). **Achtung:** Das greift nur
  bei bereits über SoaringSpot verarbeiteten Dateien - die rohen, direkt von
  den Piloten eingesammelten Dateien (vor der eigentlichen Wertung) haben
  diesen Block noch nicht, da er erst beim SoaringSpot-Upload entsteht.

## 8. IGC-Validität beim Zurückschreiben

Wird die Aufgabe (korrigierter Startpunkt als Mini-Zylinder, 1 m Radius um
den Credited Start Point) in die IGC-Datei geschrieben, geschieht das
ausschließlich über **L-Records** (`LCU::`/`LSEEYOU`, Zeilen beginnend mit
"L"). Das ist bewusst so gewählt: L-Records liegen in allen geprüften
Testdateien *nach* dem G-Record (digitale Signatur) und werden auch von
SoaringSpot selbst nachträglich angehängt, ohne die Signatur zu brechen -
L-Records sind im IGC-Format für genau solche nachträglichen Anmerkungen
vorgesehen. B-Records, der G-Record selbst oder sonstige Records werden nie
verändert. Trotzdem: vor Produktiveinsatz einmal gegen einen echten
IGC-Validator (z. B. CIVL Open Validation Server) prüfen, falls PySoar das
nicht ohnehin schon tut.

## 9. Offene Punkte / bekannte Grenzen

- Der Live-Netzwerkabruf der SoaringSpot-Task-Seite wurde gegen zwei echte,
  gespeicherte Seiteninhalte getestet, nicht gegen einen echten Live-Request
  aus der Zielumgebung heraus (Netzwerkbeschränkung in der Entwicklungsumgebung).
- Die Observation-Zone-Textmuster (`Cylinder R=...`, `Rmin=.../Rmax=.../Angle=...`,
  `Line ... (Radius ...)`) wurden nur anhand der zwei gesehenen Seiten
  abgeleitet - bei anderen SoaringSpot-Versionen/Sprachen ggf. abweichend,
  Regex in `soaringspot_web._parse_observation_zone()` entsprechend anpassen.
- Referenzimplementierung geht von Racing-Task- und AAT-Zonen mit A1=180
  (Vollkreis) aus; echte enge Sektoren werden für die Zeit-/Reihenfolgeprüfung
  nur als Vollkreis angenähert (siehe Abschnitt 5).
- Die Loss-of-Height-Rate (1 Punkt je 3 m) stammt nicht aus dem gelesenen
  Annex-Auszug, sondern wurde vom Auftraggeber vorgegeben und ist einstellbar.
- Die mehrtägige Eskalation der PEV-Intervall-Strafe (5 → 10 Minuten) lässt
  sich aus den Dateien eines einzelnen Tages nicht ableiten.
- Oberfläche und Excel-Report gibt es auf Deutsch und Englisch (`i18n.py`,
  `en_dict.py`); der deutsche Text ist zugleich der Übersetzungsschlüssel.
