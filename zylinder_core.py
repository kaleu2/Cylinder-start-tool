"""
Zylinderabflug-Auswertetool - Kernlogik
-----------------------------------------
Wertet den Annex-A "Cylinder Start" (SC3A 7.4.4, Edition 2025) aus IGC-Dateien
aus. Reine Standardbibliothek (keine externen Abhaengigkeiten fuer die Logik),
damit das Tool ohne zusaetzliche pip-Installation laeuft.
"""

import bisect
import math
import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from i18n import tr


# =====================================================================
# WGS84-Geodaesie (Vincenty invers) - Annex A verlangt "geodesic distance"
# =====================================================================

WGS84_A = 6378137.0            # große Halbachse (m)
WGS84_F = 1 / 298.257223563    # Abplattung
WGS84_B = WGS84_A * (1 - WGS84_F)


def vincenty_distance_m(lat1, lon1, lat2, lon2, max_iter=200, tol=1e-12):
    """WGS84-Ellipsoid, geodätische Distanz in Metern (Vincenty invers)."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    a, f, b = WGS84_A, WGS84_F, WGS84_B
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    L = math.radians(lon2 - lon1)

    U1 = math.atan((1 - f) * math.tan(phi1))
    U2 = math.atan((1 - f) * math.tan(phi2))
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)

    lam = L
    for _ in range(max_iter):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.sqrt((cosU2 * sin_lam) ** 2 +
                               (cosU1 * sinU2 - sinU1 * cosU2 * cos_lam) ** 2)
        if sin_sigma == 0:
            return 0.0  # identische Punkte
        cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cosU1 * cosU2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha ** 2
        if cos_sq_alpha != 0:
            cos_2sigma_m = cos_sigma - 2 * sinU1 * sinU2 / cos_sq_alpha
        else:
            cos_2sigma_m = 0.0  # Äquator-Sonderfall
        C = f / 16 * cos_sq_alpha * (4 + f * (4 - 3 * cos_sq_alpha))
        lam_prev = lam
        lam = L + (1 - C) * f * sin_alpha * (
            sigma + C * sin_sigma * (
                cos_2sigma_m + C * cos_sigma * (-1 + 2 * cos_2sigma_m ** 2)
            )
        )
        if abs(lam - lam_prev) < tol:
            break

    u_sq = cos_sq_alpha * (a ** 2 - b ** 2) / (b ** 2)
    A = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    B = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta_sigma = B * sin_sigma * (
        cos_2sigma_m + B / 4 * (
            cos_sigma * (-1 + 2 * cos_2sigma_m ** 2) -
            B / 6 * cos_2sigma_m * (-3 + 4 * sin_sigma ** 2) *
            (-3 + 4 * cos_2sigma_m ** 2)
        )
    )
    return b * A * (sigma - delta_sigma)


# =====================================================================
# IGC-Parsing
# =====================================================================

def parse_igc_latlon(lat_str: str, lon_str: str) -> Tuple[float, float]:
    """lat_str: 'DDMMmmmN/S' (7+1 Zeichen), lon_str: 'DDDMMmmmE/W' (8+1 Zeichen)."""
    lat_deg = int(lat_str[0:2])
    lat_min = int(lat_str[2:7]) / 1000.0
    lat = lat_deg + lat_min / 60.0
    if lat_str[-1] == 'S':
        lat = -lat
    lon_deg = int(lon_str[0:3])
    lon_min = int(lon_str[3:8]) / 1000.0
    lon = lon_deg + lon_min / 60.0
    if lon_str[-1] == 'W':
        lon = -lon
    return lat, lon


def hms_to_seconds(hhmmss: str) -> int:
    h, m, s = int(hhmmss[0:2]), int(hhmmss[2:4]), int(hhmmss[4:6])
    return h * 3600 + m * 60 + s


def seconds_to_hms(sec: int) -> str:
    sec = int(round(sec)) % 86400
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class Fix:
    time_s: int
    lat: float
    lon: float
    baro_alt: Optional[int]
    gps_alt: Optional[int]


@dataclass
class IGCFlight:
    path: str
    pilot: str = ""
    comp_id: str = ""
    glider_id: str = ""
    date_str: str = ""          # aus HFDTEDATE, Format "DD.MM.YYYY"
    tz_offset_h: float = 0.0
    fixes: List[Fix] = field(default_factory=list)
    pev_times_s: List[int] = field(default_factory=list)
    all_lines: List[str] = field(default_factory=list)  # Originalzeilen (fuer Kopie/Anhang)

    def fix_at_or_before(self, t_s: int) -> Optional[Fix]:
        best = None
        for fx in self.fixes:
            if fx.time_s <= t_s:
                best = fx
            else:
                break
        return best

    def fixes_after(self, t_s: int):
        return [fx for fx in self.fixes if fx.time_s > t_s]


def parse_igc(path: str) -> IGCFlight:
    flight = IGCFlight(path=path)
    with open(path, 'r', encoding='latin-1', errors='replace') as f:
        lines = f.readlines()
    flight.all_lines = lines

    for line in lines:
        line = line.rstrip('\r\n')
        if not line:
            continue
        rec = line[0]

        if line.startswith('HFPLTPILOT'):
            flight.pilot = line.split(':', 1)[-1].strip()
        elif line.startswith('HFPLTPILOTINCHARGE'):
            if not flight.pilot:
                flight.pilot = line.split(':', 1)[-1].strip()
        elif line.startswith('HFCIDCOMPETITIONID'):
            flight.comp_id = line.split(':', 1)[-1].strip()
        elif line.startswith('HFGIDGLIDERID'):
            flight.glider_id = line.split(':', 1)[-1].strip()
        elif line.startswith('HFDTEDATE'):
            m = re.search(r'(\d{2})(\d{2})(\d{2})', line.split(':', 1)[-1])
            if m:
                dd, mm, yy = m.groups()
                flight.date_str = f"{dd}.{mm}.20{yy}"
        elif line.startswith('HFTZNTIMEZONE'):
            try:
                flight.tz_offset_h = float(line.split(':', 1)[-1].strip())
            except ValueError:
                pass
        elif rec == 'B' and len(line) >= 35:
            try:
                t_s = hms_to_seconds(line[1:7])
                lat, lon = parse_igc_latlon(line[7:15], line[15:24])
                valid = line[24]
                baro = int(line[25:30]) if line[25:30].strip('-').isdigit() else None
                gps = int(line[30:35]) if line[30:35].strip('-').isdigit() else None
                if valid == 'A':  # nur 3D-valide Fixe
                    flight.fixes.append(Fix(t_s, lat, lon, baro, gps))
            except (ValueError, IndexError):
                continue
        elif rec == 'E' and len(line) >= 10:
            # E HHMMSS TTT... ; PEV-Marker
            code = line[7:10]
            if code == 'PEV':
                try:
                    flight.pev_times_s.append(hms_to_seconds(line[1:7]))
                except ValueError:
                    pass

    flight.fixes.sort(key=lambda fx: fx.time_s)
    flight.pev_times_s.sort()
    return flight


# =====================================================================
# Aufgaben-/Parameterdefinition
# =====================================================================

# Schweregrade fuer Hinweise im Report
SEV_INFO = 1      # grau  : normale/irrelevante Hinweise (Aussenlandung, ignorierter PEV, ...)
SEV_WARN = 2      # gelb  : pruefen, aber (noch) keine Strafe
SEV_PENALTY = 3   # rot   : Strafe/ungueltig - wirkt sich auf die Wertung aus

# Die PEV-Intervall-Strafe (nur beim gewerteten Abflug) wird hier eingestuft.
# Nutzerwunsch: rot. Auf SEV_WARN aendern, falls gelb gewuenscht.
SEV_PEV_INTERVAL = SEV_PENALTY


@dataclass
class Note:
    text: str
    sev: int = SEV_INFO


@dataclass
class Zone:
    """Ein zu erreichender Wende-/AAT-Punkt oder das Ziel, in Flugreihenfolge."""
    name: str
    lat: float
    lon: float
    radius_m: float                # R1 (Außenradius)
    is_finish: bool = False
    r_min_m: float = 0.0           # R2 (Innenradius, 0 = kein Sektor-Loch)
    angle_max_deg: float = 180.0   # A1 (180 = Vollkreis)
    angle_min_deg: float = 0.0     # A2
    max_alt_m: float = 0.0         # MaxAlt (0 = keine Höhenbegrenzung)


@dataclass
class TaskParams:
    # Start
    start_lat: float = 0.0
    start_lon: float = 0.0
    start_radius_m: float = 10000.0          # Annex A: Task-Sheet-Wert, Mindestens 10 km
    gate_open_local: str = "00:00:00"        # Toroeffnung in ORTSZEIT (Task Sheet)
    tz_offset_h: float = 0.0
    date_str: str = ""                       # Wertungstag "DD.MM.YYYY" - zur Gegenpruefung je Pilot

    # Annex-A-Konstanten (fest in den Regeln, aber editierbar fuer nationale Abweichungen)
    min_pev_interval_s: int = 600            # 10 Minuten
    pev_cluster_s: int = 30                  # Cluster-Regel
    tolerance_m: float = 0.0                 # PEV ausserhalb bis x m noch akzeptieren (Default: aus)
    tolerance_penalty_pts: float = 50.0
    no_pev_penalty_first_min: float = 5.0
    no_pev_penalty_subsequent_min: float = 10.0
    speed_penalty_per_kmh: float = 2.0
    speed_penalty_cap_kmh: float = 50.0

    # Tagesabhaengige Werte vom Task Sheet
    max_groundspeed_kmh: float = 160.0
    max_loss_of_height_m: float = 800.0
    loh_m_per_point: float = 3.0             # 1 Punkt je 3 m Ueberschreitung
    task_time_str: str = ""                  # AAT-Mindestzeit "HH:MM:SS", leer = Racing Task

    # Baro-Kalibrierung (None = aus -> Hoehen bleiben unkalibrierte Druckhoehe)
    ref_elevation_m: Optional[float] = None  # Flugplatzhoehe MSL am Startplatz
    baro_cal_fixes: int = 60                 # so viele Anfangsfixe (Standphase) mitteln

    # Streckenfuehrung (Wendepunkte/AAT in Reihenfolge, letzter Eintrag = Ziel)
    zones: List[Zone] = field(default_factory=list)


# =====================================================================
# Hilfsfunktionen
# =====================================================================

def round_half_up(x: float) -> int:
    """Kaufmaennisch runden (x,5 -> aufrunden), nicht Pythons Banker-Rundung."""
    return int(math.floor(x + 0.5))


def _haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


def _local_to_utc_seconds(local_hms: str, tz_offset_h: float) -> int:
    h, m, s = (int(x) for x in local_hms.split(':'))
    local_s = h * 3600 + m * 60 + s
    return int(round(local_s - tz_offset_h * 3600)) % 86400


class _CircleTester:
    """Schnelle, aber exakte Innerhalb-Pruefung: Haversine als Vorfilter,
    nur im 1-%-Randbereich wird mit Vincenty (WGS84) nachgerechnet.
    Kreis 0 = Startzylinder, Kreis k = k-te Zone der Aufgabe."""

    def __init__(self, flight: IGCFlight, task: TaskParams):
        self.flight = flight
        self.circles = [(task.start_lat, task.start_lon, task.start_radius_m)]
        for z in task.zones:
            self.circles.append((z.lat, z.lon, z.radius_m))
        n = len(flight.fixes)
        self.cache = [[None] * n for _ in self.circles]

    def inside(self, k: int, i: int) -> bool:
        c = self.cache[k]
        v = c[i]
        if v is None:
            lat, lon, r = self.circles[k]
            fx = self.flight.fixes[i]
            h = _haversine_m(lat, lon, fx.lat, fx.lon)
            if h < r * 0.99:
                v = True
            elif h > r * 1.01:
                v = False
            else:
                v = vincenty_distance_m(lat, lon, fx.lat, fx.lon) <= r
            c[i] = v
        return v


# =====================================================================
# Aufgabenverfolgung ab einem Startkandidaten
# =====================================================================

@dataclass
class FinishResult:
    found: bool
    time_s: Optional[float] = None       # interpoliert (Sekunden, evtl. nicht ganzzahlig)
    baro_alt_raw: Optional[float] = None  # interpolierte unkalibrierte Druckhoehe
    zone_times: List[Tuple[str, int]] = field(default_factory=list)
    reached: int = 0
    missing: List[str] = field(default_factory=list)


def _interpolate_entry(flight: IGCFlight, zone: Zone, i: int):
    """Eintritt in die Zone zwischen Fix i-1 (aussen) und Fix i (innen):
    lineare Interpolation (Position, Zeit, Druckhoehe), Schnittpunkt per Bisektion
    gegen den geodaetischen Zonenradius."""
    a, b = flight.fixes[i - 1], flight.fixes[i]

    def pt(f):
        return a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon)

    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        la, lo_ = pt(mid)
        if vincenty_distance_m(zone.lat, zone.lon, la, lo_) <= zone.radius_m:
            hi = mid
        else:
            lo = mid
    f = hi
    t = a.time_s + f * (b.time_s - a.time_s)
    alt = None
    if a.baro_alt is not None and b.baro_alt is not None:
        alt = a.baro_alt + f * (b.baro_alt - a.baro_alt)
    elif b.baro_alt is not None:
        alt = float(b.baro_alt)
    return t, alt


def _trace_task(flight: IGCFlight, task: TaskParams, tester: _CircleTester,
                times: List[int], t_start: int) -> FinishResult:
    """Ab Startzeit: Zonen der Reihe nach abarbeiten, erster Eintritt je Zone."""
    zones = task.zones
    res = FinishResult(found=False)
    if not zones:
        res.missing = []
        return res
    i0 = bisect.bisect_right(times, t_start)
    k = 0
    n = len(flight.fixes)
    for i in range(i0, n):
        while k < len(zones) and tester.inside(k + 1, i):
            fx = flight.fixes[i]
            res.zone_times.append((zones[k].name, fx.time_s))
            if zones[k].is_finish:
                if i - 1 >= 0 and not tester.inside(k + 1, i - 1):
                    t, alt = _interpolate_entry(flight, zones[k], i)
                else:
                    t = float(fx.time_s)
                    alt = float(fx.baro_alt) if fx.baro_alt is not None else None
                res.found = True
                res.time_s = t
                res.baro_alt_raw = alt
                res.reached = k + 1
                return res
            k += 1
    res.reached = k
    res.missing = [z.name for z in zones[k:]]
    return res


# =====================================================================
# Startermittlung
# =====================================================================

def method_label(method: str) -> str:
    """Anzeigename der Startmethode in der gewaehlten Sprache."""
    return {'PEV': tr('PEV'), 'Ausflug': tr('Ausflug'), 'kein Start': tr('kein Start')}.get(method, method)


@dataclass
class StartResult:
    method: str                     # 'PEV', 'Ausflug' oder 'kein Start'
    time_s: int
    lat: float
    lon: float
    baro_alt: Optional[int]         # unkalibrierte Druckhoehe am Startfix
    distance_to_center_m: float
    notes: List[Note] = field(default_factory=list)
    penalty_points: float = 0.0
    penalty_minutes: float = 0.0
    valid: bool = True
    radius_m: float = 0.0

    @property
    def edge_distance_m(self) -> float:
        """Abstand zum Zylinderrand (negativ = innerhalb)."""
        return self.distance_to_center_m - self.radius_m


@dataclass
class _Cand:
    kind: str            # 'PEV' | 'Ausflug'
    time_s: int
    fix_idx: int
    dist_m: float        # Distanz zum Zylindermittelpunkt
    progress: int = 0
    finished: bool = False


def _cluster_pevs(pev_times: List[int], cluster_s: int) -> Tuple[List[int], int]:
    clustered: List[int] = []
    merged = 0
    for t in pev_times:
        if clustered and t - clustered[-1] <= cluster_s:
            merged += 1
            continue
        clustered.append(t)
    return clustered, merged


def _find_start(flight: IGCFlight, task: TaskParams, tester: _CircleTester,
                times: List[int]):
    """Annex A 7.4.4: gewerteter Startpunkt. Gibt (StartResult, FinishResult) zurueck."""
    notes: List[Note] = []
    gate_s = _local_to_utc_seconds(task.gate_open_local, task.tz_offset_h)
    R = task.start_radius_m
    tol = task.tolerance_m

    # ---- PEV-Kandidaten (nach Toroeffnung) ----
    # Erst nach Zylinder-Zugehoerigkeit filtern, DANACH die 30-s-Regel anwenden:
    # PEVs ausserhalb werden ignoriert und starten keine 30-s-Sequenz; die Sequenz
    # beginnt mit dem ersten PEV im Zylinder.
    raw = [t for t in flight.pev_times_s if t >= gate_s]
    valid_raw = []   # (t, fix_idx, d)
    for t in raw:
        if not flight.fixes:
            break
        i = max(bisect.bisect_right(times, t) - 1, 0)
        fx = flight.fixes[i]
        d = vincenty_distance_m(task.start_lat, task.start_lon, fx.lat, fx.lon)
        if d <= R + tol:
            valid_raw.append((t, i, d))
        else:
            notes.append(Note(tr(
                "nicht relevanter PEV: PEV um {t} UTC ignoriert: {d:.0f} m außerhalb des Zylinders",
                t=seconds_to_hms(t), d=d - R), SEV_INFO))

    pev_cands: List[_Cand] = []
    merged = 0
    for t, i, d in valid_raw:
        if pev_cands and t - pev_cands[-1].time_s <= task.pev_cluster_s:
            merged += 1
            continue
        pev_cands.append(_Cand('PEV', t, i, d))
        if d > R:
            notes.append(Note(tr(
                "PEV um {t} UTC {d:.0f} m außerhalb des Zylinders (innerhalb Toleranz {tol:.0f} m) "
                "-> {pts} Punkte Strafe",
                t=seconds_to_hms(t), d=d - R, tol=tol,
                pts=round_half_up(task.tolerance_penalty_pts)), SEV_PENALTY))
    if merged:
        notes.append(Note(tr(
            "{n} PEV(s) innerhalb von {s} s nach einem PEV im Zylinder zusammengefasst "
            "(zählt als ein PEV zum ersten der Gruppe)", n=merged, s=task.pev_cluster_s),
            SEV_INFO))

    # ---- Ausflug-Kandidaten (nur relevant, wenn kein gueltiger PEV) ----
    def exit_cands() -> List[_Cand]:
        out = []
        n = len(flight.fixes)
        prev_in = None
        for i in range(n):
            cur_in = tester.inside(0, i)
            if prev_in is True and not cur_in and flight.fixes[i].time_s >= gate_s:
                fx = flight.fixes[i]
                d = vincenty_distance_m(task.start_lat, task.start_lon, fx.lat, fx.lon)
                out.append(_Cand('Ausflug', fx.time_s, i, d))
            prev_in = cur_in
        return out

    def best_of(cands: List[_Cand]) -> Tuple[_Cand, FinishResult]:
        """Spaetester Kandidat mit dem groessten Aufgabenfortschritt."""
        best, best_fin = None, None
        for c in cands:
            fin = _trace_task(flight, task, tester, times, c.time_s)
            c.progress = fin.reached
            c.finished = fin.found
            if best is None or c.progress > best.progress or \
                    (c.progress == best.progress and c.time_s >= best.time_s):
                best, best_fin = c, fin
        return best, best_fin

    penalty_points = 0.0
    penalty_minutes = 0.0

    if pev_cands:
        cand, fin = best_of(pev_cands)
        # PEV-Intervall: nur fuer den GEWERTETEN PEV gegen den vorherigen gueltigen PEV
        idx = pev_cands.index(cand)
        if idx >= 1:
            gap = cand.time_s - pev_cands[idx - 1].time_s
            if gap < task.min_pev_interval_s:
                add_min = task.no_pev_penalty_first_min
                penalty_minutes += add_min
                notes.append(Note(tr(
                    "PEV-Intervall zwischen {a} und {b} UTC kürzer als Mindestintervall "
                    "({m} min) -> +{add:.0f} Minuten Strafzeit (vorherige Fälle prüfen: bei "
                    "Wiederholung an einem weiteren Wertungstag +{sub:.0f} Minuten)",
                    a=seconds_to_hms(pev_cands[idx - 1].time_s), b=seconds_to_hms(cand.time_s),
                    m=task.min_pev_interval_s // 60, add=add_min,
                    sub=task.no_pev_penalty_subsequent_min), SEV_PEV_INTERVAL))
        # uebrige Paare: nur grau
        for j in range(1, len(pev_cands)):
            if j == idx:
                continue
            if pev_cands[j].time_s - pev_cands[j - 1].time_s < task.min_pev_interval_s:
                notes.append(Note(tr(
                    "nicht gewerteter PEV: Intervall {a} -> {b} UTC < {m} min "
                    "(ohne Auswirkung, nicht der gewertete PEV)",
                    a=seconds_to_hms(pev_cands[j - 1].time_s), b=seconds_to_hms(pev_cands[j].time_s),
                    m=task.min_pev_interval_s // 60), SEV_INFO))
        if cand is not pev_cands[-1]:
            notes.append(Note(tr(
                "Gewerteter PEV {a} UTC ist nicht der letzte PEV im Zylinder ({b} UTC): nach dem "
                "späteren PEV wäre weniger der Aufgabe geflogen -> bitte prüfen",
                a=seconds_to_hms(cand.time_s), b=seconds_to_hms(pev_cands[-1].time_s)), SEV_WARN))
        if cand.dist_m > R:
            penalty_points += round_half_up(task.tolerance_penalty_pts)
        fx = flight.fixes[cand.fix_idx]
        sr = StartResult('PEV', cand.time_s, fx.lat, fx.lon, fx.baro_alt, cand.dist_m,
                         notes, penalty_points, penalty_minutes)
        return sr, fin

    # kein gueltiger PEV -> Ausflug
    notes.append(Note(tr(
        "Kein gültiger PEV im Zylinder -> Abflugort = Ausflug aus dem Zylinder, "
        "+{m:.0f} Minuten Strafzeit", m=task.no_pev_penalty_first_min), SEV_PENALTY))
    penalty_minutes += task.no_pev_penalty_first_min

    exits = exit_cands()
    if not exits:
        notes.append(Note(tr("Kein Ausflug aus dem Zylinder nach Toröffnung gefunden -> "
                             "kein gültiger Start"), SEV_PENALTY))
        sr = StartResult('kein Start', gate_s, task.start_lat, task.start_lon, None, 0.0,
                         notes, penalty_points, penalty_minutes, valid=False)
        return sr, FinishResult(found=False)

    cand, fin = best_of(exits)
    fx = flight.fixes[cand.fix_idx]
    sr = StartResult('Ausflug', cand.time_s, fx.lat, fx.lon, fx.baro_alt, cand.dist_m,
                     notes, penalty_points, penalty_minutes)
    return sr, fin


def evaluate_start(flight: IGCFlight, task: TaskParams) -> StartResult:
    """Kompatibilitaets-Wrapper (nur Start)."""
    times = [fx.time_s for fx in flight.fixes]
    tester = _CircleTester(flight, task)
    sr, _ = _find_start(flight, task, tester, times)
    return sr


def compute_start_groundspeed(flight: IGCFlight, start: StartResult):
    """Annex A 7.4.4.1: Luftlinie (geodaetisch, WGS84) zwischen Credited-Start-Fix und
    dem Fix, der 8 s DAVOR am naechsten liegt, geteilt durch die tatsaechliche
    Zeitdifferenz. Rueckgabe (km/h, Distanz m, dt s) oder None."""
    target_t = start.time_s - 8
    candidates = [fx for fx in flight.fixes if fx.time_s < start.time_s]
    if not candidates:
        return None
    before = min(candidates, key=lambda fx: abs(fx.time_s - target_t))
    dt = start.time_s - before.time_s
    if dt <= 0:
        return None
    d = vincenty_distance_m(before.lat, before.lon, start.lat, start.lon)
    return (d / dt) * 3.6, d, dt


def compute_start_groundspeed_kmh(flight: IGCFlight, start: StartResult) -> Optional[float]:
    r = compute_start_groundspeed(flight, start)
    return r[0] if r else None


def evaluate_speed_penalty(speed_kmh: Optional[float], task: TaskParams):
    """Geschwindigkeitsstrafe (2 Pkt je km/h ueber Limit, ab Limit+50 kein Start)."""
    if speed_kmh is None:
        return 0.0, [], True
    excess = speed_kmh - task.max_groundspeed_kmh
    if excess <= 0:
        return 0.0, [], True
    if excess > task.speed_penalty_cap_kmh:
        return 0.0, [Note(tr(
            "Groundspeed am Abflug {v:.1f} km/h > {lim:.0f} km/h -> kein gültiger Start",
            v=speed_kmh, lim=task.max_groundspeed_kmh + task.speed_penalty_cap_kmh),
            SEV_PENALTY)], False
    pts = round_half_up(excess * task.speed_penalty_per_kmh)
    return pts, [Note(tr(
        "Groundspeed am Abflug {v:.1f} km/h, {ex:.1f} km/h über Limit ({lim:.0f} km/h) "
        "-> {pts} Punkte Strafe", v=speed_kmh, ex=excess, lim=task.max_groundspeed_kmh,
        pts=pts), SEV_PENALTY)], True


# =====================================================================
# Baro-Kalibrierung (5.4.1: MSL = Druckhoehe - Druckhoehe am Takeoff + Platzhoehe)
# =====================================================================

def compute_baro_offset(flight: IGCFlight, ref_elev_m: float, n_fixes: int = 60):
    """Offset (m), der zur Druckhoehe addiert wird, damit die Standphase am Anfang
    der Aufzeichnung der Referenzhoehe entspricht. Verwendet werden die ersten
    Fixe, solange das Flugzeug steht (< 100 m Weg, Hoehe +-10 m), hoechstens
    n_fixes. Rueckgabe (offset | None, Begruendung)."""
    fixes = [fx for fx in flight.fixes if fx.baro_alt is not None]
    if len(fixes) < 5:
        return None, tr("zu wenige Fixe mit Baro-Höhe")
    first = fixes[0]
    pts = []
    for fx in fixes[:max(5, n_fixes)]:
        if _haversine_m(first.lat, first.lon, fx.lat, fx.lon) > 100 or \
                abs(fx.baro_alt - first.baro_alt) > 10:
            break
        pts.append(fx)
    if len(pts) < 5:
        return None, tr("Aufzeichnung beginnt nicht in einer Standphase (Flugzeug bewegt sich schon)")
    vals = sorted(p.baro_alt for p in pts)
    median = vals[len(vals) // 2]
    return ref_elev_m - median, ""


# =====================================================================
# Gesamtauswertung je Pilot
# =====================================================================

@dataclass
class PilotResult:
    pilot: str
    comp_id: str
    glider_id: str
    flight_date: str
    date_mismatch: bool
    start: StartResult
    speed_kmh: Optional[float]
    speed_detail: str
    speed_penalty_pts: float
    speed_valid: bool
    finish: FinishResult
    start_alt_baro_m: Optional[float]      # ggf. kalibriert
    finish_alt_baro_m: Optional[float]     # ggf. kalibriert, interpoliert
    loss_of_height_baro_m: Optional[float]
    loh_penalty_pts: float
    baro_offset_m: Optional[float]
    baro_cal_text: str
    notes: List[Note]

    @property
    def total_penalty_pts(self) -> float:
        return self.speed_penalty_pts + self.loh_penalty_pts + self.start.penalty_points

    @property
    def worst_sev(self) -> int:
        return max((n.sev for n in self.notes), default=0)

    @property
    def besonderheiten(self) -> List[str]:
        return [n.text for n in self.notes]


def evaluate_pilot(flight: IGCFlight, task: TaskParams) -> PilotResult:
    notes: List[Note] = []
    date_mismatch = False
    if task.date_str and flight.date_str and flight.date_str != task.date_str:
        date_mismatch = True
        notes.append(Note(tr(
            "ACHTUNG: Datum in der IGC-Datei ({a}) weicht vom eingestellten Wertungstag ({b}) ab "
            "- falsche Datei/falscher Tag?", a=flight.date_str, b=task.date_str),
            SEV_PENALTY))

    times = [fx.time_s for fx in flight.fixes]
    tester = _CircleTester(flight, task)
    start, fin = _find_start(flight, task, tester, times)
    start.radius_m = task.start_radius_m
    notes.extend(start.notes)

    # Baro-Kalibrierung
    offset = None
    cal_text = tr("aus (unkalibriert)")
    if task.ref_elevation_m is not None:
        offset, why = compute_baro_offset(flight, task.ref_elevation_m, task.baro_cal_fixes)
        if offset is None:
            cal_text = tr("nicht möglich: {why}", why=why)
            notes.append(Note(tr("Baro nicht kalibriert: {why} - Höhen sind unkalibrierte "
                                 "Druckhöhen (Höhenverlust bleibt korrekt)", why=why), SEV_WARN))
        else:
            cal_text = tr("Offset {o:+.0f} m auf {r:.0f} m", o=offset, r=task.ref_elevation_m)

    speed_kmh = None
    speed_detail = ""
    speed_pts = 0.0
    speed_valid = True
    start_alt = finish_alt = loss = None
    loh_pts = 0

    if start.valid:
        gs = compute_start_groundspeed(flight, start)
        if gs:
            speed_kmh = gs[0]
            speed_detail = tr("{d:.0f} m in {t:.0f} s", d=gs[1], t=gs[2])
        speed_pts, speed_notes, speed_valid = evaluate_speed_penalty(speed_kmh, task)
        notes.extend(speed_notes)

        if start.baro_alt is not None:
            start_alt = start.baro_alt + (offset or 0.0)
        if fin.found:
            if fin.baro_alt_raw is not None:
                finish_alt = fin.baro_alt_raw + (offset or 0.0)
            if start.baro_alt is not None and fin.baro_alt_raw is not None:
                loss = start.baro_alt - fin.baro_alt_raw   # Offset kuerzt sich heraus
                excess = loss - task.max_loss_of_height_m
                if excess > 0:
                    loh_pts = (round_half_up(excess / task.loh_m_per_point)
                               if task.loh_m_per_point > 0 else 0)
                    notes.append(Note(tr(
                        "Loss of Height (baro) {loss:.0f} m, {ex:.0f} m über Limit ({lim:.0f} m) "
                        "-> Strafe nach 7.4.4.7: {pts} Punkte (1 Pkt/{per:g} m, kaufmännisch gerundet)",
                        loss=loss, ex=excess, lim=task.max_loss_of_height_m, pts=loh_pts,
                        per=task.loh_m_per_point), SEV_PENALTY))
        elif task.zones:
            notes.append(Note(tr(
                "Aufgabe nicht vollständig - fehlend: {names}", names=', '.join(fin.missing)),
                SEV_INFO))
    elif task.zones:
        notes.append(Note(tr("Aufgabe nicht ausgewertet (kein gültiger Start)"), SEV_INFO))

    if not task.zones:
        notes.append(Note(tr("Keine Streckenpunkte definiert - Ziel/Höhenverlust nicht geprüft"),
                          SEV_WARN))

    notes.sort(key=lambda n: -n.sev)
    return PilotResult(
        pilot=flight.pilot, comp_id=flight.comp_id, glider_id=flight.glider_id,
        flight_date=flight.date_str, date_mismatch=date_mismatch,
        start=start, speed_kmh=speed_kmh, speed_detail=speed_detail,
        speed_penalty_pts=speed_pts, speed_valid=speed_valid, finish=fin,
        start_alt_baro_m=start_alt, finish_alt_baro_m=finish_alt,
        loss_of_height_baro_m=loss, loh_penalty_pts=loh_pts,
        baro_offset_m=offset, baro_cal_text=cal_text, notes=notes,
    )


# =====================================================================
# Export: LSEEYOU-Mini-Zylinder-Block anhaengen
# =====================================================================

def format_lat_lseeyou(lat: float) -> str:
    hemi = 'N' if lat >= 0 else 'S'
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60
    return f"{deg:02d}{minutes:06.3f}{hemi}"


def format_lon_lseeyou(lon: float) -> str:
    hemi = 'E' if lon >= 0 else 'W'
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60
    return f"{deg:03d}{minutes:06.3f}{hemi}"


def format_latlon_crecord(lat: float, lon: float) -> str:
    def lat_part(lat):
        hemi = 'N' if lat >= 0 else 'S'
        lat = abs(lat)
        deg = int(lat)
        mmm = round((lat - deg) * 60 * 1000)
        return f"{deg:02d}{mmm:05d}{hemi}"

    def lon_part(lon):
        hemi = 'E' if lon >= 0 else 'W'
        lon = abs(lon)
        deg = int(lon)
        mmm = round((lon - deg) * 60 * 1000)
        return f"{deg:03d}{mmm:05d}{hemi}"

    return lat_part(lat) + lon_part(lon)


def build_seeyou_block(start: StartResult, task: TaskParams, start_label: str = "CylStart") -> List[str]:
    """Erzeugt einen vollstaendigen LSEEYOU-Aufgabenblock (Start als 1-m-Mini-
    Zylinder, danach die Streckenpunkte) - nur fuer den Fall, dass die Eingabe-
    IGC noch KEINEN SoaringSpot-Aufgabenblock enthaelt (z. B. CUP-/manuelle
    Eingabe). Existiert bereits ein SoaringSpot-Block, wird stattdessen NUR
    die Start-Zeile darin ersetzt (siehe soaringspot_block.replace_start_in_block)."""
    lines = []
    lines.append(f"LCU::C{format_latlon_crecord(start.lat, start.lon)}{start_label}")
    for z in task.zones:
        lines.append(f"LCU::C{format_latlon_crecord(z.lat, z.lon)}{z.name}")

    lines.append(
        f"LSEEYOU OZ=-1,Style=2,SpeedStyle=0,R1=1m,A1=180,R2=0m,A2=0,MaxAlt=0.0m"
    )
    for i, z in enumerate(task.zones):
        style = 3 if z.is_finish else 1
        lines.append(
            f"LSEEYOU OZ={i},Style={style},SpeedStyle={2 if z.is_finish else 1},"
            f"R1={int(z.radius_m)}m,A1={z.angle_max_deg:g},"
            f"R2={int(z.r_min_m)}m,A2={z.angle_min_deg:g},"
            f"MaxAlt={z.max_alt_m:g}m" +
            ("" if z.is_finish else ",AAT=1")
        )

    tsk_parts = [f"NoStart={task.gate_open_local}"]
    if task.task_time_str:
        tsk_parts.append(f"TaskTime={task.task_time_str}")
    lines.append("LSEEYOU TSK," + ",".join(tsk_parts) + ",MultiStart=False")
    lines.append(f"LCU::HPTZNTIMEZONE:{task.tz_offset_h:g}")
    return lines


def write_output_igc(flight: IGCFlight, start: StartResult, task: TaskParams, out_path: str):
    """Bevorzugt: bestehenden SoaringSpot-Kommentarblock in der Datei findet und
    NUR die Start-Deklaration darin ersetzt (Annex-A-konform, Rest der von
    SoaringSpot bekannten Aufgabe bleibt unangetastet). Nur wenn kein solcher
    Block gefunden wird (z. B. reine CUP-/manuelle Eingabe ohne SoaringSpot-
    Download), wird ein neuer Block ans Dateiende angehaengt."""
    from soaringspot_block import find_soaringspot_block, replace_start_in_block

    lines = [ln.rstrip('\r\n') for ln in flight.all_lines]
    ss_block = find_soaringspot_block(lines)

    if ss_block is not None:
        out_lines = replace_start_in_block(lines, ss_block, start)
    else:
        out_lines = lines + build_seeyou_block(start, task)

    with open(out_path, 'w', encoding='latin-1', errors='replace', newline='') as f:
        for ln in out_lines:
            f.write(ln + '\r\n')
