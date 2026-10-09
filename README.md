# Cylinder Start Evaluation Tool

*(Deutsche Version: [README_DE.md](README_DE.md))*

Evaluates the Annex A "Cylinder Start" (SC3A 7.4.4, edition 2025) for one
contest day from the raw IGC files submitted by the pilots (before they are
scored by SeeYou Competition) and produces:

- **Copies** of the IGC files (originals are never touched) with the task
  written into them. They are saved into the target folder, **which should be
  the folder SeeYou Competition searches IGC files in**. Each copy contains the
  task points plus the corrected start point (a 1 m mini cylinder exactly at
  the credited PEV) in LSEEYOU format, for import into SeeYou Competition via
  "Use task from IGC file". If a file already contains a SoaringSpot task block
  (e.g. on a second run), only the start line in it is replaced instead of
  appending everything again.
- **One common report** (`Cylinder_Start_Report.xlsx`, German UI language:
  `Zylinderabflug_Report.xlsx`) with start method, start/finish altitude (baro),
  groundspeed, loss of height, penalty points and all remarks per pilot.

Line and sector start days are **not** handled by this tool (SeeYou does that
itself) - only use it for days with a cylinder start.

## Quick start: scoring one contest day

**Once, before the first use**
1. Get the program (see [Installation](#installation)): the easiest way is the
   ready-made `Zylinderabflug_Tool.exe` from the **Releases** page of this
   repository - no Python, no terminal.
2. Have the **CUP file** of the competition (turn points with coordinates)
   ready. The tool asks for it once and remembers it.

**Every contest day**
1. **Collect the raw IGC files** of the day (one class only) in one folder -
   the *source folder*. For a real contest day these are the files as the
   pilots delivered them. To **test with an old, already scored day**, you can
   also use IGC files downloaded from SoaringSpot: they already contain a task
   block, which the tool updates (only the start line is replaced). Do not use
   copies that this tool has already written (`..._cyl.igc`) as input.
2. **Start the program** (double-click on the `.exe`).
3. **Choose the folders:**
   - *Source folder* = the folder from step 1.
   - *Target folder* = the folder where SeeYou Competition looks for the IGC
     files of this day. Use a **different folder** than the source folder, so
     that the raw files and the copies (named `<original name>_cyl.igc`) are
     not mixed up.
4. **Load the task** - click "Load task from SoaringSpot web page...", paste
   the link of the day's *task* page (a results link is converted
   automatically) and select the CUP file when asked. The contest day is taken
   from the link.
5. **Check the fields** - the tool cannot read everything from the web page:
   - **Gate opening (local time)**: yellow/bold means it still has the default
     value (03:00:00) - enter the real time from the task sheet. If the page
     has "Task notes", they are shown in a window; copy gate opening, maximum
     groundspeed and maximum loss of height from there.
   - **Max. groundspeed / max. loss of height / time zone**: must match the
     task sheet. The Annex A values are preset; change them for national rules.
   - Optionally: **calibrate baro** to the field elevation (see below).
6. Click **"Start evaluation"**. The log shows the progress; when it is done,
   the target folder contains the IGC copies and the Excel report.
7. **Read the report** (`Cylinder_Start_Report.xlsx`) before going on. Every
   pilot has one row, coloured by the most severe remark:
   **red** = penalty or invalid, **yellow** = please check manually,
   **grey** = information only (e.g. normal outlanding). Look at all red and
   yellow rows first.
8. **Score in SeeYou Competition:** set the day's task with
   "Use task from IGC file" (choose one of the copies in the target folder)
   and load the flights from the target folder. The start of every pilot is
   now the 1 m cylinder at his credited start fix, so SeeYou calculates the
   start time and altitude correctly. (Menu names can differ slightly between
   SeeYou versions.)
9. **Enter the penalties manually in SeeYou**: the report contains the time
   penalty (+5 min for an exit start or a short PEV interval) and the points
   for excess groundspeed and loss of height per pilot.

The next day: start the program again - folders, parameters and the CUP file
are remembered; only today's date and the gate opening are reset.

## Where the task comes from - three ways

1. **SoaringSpot web page** (main way): button "Load task from SoaringSpot web
   page...", enter the link of the **task** page, e.g.
   `https://www.soaringspot.com/en_gb/<competition>/tasks/<class>/task-N-on-<date>`.
   If you paste a *results* link by mistake, the tool converts it to the task
   page automatically; the contest day is taken from the link. The page
   provides the order of the task points, cylinder/sector radii and the AAT
   minimum time - but **no coordinates**. Therefore the tool asks for a
   **CUP file** from which the coordinates are matched by name (the CUP file
   is stored permanently; you are asked for a new one only when names of a
   task no longer match). Gate opening, max. groundspeed and max. loss of
   height are only available (if the organiser entered them) in the free-text
   "Task notes" of the page - these are shown in a window after loading so
   you can copy them into the fields.
2. **From an already processed IGC file**: button "Load task from IGC file
   (SoaringSpot)...". Works only if the chosen file already contains a
   SoaringSpot task block - which is **not** the case for the **raw pilot
   files before scoring** and also **not** for files that already have an
   altered task with a personal start point (the SoaringSpot block is created
   by the SoaringSpot upload, usually AFTER scoring).
3. **CUP file + manual entry**: for the case that SoaringSpot is not
   reachable as expected or you want to score with another tool than SeeYou.
   Add turn points one by one (take coordinates from a CUP file or type
   them), plus radius, optionally sector (inner radius/opening angle) and
   maximum altitude, and enter the daily parameters by hand.

All three ways lead to the same form - whatever the web page does not provide
(coordinates, gate opening, max. groundspeed/loss of height without notes)
can be added or corrected by hand afterwards.

## Installation

Three options, none of them needs a terminal:

**1. Download the ready-made .exe (easiest)**
Open the **Releases** page of this repository and download
`Zylinderabflug_Tool.exe`. Copy it to the desktop - a double-click starts the
program. Windows may show a "SmartScreen" warning because the file is not
digitally signed: click "More info" -> "Run anyway".

**2. Build the .exe yourself (Windows, Python installed)**
1. Put all files into one folder.
2. Double-click `build_exe.bat` (briefly opens a window that installs and
   builds everything automatically - type nothing, just wait).
3. Afterwards `dist\Zylinderabflug_Tool.exe` is a ready, standalone file.
   Copy it to the desktop (or create a shortcut) - from now on a double-click
   is enough, **no Python and no terminal needed**, also not on another
   Windows computer.

**3. Without building, if Python is already installed**
1. Double-click `install.bat` (once; installs `openpyxl`, `requests` and
   `beautifulsoup4`).
2. Afterwards a double-click on `Zylinderabflug_Tool.pyw` starts the user
   interface directly, without a console window.

**Only if Python is missing completely:** install it from python.org and make
sure to tick "Add python.exe to PATH" - afterwards option 2 or 3 works.

All `.py` files (including `i18n.py` and `en_dict.py`) must be in the same
folder when running from source (options 2 and 3).

## Settings in detail

- **Daily parameters** (max. groundspeed, max. loss of height, minimum PEV
  interval, etc.): Annex A default values are preset and can be overwritten
  directly for national contests with different rules.
- **Baro calibration** (optional): tick "Calibrate baro to reference
  elevation" and enter the field elevation (m MSL). The stationary phase at
  the start of the file is then set to this elevation. If a file starts in the
  air it stays uncalibrated (remark in the report). The loss of height does
  not change through the calibration, only the reported start/finish
  altitudes. Altitudes in the report are always barometric.
- **Save/Load parameters** saves a complete data set as JSON, e.g. to reuse
  the task of a previous day.
- **If the window is larger than your screen**: use the scroll bar on the right
  or the mouse wheel. The buttons "Load/Save parameters" and "Start
  evaluation" at the bottom are always visible.

## Language

German / English can be selected at the top right of the window. The change
takes effect immediately and is remembered (default: system language). The
Excel report is written in the selected language.

## Remembered settings

On closing, the tool stores all values (speeds, loss of height, field
elevation + calibration checkbox, folders, start cylinder, task points, ...)
and, for each selection dialog, the last folder used - also after a restart.
The contest day is not remembered (at program start: today's date) and
neither is the gate opening (default 03:00:00). The CUP file is stored in the
folder `.zylinderabflug_tool` in the user directory.

## Report colours

Each pilot row has the colour of its most severe remark: **red** = penalty or
invalid, **yellow** = check, **grey** = note only (e.g. normal outlanding,
ignored irrelevant PEV). Penalty points are whole numbers (rounded half up).

## Troubleshooting

| Problem | What to do |
|---|---|
| "Task page cannot be read" / no turn points found | Check that the link points to a *task* page of one contest day (`.../task-N-on-<date>`), or enter the task manually (way 3). |
| The tool asks for a CUP file again | Some turn point names of the task no longer match the stored CUP file - choose the CUP file of this competition. |
| No `.igc` files found | The source folder must directly contain the files (subfolders are not searched). |
| A pilot has "no valid start" | See the remark in the report: no PEV in the cylinder and no exit after gate opening, or start speed more than 50 km/h above the limit. |
| Gate opening field is yellow | It still has the default 03:00:00 - enter the real value. |

## Open points / known limits of this version

- For the internal task-order check (when was which point reached, for loss
  of height) only the outer radius of each zone is checked as a full circle,
  no exact sector angle limits - irrelevant for the actual scoring, SeeYou
  does that with the real sector values.
- The core logic was tested against four real contest-day IGC files (normal
  case, PEV outside the cylinder, speed exceedance, loss-of-height borderline
  case) - for productive use as contest management please still spot-check
  against known SeeYou results before relying on it.
- Line and sector start days are not touched by the tool (SeeYou already
  handles them) - for such days simply use the original IGC files directly in
  SeeYou and do not run them through this tool.
- Loss-of-height penalty: 1 point per 3 m is a setting (value given by the
  client; the annex only says "proportional"). Capping (achieved speed points
  / 15 % of the best score) is done by SeeYou.
- The 10-minute PEV interval penalty on repetition on another contest day
  cannot be detected by the tool - the report only contains the hint "check
  previous cases".
