# Technical handover: Cylinder start evaluation (Annex A 7.4.4)

*(Deutsche Version: [Cylinder-Start-Auswertung_Technische-Uebergabe_DE.md](Cylinder-Start-Auswertung_Technische-Uebergabe_DE.md))*

Purpose of this document: all rules, formulas and algorithm decisions needed
to evaluate the Annex A "Cylinder Start", so that it can be rebuilt in PySoar.
Source: FAI Sporting Code Section 3, Annex A, edition 2025, section 7.4.4
("Cylinder Start Procedures"), plus the general sections 7.4.2 ("Common Start
Procedures") and 5.4.1 (altitude determination). All rule texts below are
paraphrased, not quoted verbatim - in case of doubt check against the
original source, in particular if an edition newer than 2025 applies.

A working reference implementation (Python, standard library + pure WGS84
Vincenty, no dependency on opensoar needed) already exists as a basis:
`zylinder_core.py` (core logic), `soaringspot_block.py` /
`soaringspot_web.py` (task import). This document describes *what* happens
there and *why*, so that it can be ported 1:1 to PySoar.

## 1. Geodetic model

Annex A explicitly defines distances, radii and lines as **geodesics on the
WGS84 ellipsoid** - not as a spherical approximation (haversine) and not as
the simplified "FAI sphere" used elsewhere for pure distance scoring. For
cylinder radius checks (10+ km) and the start groundspeed measurement this
makes a noticeable difference (several metres up to low double-digit metres),
especially at the cylinder boundary.

The **Vincenty inverse formula** is used (iterative, WGS84 semi-axis
a = 6378137 m, flattening f = 1/298.257223563). A pure Python implementation
without dependencies is available in `zylinder_core.vincenty_distance_m()` -
it can be taken over 1:1 unless PySoar already has an equivalent function
(e.g. via `geographiclib`/`pyproj`, if acceptable as a dependency - gives
practically identical results).

Performance note: the reference implementation uses haversine only as a
pre-filter (outside a ±1 % band around the radius the result is certain) and
runs Vincenty only inside that band.

## 2. Procedure for determining the start (Annex A 7.4.4)

Inputs: cylinder centre (lat/lon), cylinder radius (task sheet, Annex A
minimum 10 km), gate opening time (local time, task sheet), time zone offset,
the list of PEV events (E records, code `PEV`) from the IGC file, and all
B-record fixes.

**Step 1 - discard PEVs before gate opening.** Only PEVs with a timestamp ≥
gate opening time (converted to UTC) are considered. A PEV before gate
opening does not count as a start event.

**Step 2 - 30-second cluster rule.** Several PEVs within 30 seconds are
treated as **one** PEV (time of the first of the group). The order matters:
filter by cylinder membership **first** (step 3), cluster **afterwards** - a
PEV outside the cylinder does not start a 30 s sequence; the sequence starts
with the first PEV inside the cylinder.
This rule applies to the cylinder start just as to the line-start PEV option
PySoar already uses - **do not confuse it with the minimum interval** (see
step 4): the 30-second rule is merely debouncing of multiple clicks, not a
validity criterion.

**Step 3 - check cylinder membership of each PEV** (geodesic distance
PEV fix ↔ cylinder centre, WGS84):
- distance ≤ cylinder radius → PEV valid, counts as a possible start
- distance > cylinder radius → PEV is **ignored**. The message states the
  distance to the **edge** (distance − radius), not to the centre.
- Optional (parameter `tolerance_m`, default **0 = off**): a PEV up to x m
  outside stays valid with a 50-point penalty. The 0.5 km / 50 points rule
  (8.7) refers according to the annex text to "no fix inside the cylinder"
  and is **not** implemented here as a PEV tolerance - only meant for
  national special rules.

**Step 4 - minimum PEV interval (only for the CREDITED PEV).** The credited
PEV is compared with the valid PEV before it. If less than **10 minutes** lie
in between, the start stays valid but there is a **+5 minutes time
penalty**. The 10 minutes apply only on repetition on a further contest day -
the tool cannot know that, therefore the report contains the hint "check
previous cases". Violations between other, non-credited PEV pairs have no
effect (grey in the report only).

**Step 5 - determine the start point.** Among the valid PEVs (after gate
opening, clustered) the **latest one with the greatest task progress** is
chosen (progress = number of zones reached in order from this start).
Normal case: that is the last PEV. If the last PEV is worse than an earlier
one (e.g. pressed only after the finish), a "please check" note is created.
Credited start time/point/altitude = timestamp/position/altitude of the
corresponding B-record fix (the mini cylinder needs a real fix, no
interpolation).

**Step 6 - fallback without a valid PEV.** If no PEV lies inside the
cylinder, the start is an **exit from the cylinder** after gate opening (last
fix inside → first fix outside) with +5 minutes time penalty. There are often
several exits (edge flying, re-entry, exit after the finish!). Therefore
**not** blindly the last exit is chosen but the latest exit with the greatest
task progress - otherwise, for example, a finish located at the cylinder edge
(exit after the finish crossing) wrongly becomes the start.

If no exit from the cylinder happens after gate opening: no valid start.

## 3. Groundspeed at start

Own formula, different from the line start (7.4.4.1): the straight-line
distance (geodesic, WGS84) between the **credited start fix** and the fix
**nearest to 8 seconds before** it (not averaged over before+after as with the
line start), divided by the actual elapsed time between the two fixes.
Result in km/h.

Penalty scale (8.7): exceeding the maximum start speed set on the task sheet
→ **2 points per km/h** of excess, up to 50 km/h above the limit. Above that:
**no valid start**. All penalty points are **rounded half up to whole
numbers**.

## 4. Loss of height (start → finish)

Defined as **start altitude minus finish altitude** (7.4.4.1/7.4.4.7), both
MSL. **Important:** according to Annex A 5.4.1 MSL altitude is derived from
the **barometric** altitude difference to the start point plus field
elevation - **not** from raw GPS altitude (in the test data: "1 m over the
limit" baro vs. "27 m" GPS). Always use `baro_alt` of the B records. The
**finish altitude is interpolated between the fix before and the fix after
entering the finish cylinder** (intersection by bisection against the
geodesic radius, time and pressure altitude linear).

Baro calibration (optional): the stationary phase at the start of the file
(aircraft not moving: < 100 m travelled, ±10 m altitude) is set to the field
elevation. Loss of height does not change (the offset cancels), only the
reported start/finish altitudes.

If loss of height exceeds the maximum, there is a penalty proportional to the
excess: in the tool **1 point per 3 m** (parameter `loh_m_per_point`, value
given by the client - the annex excerpt only says "proportional"), capped to
the achieved speed points or 15 % of the day's best score (7.4.4.7). Capping
is done by SeeYou; the report states the uncapped number of points.

## 5. Determining the finish arrival - a pitfall

For loss of height and the report it must be known **when** the finish was
reached. A plain "is the pilot inside the finish radius" check over the whole
flight is **wrong** and gives false positives: with cylinder-start tactics
("start anywhere") the credited start point is often geographically already
inside the finish radius (close to the airfield) - a naive distance check
then immediately reports "finish reached" although not a single turn
point/AAT area has been flown yet.

Correct: **order-dependent check.** Only when all turn/AAT zones have been
confirmed once each by a fix in the declared order (a simple distance test is
sufficient, Annex A 7.9.1 "Completed Task"), the first subsequent entry into
the finish zone counts as finish arrival. Simplification in the reference
implementation: only the outer radius of each zone is checked as a full
circle, no exact sector angle limits - accurate enough for time/altitude
determination; the actual scoring is done by SeeYou with the real sector
values anyway.

## 6. Distinction from the existing line-start PEV logic in PySoar

PySoar so far evaluates the PEV option of the **line start** (7.4.3), with the
rule "a PEV is invalid if it is less than 30 seconds after the last valid
PEV". That is a **separate rule set** with its own mechanics (PEV wait time,
start window) and has **nothing to do with the cylinder-start minimum
interval of 10 minutes**. For an extension to cylinder start a separate code
path is recommended instead of trying to squeeze both PEV mechanisms into one
function - validity conditions, time windows and penalty mechanics differ in
several places (see sections 2-4).

## 7. Where the task parameters come from

Two usable sources, both already implemented and tested against real data:

- **SoaringSpot task page** (`.../tasks/<class>/task-N-on-<date>`, NOT the
  `results` page - a results link can be converted by replacing `/results/`
  with `/tasks/` and cutting everything after `task-N-on-<date>`): HTML table
  with turn point names, distance, direction and observation zone
  (radius/sector angle as text, e.g. `Cylinder R=10.00 km` or
  `Rmin=0.50 km, Rmax=10.00 km, Angle=90.0°`). Provides **no coordinates** -
  they must additionally be matched from a CUP file by name (normalisation
  needed: upper/lower case, spaces/underscores, see
  `soaringspot_web.match_names_to_cup()`). Free-text "Task notes" (if
  maintained by the organiser) often contain gate opening, max. groundspeed,
  max. loss of height - but not structured, only as running text for manual
  transfer.
- **SoaringSpot IGC comment block**: every IGC file downloaded via SoaringSpot
  already contains the task as `LCU::C...`/`LSEEYOU OZ=...`/`LSEEYOU TSK...`
  comment lines (see `soaringspot_block.py`, format corresponds to
  `opensoar.competition.soaringspot`). **Note:** this only works for files
  already processed via SoaringSpot - the raw files collected directly from
  the pilots (before the actual scoring) do not have this block yet, because
  it is created by the SoaringSpot upload.

## 8. IGC validity when writing back

If the task (corrected start point as a mini cylinder, 1 m radius around the
credited start point) is written into the IGC file, this happens exclusively
via **L records** (`LCU::`/`LSEEYOU`, lines starting with "L"). This is a
deliberate choice: in all tested files the L records are located *after* the
G record (digital signature) and are also appended afterwards by SoaringSpot
itself without breaking the signature - L records are intended in the IGC
format for exactly such later annotations. B records, the G record itself or
other records are never changed. Still: before productive use check once
against a real IGC validator (e.g. the CIVL Open Validation Server), unless
PySoar does that anyway.

## 9. Open points / known limits

- The live network request of the SoaringSpot task page was tested against two
  real, saved page contents, not against a real live request from the target
  environment (network restriction in the development environment).
- The observation zone text patterns (`Cylinder R=...`,
  `Rmin=.../Rmax=.../Angle=...`, `Line ... (Radius ...)`) were derived only
  from the two pages seen - they may differ for other SoaringSpot
  versions/languages; adapt the regex in
  `soaringspot_web._parse_observation_zone()` accordingly.
- The reference implementation assumes racing-task and AAT zones with A1=180
  (full circle); real narrow sectors are only approximated as a full circle
  for the time/order check (see section 5).
- The loss-of-height rate (1 point per 3 m) is not part of the annex excerpt
  read; it was provided by the client and is configurable.
- The multi-day escalation of the PEV interval penalty (5 → 10 minutes) cannot
  be derived from a single day's files.
- User interface and Excel report exist in German and English (`i18n.py`,
  `en_dict.py`); the German text is also the translation key.
