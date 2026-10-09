# Cylinder Start Evaluation Tool

*(Deutsche Version: [README_DE.md](README_DE.md))*

Evaluates the Annex A "Cylinder Start" (SC3A 7.4.4, edition 2025) for one
contest day from the raw IGC files submitted by the pilots (before they are
scored by SeeYou Competition) and produces:

- **Copies** of the IGC files (originals are never touched) with the task
  written into them are saved into the target folder **which should be the
  folder SeeYou Competition searches IGC files in**: task points plus the
  corrected start point (a 1 m mini cylinder exactly at the credited PEV) in
  LSEEYOU format, for import into SeeYou Competition via "Use task from IGC file".
  If a file already contains a SoaringSpot task block (e.g. on a second run),
  only the start line in it is replaced instead of appending everything again.
- **One common report** (`Cylinder_Start_Report.xlsx`, German UI language:
  `Zylinderabflug_Report.xlsx`) with start method, validity, groundspeed,
  loss of height and all remarks per pilot.

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
   files before scoring** and also **not** for files that already have an altered task with personal start point(the block is created by the SoaringSpot upload,
   usually AFTER scoring).
3. **CUP file + manual entry**: for the case that SoaringSpot is not
   reachable as expected or you want to score with another tool than SeeYou. Add turn points one by one (take coordinates from a
   CUP file or type them), plus radius, optionally sector (inner
   radius/opening angle) and maximum altitude, and enter the daily parameters
   by hand.

All three ways lead to the same form - whatever the web page does not provide
(coordinates, gate opening, max. groundspeed/loss of height without notes)
can be added or corrected by hand afterwards.

## Use without a terminal - three options

**Least effort for permanent use: standalone .exe (set up once)**
1. Put all files into one folder.
2. Double-click `build_exe.bat` (briefly opens a window that installs and
   builds everything automatically - type nothing, just wait).
3. Afterwards `dist\Zylinderabflug_Tool.exe` is a ready, standalone file.
   Copy it to the desktop (or create a shortcut) - from now on a double-click
   is enough, **no Python and no terminal needed**, also not on another
   Windows computer.

**Alternative without a preparation step, if Python is already installed:**
1. Double-click `install.bat` (once; installs `openpyxl`, `requests` and
   `beautifulsoup4`).
2. Afterwards a double-click on `Zylinderabflug_Tool.pyw` starts the user
   interface directly, without a console window.

**Only if Python is missing completely:** install it from python.org and make
sure to tick "Add python.exe to PATH" - afterwards one of the two ways above
works.

All `.py` files (including `i18n.py` and `en_dict.py`) must be in the same
folder.

## Usage

1. Choose the **source folder** (raw IGC files of the pilots for the contest
   day) and the **target folder**.
2. Load the task (see above, one of the three ways) and check/complete the
   fields. The gate opening field is highlighted yellow/bold as long as it
   still has its default value (03:00:00).
3. Check/adjust the **daily parameters** (max. groundspeed, max. loss of
   height, minimum PEV interval, etc.) - Annex A default values are preset
   and can be overwritten directly for national contests with different rules.
4. Optionally enable **baro calibration** and enter the field elevation.
5. With "Save/Load parameters" a data set can be saved as JSON and reused on
   the next contest day.
6. Click "Start evaluation".
7. Read the created copies into SeeYou Competition with "Use task from IGC
   file"; enter the penalties from the report manually in SeeYou.

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
