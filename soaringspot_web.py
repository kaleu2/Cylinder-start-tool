"""
Liest die SoaringSpot-Task-/Briefing-Seite (VOR dem Flug, z. B.
https://www.soaringspot.com/en_gb/<comp>/tasks/<klasse>/task-N-on-<datum>)
und extrahiert Streckenpunkte, Beobachtungszonen-Geometrie, Aufgabenzeit und
die freien "Task notes". Diese Seite enthaelt KEINE Koordinaten - die muessen
zusaetzlich aus einer CUP-Datei anhand des Namens zugeordnet werden
(siehe match_names_to_cup in dieser Datei).

Benoetigt 'requests' und 'beautifulsoup4' (siehe install.bat/build_exe.bat).
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

from i18n import tr

try:
    import requests
    from bs4 import BeautifulSoup
    WEB_IMPORT_AVAILABLE = True
except ImportError:
    WEB_IMPORT_AVAILABLE = False


@dataclass
class TaskPageTurnpoint:
    name: str
    radius_m: Optional[float] = None    # Aussenradius (Rmax bzw. Cylinder R)
    r_min_m: float = 0.0                # Rmin, falls Sektor
    angle_deg: float = 180.0            # Sektor-Oeffnungswinkel (180 = Vollkreis)
    is_line: bool = False
    raw_oz_text: str = ""


@dataclass
class TaskPageInfo:
    turnpoints: List[TaskPageTurnpoint] = field(default_factory=list)
    task_duration: Optional[str] = None   # "HH:MM:SS", nur bei AAT vorhanden
    task_notes: Optional[str] = None
    inactive_airspaces: Optional[str] = None
    date_str: Optional[str] = None        # "DD.MM.YYYY", aus der Seitenüberschrift


_URL_RE = re.compile(
    r'^(?P<base>https?://[^/]+/[^/]+/[^/]+)/(?P<kind>tasks|results)/(?P<cls>[^/]+)/'
    r'(?P<task>task-\d+-on-(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2}))(?:/.*)?$', re.IGNORECASE)


def normalize_task_url(url: str):
    """Wandelt auch Ergebnis-/Unterseiten-Links (…/results/<klasse>/task-N-on-DATUM/daily)
    in den Link der Task-Seite (…/tasks/<klasse>/task-N-on-DATUM) um.
    Rueckgabe: (task_url, date_str 'TT.MM.JJJJ', wurde_umgewandelt).
    Wirft ValueError, wenn der Link keinen konkreten Wertungstag enthaelt."""
    url = url.strip().split('#')[0].split('?')[0]
    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = 'https://' + url.lstrip('/')
    m = _URL_RE.match(url)
    if not m:
        raise ValueError(tr(
            "Der Link enthält keinen konkreten Wertungstag (erwartet z. B. "
            "…/tasks/standard/task-1-on-2026-07-13 oder …/results/standard/task-1-on-2026-07-13/daily)."))
    task_url = f"{m['base']}/tasks/{m['cls']}/{m['task']}"
    date_str = f"{m['d']}.{m['m']}.{m['y']}"
    return task_url, date_str, (m['kind'].lower() != 'tasks' or task_url != url)


def fetch_task_page_html(url: str, timeout: int = 15) -> str:
    if not WEB_IMPORT_AVAILABLE:
        raise RuntimeError(tr(
            "Die Pakete 'requests' und 'beautifulsoup4' fehlen. Bitte install.bat "
            "bzw. build_exe.bat erneut ausführen (installiert sie automatisch)."))
    headers = {"User-Agent": "Mozilla/5.0 (Zylinderabflug-Auswertetool)"}
    resp = requests.get(url, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp.text


_RMINMAX_RE = re.compile(
    r'Rmin\s*=\s*([\d.]+)\s*km.*?Rmax\s*=\s*([\d.]+)\s*km(?:.*?Angle\s*=\s*([\d.]+)\s*°)?',
    re.IGNORECASE | re.DOTALL,
)
_CYLINDER_RE = re.compile(r'Cylinder\s*R\s*=\s*([\d.]+)\s*km', re.IGNORECASE)
_LINE_RE = re.compile(
    r'Line\s*([\d.]+)\s*km\s*(?:\(Radius\s*([\d.]+)\s*km\))?', re.IGNORECASE
)


def _parse_observation_zone(text: str) -> Tuple[Optional[float], float, float, bool]:
    """Gibt (radius_m, r_min_m, angle_deg, is_line) zurueck."""
    text = text.strip()

    line_m = _LINE_RE.search(text)
    if line_m:
        radius_km = line_m.group(2) or line_m.group(1)
        return float(radius_km) * 1000.0, 0.0, 180.0, True

    rminmax_m = _RMINMAX_RE.search(text)
    if rminmax_m:
        r_min_km = float(rminmax_m.group(1))
        r_max_km = float(rminmax_m.group(2))
        angle = float(rminmax_m.group(3)) if rminmax_m.group(3) else 180.0
        return r_max_km * 1000.0, r_min_km * 1000.0, angle, False

    cyl_m = _CYLINDER_RE.search(text)
    if cyl_m:
        return float(cyl_m.group(1)) * 1000.0, 0.0, 180.0, False

    return None, 0.0, 180.0, False


_MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_heading_date(page_text: str) -> Optional[str]:
    m = re.search(r'\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b', page_text)
    if not m:
        return None
    day, month_name, year = m.groups()
    month = _MONTHS_EN.get(month_name.lower())
    if not month:
        return None
    return f"{int(day):02d}.{month:02d}.{year}"


def parse_task_page(html: str) -> TaskPageInfo:
    soup = BeautifulSoup(html, "html.parser")
    info = TaskPageInfo()

    table = None
    for t in soup.find_all("table"):
        header_text = t.get_text(" ", strip=True).lower()
        if "turnpoint" in header_text and "observation zone" in header_text:
            table = t
            break
    if table is None:
        raise ValueError(tr("Konnte keine Streckenpunkt-Tabelle auf dieser Seite finden. "
                            "Ist die URL wirklich eine SoaringSpot-'Task'-Seite (nicht 'results')?"))

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells or len(cells) < 4:
            continue
        first_cell = cells[0].get_text(strip=True)
        if first_cell.lower() in ("turnpoint", "total:", "total", ""):
            continue
        name = first_cell
        oz_text = cells[3].get_text(" ", strip=True)
        radius_m, r_min_m, angle_deg, is_line = _parse_observation_zone(oz_text)
        info.turnpoints.append(TaskPageTurnpoint(
            name=name, radius_m=radius_m, r_min_m=r_min_m,
            angle_deg=angle_deg, is_line=is_line, raw_oz_text=oz_text,
        ))

    page_text = soup.get_text("\n", strip=True)
    m = re.search(r'Task duration:\s*([\d:]+)', page_text)
    if m:
        info.task_duration = m.group(1)
    info.date_str = _parse_heading_date(page_text)

    notes_header = soup.find(string=re.compile(r'Task notes', re.IGNORECASE))
    if notes_header:
        container = notes_header.find_parent()
        notes_block = None
        sib = container
        for _ in range(5):
            sib = sib.find_next_sibling() if sib else None
            if sib is None:
                break
            text = sib.get_text("\n", strip=True)
            if text:
                notes_block = text
                break
        info.task_notes = notes_block

    m2 = re.search(r'Inactive airspaces:\s*(.+)', page_text)
    if m2:
        info.inactive_airspaces = m2.group(1).strip()

    return info


def match_names_to_cup(turnpoints: List[TaskPageTurnpoint],
                        cup_points: List[Tuple[str, float, float]]
                        ) -> Tuple[Dict[str, Tuple[float, float]], List[str]]:
    """Ordnet Task-Seiten-Namen den Koordinaten aus einer CUP-Datei zu.
    Gibt (name -> (lat, lon), Liste nicht gefundener Namen) zurueck."""
    def norm(s: str) -> str:
        return re.sub(r'[\s_\-]', '', s).lower()

    cup_by_norm = {norm(name): (lat, lon) for name, lat, lon in cup_points}

    resolved = {}
    unresolved = []
    for tp in turnpoints:
        key = norm(tp.name)
        if key in cup_by_norm:
            resolved[tp.name] = cup_by_norm[key]
        else:
            # Versuch: Namen ohne evtl. fuehrenden Zahlencode (z.B. "213WASOS" -> "WASOS")
            stripped = re.sub(r'^\d+', '', key)
            match = next((v for k, v in cup_by_norm.items() if re.sub(r'^\d+', '', k) == stripped), None)
            if match:
                resolved[tp.name] = match
            else:
                unresolved.append(tp.name)
    return resolved, unresolved
