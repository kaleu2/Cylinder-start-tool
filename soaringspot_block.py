"""
Liest den von SoaringSpot beim Download angehängten Kommentarblock
(LCU::C.../LSEEYOU OZ=.../LSEEYOU TSK...) aus einer IGC-Datei und kann darin
gezielt NUR die Start-Deklaration ersetzen (Annex-A-Zylinderauswertung),
ohne den Rest der von SoaringSpot bekannten Aufgabe anzutasten.

Format-Referenz: opensoar.competition.soaringspot (get_info_from_comment_lines,
get_waypoints, get_lat_long, get_sector_dimensions) - dieselbe Konvention, mit
der SoaringSpot-Downloads ihre Aufgabe in jeder Piloten-IGC-Datei mitliefern.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from zylinder_core import Zone, StartResult, format_latlon_crecord


@dataclass
class SoaringSpotWaypoint:
    name: str
    lat: float
    lon: float
    radius_m: float
    line_index_lcu: int
    line_index_oz: int


@dataclass
class SoaringSpotBlock:
    waypoints: List[SoaringSpotWaypoint]   # [0] = Start, [-1] = Ziel
    tz_offset_h: Optional[float]
    gate_open_local: Optional[str]         # aus 'NoStart=' auf der LSEEYOU-TSK-Zeile
    task_time: Optional[str]               # aus 'TaskTime=' (Mindestzeit bei AAT)
    tsk_line_index: Optional[int]


def _parse_lcu_coord(line: str) -> Tuple[float, float, str]:
    """line: 'LCU::C5145317N01757867E<Name>' -> (lat, lon, name)."""
    lat_deg = int(line[6:8])
    lat_min = int(line[8:13]) / 1000.0
    lat = lat_deg + lat_min / 60.0
    if line[13] == 'S':
        lat = -lat
    lon_deg = int(line[14:17])
    lon_min = int(line[17:22]) / 1000.0
    lon = lon_deg + lon_min / 60.0
    if line[22] == 'W':
        lon = -lon
    name = line[23:].strip()
    return lat, lon, name


def _parse_oz_radius(line: str) -> Optional[float]:
    m = re.search(r'R1=(\d+)m', line)
    return float(m.group(1)) if m else None


def find_soaringspot_block(lines: List[str]) -> Optional[SoaringSpotBlock]:
    lcu_c_idx = [i for i, l in enumerate(lines)
                 if l.startswith('LCU::C') and re.match(r'LCU::C\d', l)]
    oz_idx = [i for i, l in enumerate(lines) if l.startswith('LSEEYOU OZ=')]
    tsk_idx = next((i for i, l in enumerate(lines) if l.startswith('LSEEYOU TSK')), None)
    tz_idx = next((i for i, l in enumerate(lines) if l.startswith('LCU::HPTZNTIMEZONE:')), None)

    # opensoar-Konvention: lcu_c_idx[0]=Datum, [1]=Padding, [2:-1]=echte Punkte, [-1]=Padding
    if len(lcu_c_idx) < 4 or len(oz_idx) == 0:
        return None
    waypoint_lcu_idx = lcu_c_idx[2:-1]
    if len(waypoint_lcu_idx) != len(oz_idx):
        return None  # unerwartetes Format - lieber nichts automatisch anfassen

    waypoints = []
    for lcu_i, oz_i in zip(waypoint_lcu_idx, oz_idx):
        lat, lon, name = _parse_lcu_coord(lines[lcu_i])
        radius = _parse_oz_radius(lines[oz_i]) or 0.0
        waypoints.append(SoaringSpotWaypoint(name, lat, lon, radius, lcu_i, oz_i))

    tz_offset_h = None
    if tz_idx is not None:
        try:
            tz_offset_h = float(lines[tz_idx].split(':')[-1].strip())
        except ValueError:
            pass

    gate_open_local = None
    task_time = None
    if tsk_idx is not None:
        m = re.search(r'NoStart=(\d{1,2}:\d{2}:\d{2})', lines[tsk_idx])
        if m:
            gate_open_local = m.group(1)
        m2 = re.search(r'TaskTime=(\d{1,2}:\d{2}:\d{2})', lines[tsk_idx])
        if m2:
            task_time = m2.group(1)

    return SoaringSpotBlock(waypoints=waypoints, tz_offset_h=tz_offset_h,
                             gate_open_local=gate_open_local, task_time=task_time,
                             tsk_line_index=tsk_idx)


def zones_from_block(block: SoaringSpotBlock) -> List[Zone]:
    """Alle Punkte AUSSER dem Start, letzter Punkt = Ziel."""
    zones = []
    for i, wp in enumerate(block.waypoints[1:]):
        is_last = (i == len(block.waypoints) - 2)
        zones.append(Zone(name=wp.name, lat=wp.lat, lon=wp.lon,
                           radius_m=wp.radius_m, is_finish=is_last))
    return zones


def replace_start_in_block(lines: List[str], block: SoaringSpotBlock,
                            start: StartResult, mini_radius_m: float = 1.0) -> List[str]:
    """Ersetzt NUR die Start-Deklaration (erster Wegpunkt) im bestehenden
    SoaringSpot-Kommentarblock durch den gewerteten Startpunkt mit
    Mini-Zylinder - der Rest der Aufgabe bleibt exakt wie von SoaringSpot
    bekannt (Annex-A-konform: nur der Abflug wird korrigiert)."""
    new_lines = list(lines)
    start_wp = block.waypoints[0]

    old_lcu = new_lines[start_wp.line_index_lcu]
    label = old_lcu[23:]  # Original-Label unveraendert uebernehmen
    new_lcu = old_lcu[:6] + format_latlon_crecord(start.lat, start.lon) + label
    new_lines[start_wp.line_index_lcu] = new_lcu

    old_oz = new_lines[start_wp.line_index_oz]
    new_oz = re.sub(r'R1=\d+m', f'R1={mini_radius_m:g}m', old_oz)
    new_lines[start_wp.line_index_oz] = new_oz

    return new_lines
