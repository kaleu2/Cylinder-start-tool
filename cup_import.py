"""Minimaler SeeYou-CUP-Parser: liest Name/Lat/Lon aus einer .cup-Datei."""

import csv
import io


def _parse_cup_coord(s: str, is_lat: bool) -> float:
    """CUP-Koordinate wie '5145.317N' oder '01757.867E' -> Dezimalgrad."""
    s = s.strip()
    if not s:
        raise ValueError("leere Koordinate")
    hemi = s[-1].upper()
    num = s[:-1]
    deg_len = 2 if is_lat else 3
    deg = int(num[:deg_len])
    minutes = float(num[deg_len:])
    value = deg + minutes / 60.0
    if hemi in ('S', 'W'):
        value = -value
    return value


def parse_cup_file(path: str):
    """Gibt eine Liste von (name, lat, lon) zurueck."""
    points = []
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        content = f.read()

    lines = content.splitlines()
    reader = csv.reader(lines)
    started_data = False
    for row in reader:
        if not row:
            continue
        first = row[0].strip()
        if first.startswith('-----'):
            break  # Ende des Waypoint-Blocks (Task-Sektion folgt)
        if first.lower() == 'name':
            started_data = True
            continue
        if len(row) < 4:
            continue
        try:
            name = row[0].strip().strip('"')
            lat = _parse_cup_coord(row[3], is_lat=True)
            lon = _parse_cup_coord(row[4], is_lat=False)
        except (ValueError, IndexError):
            continue
        points.append((name, lat, lon))
    return points
