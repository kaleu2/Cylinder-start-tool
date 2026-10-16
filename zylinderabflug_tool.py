#!/usr/bin/env python3
"""
Zylinderabflug-Auswertetool
============================
Wertet den Annex-A "Cylinder Start" (SC3A 7.4.4, Edition 2025) fuer alle
IGC-Dateien eines Wertungstages aus, schreibt Kopien mit angehaengter
Mini-Zylinder-Aufgabendeklaration (fuer SeeYou Competition "Aufgabe aus
IGC-Datei nutzen") und erzeugt einen Gesamtreport (xlsx).

Start: python zylinderabflug_tool.py   (keine Kommandozeile noetig, GUI oeffnet sich)

Abhaengigkeiten: nur Python-Standardbibliothek + openpyxl.
"""

import copy
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import asdict

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from zylinder_core import (
    TaskParams, Zone, parse_igc, evaluate_pilot, write_output_igc, seconds_to_hms, method_label,
    list_start_options, read_igc_header,
)
from i18n import tr, set_lang, get_lang, LANGUAGES
from zylinder_report import write_report_xlsx
from cup_import import parse_cup_file
from soaringspot_block import find_soaringspot_block, zones_from_block
from soaringspot_web import (
    WEB_IMPORT_AVAILABLE, fetch_task_page_html, parse_task_page, match_names_to_cup, normalize_task_url,
)



# Dauerhaft gespeicherte Wendepunktdatei (CUP) + Einstellungen
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".zylinderabflug_tool")
STORED_CUP = os.path.join(CONFIG_DIR, "stored.cup")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")


def _default_language():
    """Systemsprache: Deutsch -> 'de', sonst 'en'; bei Unklarheit 'de'."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "de" if (lang_id & 0xFF) == 0x07 else "en"
    except Exception:
        pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        val = os.environ.get(var, "")
        if val:
            return "de" if val.lower().startswith("de") else "en"
    try:
        import locale
        loc = locale.getlocale()[0]
        if loc:
            return "de" if loc.lower().startswith("de") else "en"
    except Exception:
        pass
    return "de"


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class UrlDialog(tk.Toplevel):
    """Einfache Abfrage der SoaringSpot-Task-Seiten-URL."""

    def __init__(self, master):
        super().__init__(master)
        self.title(tr("SoaringSpot-Aufgabenseite"))
        self.result = None
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ttk.Label(self, text=tr("Link zur SoaringSpot-Seite des Tages (Task- oder Ergebnis-Seite):")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 2))
        self.entry = ttk.Entry(self, width=70)
        self.entry.grid(row=1, column=0, columnspan=2, padx=8, pady=4)
        self.entry.focus_set()

        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, columnspan=2, pady=8)
        ttk.Button(btns, text=tr("Laden"), command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text=tr("Abbrechen"), command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda e: self._ok())

    def _ok(self):
        url = self.entry.get().strip()
        if url:
            self.result = url
        self.destroy()


class NotesDialog(tk.Toplevel):
    """Zeigt die freien 'Task notes' zum manuellen Übertragen (Höhen, Frequenzen, ...)."""

    def __init__(self, master, notes_text):
        super().__init__(master)
        self.title(tr("Task notes (bitte relevante Werte manuell übernehmen)"))
        self.geometry("520x320")
        self.transient(master)

        txt = tk.Text(self, wrap="word")
        txt.insert("1.0", notes_text or tr("(keine Notizen auf dieser Seite hinterlegt)"))
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(self, text=tr("Schließen"), command=self.destroy).pack(pady=(0, 8))


class ZoneDialog(tk.Toplevel):
    """Formular zum Hinzufuegen/Bearbeiten eines Streckenpunkts."""

    def __init__(self, master, zone=None, prefill=None):
        super().__init__(master)
        self.title(tr("Streckenpunkt"))
        self.result = None
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        vals = {"name": "", "lat": "", "lon": "", "radius": "10000",
                "r_min": "0", "a_max": "180", "a_min": "0", "max_alt": "0"}
        if zone:
            vals = {"name": zone.name, "lat": f"{zone.lat:.6f}", "lon": f"{zone.lon:.6f}",
                    "radius": f"{zone.radius_m:.0f}", "r_min": f"{zone.r_min_m:.0f}",
                    "a_max": f"{zone.angle_max_deg:g}", "a_min": f"{zone.angle_min_deg:g}",
                    "max_alt": f"{zone.max_alt_m:g}", "finish": zone.is_finish}
        if prefill:
            vals["name"] = prefill[0]
            vals["lat"] = f"{prefill[1]:.6f}"
            vals["lon"] = f"{prefill[2]:.6f}"

        basic = ttk.LabelFrame(self, text=tr("Grunddaten"))
        basic.grid(row=0, column=0, padx=6, pady=4, sticky="ew")
        labels = [tr("Name"), tr("Breite (Dezimalgrad)"), tr("Länge (Dezimalgrad)"), tr("Außenradius R1 (m)")]
        keys = ["name", "lat", "lon", "radius"]
        self.entries = {}
        for i, (lab, key) in enumerate(zip(labels, keys)):
            ttk.Label(basic, text=lab).grid(row=i, column=0, sticky="w", padx=6, pady=3)
            e = ttk.Entry(basic, width=24)
            e.insert(0, vals[key])
            e.grid(row=i, column=1, padx=6, pady=3)
            self.entries[key] = e

        adv = ttk.LabelFrame(self, text=tr("Sektor/Höhe (optional - leer/0 = Vollkreis, keine Höhenbegrenzung)"))
        adv.grid(row=1, column=0, padx=6, pady=4, sticky="ew")
        adv_labels = [
            (tr("Innenradius R2 (m):"), "r_min"),
            (tr("Öffnungswinkel außen A1 (°, 180=Vollkreis):"), "a_max"),
            (tr("Öffnungswinkel innen A2 (°):"), "a_min"),
            (tr("Max. Höhe MaxAlt (m, 0=unbegrenzt):"), "max_alt"),
        ]
        for i, (lab, key) in enumerate(adv_labels):
            ttk.Label(adv, text=lab).grid(row=i, column=0, sticky="w", padx=6, pady=3)
            e = ttk.Entry(adv, width=10)
            e.insert(0, vals[key])
            e.grid(row=i, column=1, padx=6, pady=3)
            self.entries[key] = e

        self.finish_var = tk.BooleanVar(value=vals.get("finish", False))
        ttk.Checkbutton(self, text=tr("ist Ziel (letzter Punkt)"), variable=self.finish_var).grid(
            row=2, column=0, sticky="w", padx=6, pady=4)

        btns = ttk.Frame(self)
        btns.grid(row=3, column=0, pady=8)
        ttk.Button(btns, text=tr("Übernehmen"), command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text=tr("Abbrechen"), command=self.destroy).pack(side="left", padx=4)

    def _ok(self):
        try:
            name = self.entries["name"].get().strip() or tr("Punkt")
            lat = float(self.entries["lat"].get().replace(",", "."))
            lon = float(self.entries["lon"].get().replace(",", "."))
            radius = float(self.entries["radius"].get().replace(",", "."))
            r_min = float(self.entries["r_min"].get().replace(",", ".") or "0")
            a_max = float(self.entries["a_max"].get().replace(",", ".") or "180")
            a_min = float(self.entries["a_min"].get().replace(",", ".") or "0")
            max_alt = float(self.entries["max_alt"].get().replace(",", ".") or "0")
        except ValueError:
            messagebox.showerror(tr("Fehler"), tr("Bitte alle Zahlenfelder korrekt ausfüllen."))
            return
        self.result = Zone(name=name, lat=lat, lon=lon, radius_m=radius,
                            is_finish=self.finish_var.get(), r_min_m=r_min,
                            angle_max_deg=a_max, angle_min_deg=a_min, max_alt_m=max_alt)
        self.destroy()


class CupPickDialog(tk.Toplevel):
    """Liste der Punkte aus einer CUP-Datei zum Auswaehlen."""

    def __init__(self, master, points):
        super().__init__(master)
        self.title(tr("Punkt aus CUP-Datei wählen"))
        self.result = None
        self.transient(master)
        self.grab_set()
        self.geometry("420x400")

        self.listbox = tk.Listbox(self, width=50)
        for name, lat, lon in points:
            self.listbox.insert("end", f"{name}   ({lat:.5f}, {lon:.5f})")
        self.listbox.pack(fill="both", expand=True, padx=6, pady=6)
        self.points = points

        btns = ttk.Frame(self)
        btns.pack(pady=6)
        ttk.Button(btns, text=tr("Übernehmen"), command=self._ok).pack(side="left", padx=4)
        ttk.Button(btns, text=tr("Abbrechen"), command=self.destroy).pack(side="left", padx=4)

    def _ok(self):
        sel = self.listbox.curselection()
        if sel:
            self.result = self.points[sel[0]]
        self.destroy()


class ChoiceDialog(tk.Toplevel):
    """Modale Abfrage mit frei waehlbaren Knoepfen. Ergebnis: Schluessel des gedrueckten
    Knopfes (bzw. close_key beim Schliessen ueber das Fenster-X)."""

    def __init__(self, master, title, text, buttons, close_key):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result = close_key
        self._close_key = close_key
        ttk.Label(self, text=text, wraplength=520, justify="left").pack(padx=14, pady=(14, 8))
        row = ttk.Frame(self)
        row.pack(padx=10, pady=(4, 12))
        for key, label in buttons:
            ttk.Button(row, text=label, command=lambda k=key: self._pick(k)).pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", lambda: self._pick(close_key))
        self.update_idletasks()
        x = master.winfo_rootx() + max((master.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = master.winfo_rooty() + max((master.winfo_height() - self.winfo_reqheight()) // 3, 0)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_set()

    def _pick(self, key):
        self.result = key
        self.destroy()


def ask_choice(master, title, text, buttons, close_key):
    dlg = ChoiceDialog(master, title, text, buttons, close_key)
    master.wait_window(dlg)
    return dlg.result


class PromptDialog(tk.Toplevel):
    """Kleine Eingabemaske mit mehreren Feldern (Text oder Auswahl mit Eingabe)."""

    def __init__(self, master, title, text, fields):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result = None
        ttk.Label(self, text=text, wraplength=460, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))
        self._widgets = []
        for i, (label, default, values) in enumerate(fields, start=1):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=10, pady=3)
            if values:
                w = ttk.Combobox(self, values=list(values), width=28)
            else:
                w = ttk.Entry(self, width=30)
            w.insert(0, default)
            w.grid(row=i, column=1, padx=10, pady=3)
            self._widgets.append(w)
        row = ttk.Frame(self)
        row.grid(row=len(fields) + 1, column=0, columnspan=2, pady=10)
        ttk.Button(row, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(row, text=tr("Abbrechen"), command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + max((master.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = master.winfo_rooty() + max((master.winfo_height() - self.winfo_reqheight()) // 3, 0)
        self.geometry(f"+{x}+{y}")
        self._widgets[0].focus_set()
        self.grab_set()

    def _ok(self):
        self.result = [w.get() for w in self._widgets]
        self.destroy()


def ask_fields(master, title, text, fields):
    dlg = PromptDialog(master, title, text, fields)
    master.wait_window(dlg)
    return dlg.result


class StartChoiceDialog(tk.Toplevel):
    """Manuelle Auswahl eines anderen Starts je Pilot (nach der Auswertung).
    Zeigt alle PEVs im Startzylinder plus den Ausflug nach dem letzten gueltigen PEV,
    jeweils mit Hinweistext, warum der Start eigentlich nicht zaehlt."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(self._title())
        self.transient(app)
        w = min(960, app.winfo_screenwidth() - 40)
        h = min(660, app.winfo_screenheight() - 90)
        self.geometry(f"{w}x{h}")
        self.minsize(min(700, w), min(480, h))
        self._opt_cache = {}          # Dateiname -> Liste StartOption (Cache)
        self._cur_file = None
        self._opt_rows = {}         # tree-iid -> StartOption

        ttk.Label(self, wraplength=w - 30, justify="left", text=tr(
            "Pilot wählen, dann den gewünschten Start markieren und \"Diesen Start übernehmen\" "
            "klicken. Die IGC-Kopie und der Report werden sofort neu geschrieben. Ein manuell "
            "gewählter Start wird im Report gelb markiert.")).pack(fill="x", padx=8, pady=(8, 4))

        # --- Piloten ---
        frm_p = ttk.LabelFrame(self, text=tr("Piloten"))
        frm_p.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("file", "pilot", "start", "method", "state")
        self.tree_p = ttk.Treeview(frm_p, columns=cols, show="headings", height=7, selectmode="browse")
        for c, head, wd in (("file", tr("Datei"), 170), ("pilot", tr("Pilot"), 170),
                            ("start", tr("Start (UTC)"), 90), ("method", tr("Methode"), 90),
                            ("state", tr("Wertung"), 150)):
            self.tree_p.heading(c, text=head)
            self.tree_p.column(c, width=wd, anchor="w")
        sb = ttk.Scrollbar(frm_p, orient="vertical", command=self.tree_p.yview)
        self.tree_p.configure(yscrollcommand=sb.set)
        self.tree_p.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="left", fill="y", pady=6, padx=(0, 6))
        self.tree_p.bind("<<TreeviewSelect>>", self._on_pilot)

        # --- Optionen ---
        frm_o = ttk.LabelFrame(self, text=tr("Mögliche Starts des gewählten Piloten"))
        frm_o.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("time", "kind", "edge", "prog", "speed", "pen", "state")
        self.tree_o = ttk.Treeview(frm_o, columns=cols, show="headings", height=6, selectmode="browse")
        for c, head, wd in (("time", tr("Zeit (UTC)"), 90), ("kind", tr("Art"), 80),
                            ("edge", tr("Abstand zum Rand (m)"), 140), ("prog", tr("Aufgabenpunkte"), 110),
                            ("speed", tr("Groundspeed (km/h)"), 130), ("pen", tr("Strafzeit (min)"), 130),
                            ("state", tr("Wertung"), 160)):
            self.tree_o.heading(c, text=head)
            self.tree_o.column(c, width=wd, anchor="center")
        sb2 = ttk.Scrollbar(frm_o, orient="vertical", command=self.tree_o.yview)
        self.tree_o.configure(yscrollcommand=sb2.set)
        self.tree_o.pack(side="top", fill="both", expand=True, padx=(6, 0), pady=(6, 2))
        self.tree_o.tag_configure("credited", background="#E2EFDA")
        self.tree_o.tag_configure("manual", background="#FFF2CC")
        self.tree_o.bind("<<TreeviewSelect>>", self._on_option)
        self.info = tk.Text(frm_o, height=5, wrap="word", state="disabled", background="#F5F5F5",
                            font="TkDefaultFont")
        self.info.pack(side="top", fill="x", padx=6, pady=(2, 6))

        # --- Knoepfe ---
        frm_b = ttk.Frame(self)
        frm_b.pack(fill="x", padx=8, pady=(4, 8))
        self.btn_apply = ttk.Button(frm_b, text=tr("Diesen Start übernehmen"), command=self._apply, state="disabled")
        self.btn_apply.pack(side="left", padx=4)
        self.btn_reset = ttk.Button(frm_b, text=tr("Auf automatische Wertung zurücksetzen"),
                                    command=self._reset, state="disabled")
        self.btn_reset.pack(side="left", padx=4)
        ttk.Button(frm_b, text=tr("Schließen"), command=self.destroy).pack(side="right", padx=4)

        self._fill_pilots()

    # ------------------------------------------------------------------
    def _title(self):
        t = tr("Andere Abflüge wählen")
        a = self.app
        if a.multi["on"] and a.jobs[a.cur]["name"]:
            t += f" - {a.jobs[a.cur]['name']}"
        return t

    def reload_job(self):
        """Anderer Reiter aktiv: Listen neu aufbauen."""
        self._opt_cache.clear()
        self._cur_file = None
        self.title(self._title())
        self.tree_o.delete(*self.tree_o.get_children())
        self._opt_rows = {}
        self._set_info("")
        self.btn_apply.config(state="disabled")
        self.btn_reset.config(state="disabled")
        self._fill_pilots()

    def _fill_pilots(self, keep=None):
        self.tree_p.delete(*self.tree_p.get_children())
        rd = self.app._run_data
        for fname, res in (rd["results"].items() if rd else []):
            manual = res.start.manual
            self.tree_p.insert("", "end", iid=fname, values=(
                fname, res.pilot or tr("(ohne Namen)"),
                seconds_to_hms(res.start.time_s) if res.start.valid else "-",
                method_label(res.start.method),
                tr("manuell gewählt") if manual else tr("automatisch")),
                tags=("manual",) if manual else ())
        self.tree_p.tag_configure("manual", background="#FFF2CC")
        if keep and self.tree_p.exists(keep):
            self.tree_p.selection_set(keep)

    def refresh(self, changed=None):
        """Piloten-Liste neu aufbauen (z. B. nach Auto-Auswertung); Optionen-Cache der
        geaenderten Dateien verwerfen (changed=None -> alles)."""
        if changed is None:
            self._opt_cache.clear()
        else:
            for f in changed:
                self._opt_cache.pop(f, None)
        keep = self._cur_file
        self._fill_pilots(keep=keep)
        if keep and self.tree_p.exists(keep):
            self._fill_options()

    def _on_pilot(self, event=None):
        sel = self.tree_p.selection()
        if not sel:
            return
        fname = sel[0]
        self._cur_file = fname
        if fname not in self._opt_cache:
            self.config(cursor="watch")
            self.update_idletasks()
            try:
                rd = self.app._run_data
                self._opt_cache[fname] = list_start_options(rd["flights"][fname], rd["task"])
            finally:
                self.config(cursor="")
        self._fill_options()

    def _fill_options(self):
        self.tree_o.delete(*self.tree_o.get_children())
        self._opt_rows = {}
        fname = self._cur_file
        res = self.app._run_data["results"][fname]
        for n, o in enumerate(self._opt_cache.get(fname, [])):
            is_now = (res.start.valid and res.start.method == o.kind and res.start.time_s == o.time_s)
            if is_now and res.start.manual:
                state, tag = tr("manuell gewählt"), "manual"
            elif o.credited:
                state, tag = tr("automatisch gewertet"), "credited"
            else:
                state, tag = "", ""
            if is_now and not res.start.manual and not o.credited:
                state = tr("gewertet")
            iid = str(n)
            self._opt_rows[iid] = o
            self.tree_o.insert("", "end", iid=iid, tags=(tag,) if tag else (), values=(
                seconds_to_hms(o.time_s), method_label(o.kind), f"{o.edge_m:+.0f}",
                f"{o.progress}/{o.n_zones}" if o.n_zones else "-",
                f"{o.speed_kmh:.1f}" if o.speed_kmh is not None else "-",
                f"{o.penalty_min:.0f}" if o.penalty_min else "0", state))
        self._set_info("")
        self.btn_apply.config(state="disabled")
        self.btn_reset.config(state="normal" if res.start.manual else "disabled")

    def _on_option(self, event=None):
        sel = self.tree_o.selection()
        if not sel:
            self.btn_apply.config(state="disabled")
            return
        o = self._opt_rows[sel[0]]
        self._set_info("\n".join("• " + r for r in o.reasons) if o.reasons else
                       tr("Keine Auffälligkeiten."))
        self.btn_apply.config(state="normal")

    def _set_info(self, text):
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.config(state="disabled")

    def _apply(self):
        sel = self.tree_o.selection()
        if not sel or not self._cur_file:
            return
        o = self._opt_rows[sel[0]]
        if self.app._apply_start_choice(self._cur_file, o.key):
            self._fill_pilots(keep=self._cur_file)
            self._fill_options()

    def _reset(self):
        if self._cur_file and self.app._apply_start_choice(self._cur_file, None):
            self._fill_pilots(keep=self._cur_file)
            self._fill_options()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.zones = []
        self.jobs = [self._new_job("")]  # Auswertungen (Reiter): Klasse + Tag
        self.cur = 0
        self.multi = {"on": False, "mode": "folder", "date_filter": True,
                      "persist_manual": False, "logger_map": {}}
        self._tab_lock = False
        self._hdr_cache = {}
        self._unassigned = {}           # (Ordner, Datei) -> Grund
        self._choice_dlg = None
        self._auto_active = False       # Auto-Auswertung laeuft
        self._auto_next = 0.0           # naechster Pruefzeitpunkt (time.time())
        self._auto_global = None        # Zuordnungs-Stand der Auto-Auswertung
        self._busy = False              # verhindert Wiederholung des Timers in Dialogen
        self.settings = load_settings()
        set_lang(self.settings.get("lang") or _default_language())
        self.title(tr("Zylinderabflug-Auswertetool (Annex A 7.4.4)"))
        self.cup_points = []
        self.cup_name = ""
        self._build_ui()
        self._load_stored_cup()
        self._restore_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)
        self._fit_window(initial=True)
        self.after(1000, self._tick)

    def _fit_window(self, initial=False):
        """Fenster so gross, dass moeglichst alles sichtbar ist; sonst Scrollbalken."""
        self.update_idletasks()
        body_w, body_h = self.body.winfo_reqwidth(), self.body.winfo_reqheight()
        self.canvas.configure(width=body_w, height=body_h)
        self.update_idletasks()
        w = max(self.winfo_reqwidth() + 20, 900)
        h = self.winfo_reqheight() + 10
        if not initial:
            w = max(w, self.winfo_width())
            h = max(h, self.winfo_height())
        w = min(w, self.winfo_screenwidth() - 40)
        h = min(h, self.winfo_screenheight() - 90)
        self.geometry(f"{w}x{h}")
        # Canvas darf schrumpfen: kleine Bildschirme -> Scrollbalken statt abgeschnittener Inhalt
        self.canvas.configure(width=1, height=1)
        self.minsize(min(w, 700), min(h, 400))
        self.update_idletasks()
        self._update_scrollbar()

    def _on_body_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event):
        # Inhalt immer so breit wie das Fenster
        self.canvas.itemconfigure(self._body_id, width=event.width)
        self._update_scrollbar()

    def _update_scrollbar(self):
        """Scrollbalken nur zeigen, wenn der Inhalt hoeher als das Fenster ist."""
        try:
            need = self.body.winfo_reqheight() > self.canvas.winfo_height() + 1
        except tk.TclError:
            return
        if need:
            if not self.vscroll.winfo_ismapped():
                self.vscroll.pack(side="right", fill="y", before=self.canvas)
        elif self.vscroll.winfo_ismapped():
            self.vscroll.pack_forget()
            self.canvas.yview_moveto(0)

    def _on_mousewheel(self, event):
        w = event.widget
        try:
            cls = w.winfo_class()
        except Exception:
            return
        if cls in ("Text", "Listbox", "Treeview", "TCombobox"):
            return          # diese Felder scrollen selbst
        if not self.vscroll.winfo_ismapped():
            return
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step * 3, "units")

    def _change_language(self, event=None):
        """Sprache sofort umschalten: Oberflaeche neu aufbauen, Eingaben bleiben erhalten."""
        code = self._lang_codes[self.lang_box.current()]
        if code == get_lang():
            return
        keep = {"log": self.log.get("1.0", "end-1c")}
        self._save_cur_state()
        self._store_settings()
        self.settings["lang"] = code
        save_settings(self.settings)
        set_lang(code)
        for child in self.winfo_children():
            child.destroy()
        self.title(tr("Zylinderabflug-Auswertetool (Annex A 7.4.4)"))
        self._build_ui()
        self._load_stored_cup()
        self._apply_multi_to_ui()
        self._restore_state(self.jobs[self.cur]["state"])
        self.log.insert("1.0", keep["log"])
        self._fit_window()

    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}

        # --- Sprache ---
        frm_lang = ttk.Frame(self)
        frm_lang.pack(fill="x", padx=6, pady=(4, 0))
        self._lang_codes = list(LANGUAGES.keys())
        self.lang_box = ttk.Combobox(frm_lang, state="readonly", width=12,
                                     values=[LANGUAGES[c] for c in self._lang_codes])
        self.lang_box.current(self._lang_codes.index(get_lang()))
        self.lang_box.pack(side="right")
        self.lang_box.bind("<<ComboboxSelected>>", self._change_language)
        ttk.Label(frm_lang, text="Sprache / Language:").pack(side="right", padx=6)
        self.lbl_auto = tk.Label(frm_lang, text="", font=("TkDefaultFont", 9, "bold"), anchor="w")
        self.lbl_auto.pack(side="left", fill="x", expand=True)

        # --- Parameter speichern/laden + Auswertung (zwei Zeilen) ---
        frm_actions = ttk.Frame(self)
        frm_actions.pack(side="bottom", fill="x", **pad)
        rowA = ttk.Frame(frm_actions)
        rowA.pack(side="top", fill="x")
        rowB = ttk.Frame(frm_actions)
        rowB.pack(side="top", fill="x", pady=(4, 0))
        ttk.Button(rowA, text=tr("Parameter laden..."), command=self._load_params).pack(side="left", padx=4)
        ttk.Button(rowA, text=tr("Parameter speichern..."), command=self._save_params).pack(side="left", padx=4)
        self.btn_start = ttk.Button(rowA, text=tr("Auswertung starten"), command=self._run)
        self.btn_start.pack(side="right", padx=4)
        self.btn_auto = ttk.Button(rowA, text=tr("Auto-Auswertung starten"), command=self._auto_toggle)
        self.btn_auto.pack(side="right", padx=4)
        self.btn_recalc = ttk.Button(rowA, text=tr("Alle neu berechnen"), command=self._recalc_clicked)
        self.btn_recalc.pack(side="right", padx=4)
        self.btn_choose = ttk.Button(rowB, text=tr("Andere Abflüge wählen..."), command=self._open_choice)
        self.btn_choose.pack(side="right", padx=4)
        self.btn_report = ttk.Button(rowB, text=tr("Report öffnen"), command=self._open_report)
        self.btn_report.pack(side="right", padx=4)

        # --- Scrollbarer Hauptbereich (Scrollbalken rechts, Mausrad) ---
        mid = self._mid = ttk.Frame(self)
        mid.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(mid, highlightthickness=0, borderwidth=0)
        self.vscroll = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # --- Reiterleiste (nur bei "Mehrere Klassen / Tage") ---
        self.job_bar = ttk.Frame(self)
        self.job_nb = ttk.Notebook(self.job_bar)
        self.job_nb.pack(side="left", fill="x", expand=True)
        self.job_nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.btn_close_tab = ttk.Button(self.job_bar, text=tr("Reiter schließen"), command=self._delete_job)
        self.btn_close_tab.pack(side="right", padx=2)
        self.btn_rename = ttk.Button(self.job_bar, text=tr("Umbenennen..."), command=self._rename_job)
        self.btn_rename.pack(side="right", padx=2)
        ttk.Button(self.job_bar, text=tr("Neuer Reiter..."), command=self._add_job).pack(side="right", padx=2)

        # --- Warnbanner (nur sichtbar, wenn der Report gesperrt ist) ---
        self.banner = tk.Frame(self, bg="#C00000")
        self.banner_lbl = tk.Label(self.banner, bg="#C00000", fg="white", justify="left", anchor="w",
                                   font=("TkDefaultFont", 10, "bold"), wraplength=820)
        self.banner_lbl.pack(side="left", fill="x", expand=True, padx=8, pady=6)
        tk.Button(self.banner, text=tr("Jetzt erneut versuchen"),
                  command=self._retry_report).pack(side="right", padx=8, pady=6)

        # --- Mehrere Klassen / Tage ---
        frm_multi = ttk.LabelFrame(self.body, text=tr("Mehrere Klassen / Tage"))
        frm_multi.pack(fill="x", **pad)
        self.multi_on_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="folder")
        self.date_filter_var = tk.BooleanVar(value=True)
        self.persist_var = tk.BooleanVar(value=False)
        self.chk_multi = ttk.Checkbutton(frm_multi, text=tr("Mehrere Klassen / Tage gleichzeitig auswerten"),
                                         variable=self.multi_on_var, command=self._on_multi_toggle)
        self.chk_multi.pack(anchor="w", padx=6, pady=4)
        self.multi_opts = ttk.Frame(frm_multi)
        ttk.Label(self.multi_opts, foreground="#555", wraplength=820, justify="left",
                  text=tr("Jede Klasse bzw. jeder Tag bekommt oben einen eigenen Reiter mit eigener Aufgabe, "
                          "eigenen Ordnern und eigenem Report. Der Reitername ist der Klassenname. "
                          "Dieselbe Klasse kann für mehrere Tage ausgewertet werden (z. B. nachgereichte "
                          "Dateien vom Vortag).")).pack(anchor="w")
        ttk.Radiobutton(self.multi_opts, variable=self.mode_var, value="folder", command=self._on_multi_option,
                        text=tr("Klassen durch getrennte Ordner unterscheiden (jeder Reiter hat seinen Quellordner)")
                        ).pack(anchor="w", pady=(4, 0))
        ttk.Radiobutton(self.multi_opts, variable=self.mode_var, value="logger", command=self._on_multi_option,
                        text=tr("Klassen nach Logger-ID (Flightrecorder-ID) unterscheiden")
                        ).pack(anchor="w")
        ttk.Checkbutton(self.multi_opts, variable=self.date_filter_var, command=self._on_multi_option,
                        text=tr("Nur Flüge auswerten, deren IGC-Datum zum Wertungstag des Reiters passt")
                        ).pack(anchor="w", pady=(4, 0))
        self.logger_frame = ttk.Frame(self.multi_opts)
        self.logger_tree = ttk.Treeview(self.logger_frame, columns=("id", "cls"), show="headings", height=4)
        self.logger_tree.heading("id", text=tr("Logger-ID"))
        self.logger_tree.heading("cls", text=tr("Klasse"))
        self.logger_tree.column("id", width=140, anchor="w")
        self.logger_tree.column("cls", width=200, anchor="w")
        self.logger_tree.pack(side="left", fill="x", expand=True)
        lb = ttk.Frame(self.logger_frame)
        lb.pack(side="left", fill="y", padx=6)
        ttk.Button(lb, text=tr("Hinzufügen..."), command=lambda: self._logger_edit(True)).pack(fill="x", pady=1)
        ttk.Button(lb, text=tr("Ändern..."), command=lambda: self._logger_edit(False)).pack(fill="x", pady=1)
        ttk.Button(lb, text=tr("Löschen"), command=self._logger_delete).pack(fill="x", pady=1)
        ttk.Button(lb, text=tr("Aus Datei laden..."), command=self._logger_load_file).pack(fill="x", pady=1)
        ttk.Button(lb, text=tr("Liste leeren"), command=self._logger_clear).pack(fill="x", pady=1)
        self.logger_tree.bind("<Double-1>", lambda e: self._logger_edit(False))

        # --- Ordner ---
        frm_folders = ttk.LabelFrame(self.body, text=tr("Ordner"))
        frm_folders.pack(fill="x", **pad)

        self.src_var = tk.StringVar()
        self.dst_var = tk.StringVar()
        ttk.Label(frm_folders, text=tr("Quellordner (IGC-Dateien):")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm_folders, textvariable=self.src_var, width=60).grid(row=0, column=1, **pad)
        ttk.Button(frm_folders, text=tr("Durchsuchen..."), command=self._pick_src).grid(row=0, column=2, **pad)

        ttk.Label(frm_folders, text=tr("Zielordner (Kopien + Report):")).grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm_folders, textvariable=self.dst_var, width=60).grid(row=1, column=1, **pad)
        ttk.Button(frm_folders, text=tr("Durchsuchen..."), command=self._pick_dst).grid(row=1, column=2, **pad)

        self.cup_label_var = tk.StringVar(value=tr("(keine CUP-Datei gespeichert)"))
        ttk.Label(frm_folders, text=tr("Wendepunktdatei (CUP):")).grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(frm_folders, textvariable=self.cup_label_var, foreground="#1F4E78").grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Button(frm_folders, text=tr("Wechseln..."), command=self._change_cup).grid(row=2, column=2, **pad)
        ttk.Checkbutton(frm_folders, variable=self.persist_var, command=self._on_multi_option,
                        text=tr("Manuelle Startwahlen speichern (bleiben nach Programmneustart erhalten)")
                        ).grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        # --- Start-Zylinder ---
        frm_start = ttk.LabelFrame(self.body, text=tr("Start-Zylinder (Task Sheet)"))
        frm_start.pack(fill="x", **pad)

        self.start_lat_var = tk.StringVar()
        self.start_lon_var = tk.StringVar()
        self.start_radius_var = tk.StringVar(value="10000")
        self.gate_open_var = tk.StringVar(value=self.GATE_DEFAULT)
        self.tz_var = tk.StringVar(value="2.0")
        self.date_var = tk.StringVar(value=datetime.date.today().strftime("%d.%m.%Y"))
        self.date_var.trace_add("write", lambda *a: self._relabel_tab())

        ttk.Button(frm_start, text=tr("Aufgabe aus IGC-Datei laden (SoaringSpot)..."),
                   command=self._load_task_from_soaringspot).grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        ttk.Button(frm_start, text=tr("Aufgabe von SoaringSpot-Webseite laden..."),
                   command=self._load_task_from_website).grid(row=0, column=3, columnspan=2, sticky="w", **pad)

        ttk.Label(frm_start, text=tr("Breite:")).grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm_start, textvariable=self.start_lat_var, width=14).grid(row=1, column=1, **pad)
        ttk.Label(frm_start, text=tr("Länge:")).grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(frm_start, textvariable=self.start_lon_var, width=14).grid(row=1, column=3, **pad)
        ttk.Button(frm_start, text=tr("Aus CUP-Datei..."), command=self._pick_start_from_cup).grid(row=1, column=4, **pad)

        ttk.Label(frm_start, text=tr("Radius (m):")).grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm_start, textvariable=self.start_radius_var, width=14).grid(row=2, column=1, **pad)
        ttk.Label(frm_start, text=tr("Toröffnung (Ortszeit HH:MM:SS):")).grid(row=2, column=2, sticky="w", **pad)
        self.gate_entry = tk.Entry(frm_start, textvariable=self.gate_open_var, width=14)
        self.gate_entry.grid(row=2, column=3, **pad)
        self.gate_open_var.trace_add("write", lambda *a: self._mark_gate_default())
        self._mark_gate_default()
        ttk.Label(frm_start, text=tr("Zeitzone (h, ggü. UTC):")).grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frm_start, textvariable=self.tz_var, width=14).grid(row=3, column=1, **pad)
        ttk.Label(frm_start, text=tr("Wertungstag (TT.MM.JJJJ):")).grid(row=3, column=2, sticky="w", **pad)
        ttk.Entry(frm_start, textvariable=self.date_var, width=14).grid(row=3, column=3, **pad)
        ttk.Label(frm_start, text=tr("(Radius ggf. von Hand korrigieren, falls die geladene\n"
                                  "Datei bereits einen Mini-Zylinder enthält)"),
                  foreground="#555").grid(row=4, column=2, columnspan=2, sticky="w", **pad)

        # --- Tagesparameter ---
        frm_day = ttk.LabelFrame(self.body, text=tr("Tagesparameter (Task Sheet, national ggf. abweichend)"))
        frm_day.pack(fill="x", **pad)

        self.max_gsp_var = tk.StringVar(value="160")
        self.max_loh_var = tk.StringVar(value="800")
        self.pev_interval_var = tk.StringVar(value="10")
        self.pev_cluster_var = tk.StringVar(value="30")
        self.tolerance_var = tk.StringVar(value="0")
        self.tolerance_pts_var = tk.StringVar(value="50")
        self.task_time_var = tk.StringVar(value="")
        self.loh_per_pt_var = tk.StringVar(value="3")

        fields = [
            (tr("Max. Groundspeed am Start (km/h):"), self.max_gsp_var),
            (tr("Max. Loss of Height (m):"), self.max_loh_var),
            (tr("Loss-of-Height-Strafe: Meter je Punkt:"), self.loh_per_pt_var),
            (tr("PEV-Mindestintervall (Minuten):"), self.pev_interval_var),
            (tr("PEV-Cluster-Fenster (Sekunden):"), self.pev_cluster_var),
            (tr("PEV-Toleranz außerhalb Zylinder (m, 0 = aus):"), self.tolerance_var),
            (tr("Strafpunkte bei Toleranz-PEV:"), self.tolerance_pts_var),
            (tr("AAT-Mindestzeit (HH:MM:SS, leer=Racing Task):"), self.task_time_var),
        ]
        for i, (lab, var) in enumerate(fields):
            r, c = divmod(i, 2)
            ttk.Label(frm_day, text=lab).grid(row=r, column=c * 2, sticky="w", **pad)
            ttk.Entry(frm_day, textvariable=var, width=10).grid(row=r, column=c * 2 + 1, **pad)

        # --- Baro-Kalibrierung ---
        frm_baro = ttk.LabelFrame(self.body, text=tr("Baro-Höhe kalibrieren (optional)"))
        frm_baro.pack(fill="x", **pad)
        self.cal_on_var = tk.BooleanVar(value=False)
        self.ref_elev_var = tk.StringVar(value="")
        self.cal_n_var = tk.StringVar(value="60")
        ttk.Checkbutton(frm_baro, text=tr("Baro auf Referenzhöhe kalibrieren"),
                        variable=self.cal_on_var).grid(row=0, column=0, sticky="w", **pad)
        ttk.Label(frm_baro, text=tr("Platzhöhe am Start (m MSL):")).grid(row=0, column=1, sticky="e", **pad)
        ttk.Entry(frm_baro, textvariable=self.ref_elev_var, width=8).grid(row=0, column=2, **pad)
        ttk.Label(frm_baro, text=tr("Anfangsfixe (Standphase):")).grid(row=0, column=3, sticky="e", **pad)
        ttk.Entry(frm_baro, textvariable=self.cal_n_var, width=6).grid(row=0, column=4, **pad)
        ttk.Label(frm_baro, foreground="#555", wraplength=820, justify="left",
                  text=tr("Die Anfangsfixe jeder Datei (Standphase am Boden) werden auf die Platzhöhe gesetzt. "
                          "Beginnt eine Datei in der Luft, bleibt sie unkalibriert (Hinweis im Report). "
                          "Der Höhenverlust ändert sich durch die Kalibrierung nicht.")
                  ).grid(row=1, column=0, columnspan=5, sticky="w", **pad)

        # --- Streckenfuehrung ---
        frm_zones = ttk.LabelFrame(self.body, text=tr("Streckenführung in Flugreihenfolge (letzter Punkt = Ziel)"))
        frm_zones.pack(fill="both", expand=True, **pad)

        cols = ("name", "lat", "lon", "radius", "r_min", "angles", "max_alt", "finish")
        self.tree = ttk.Treeview(frm_zones, columns=cols, show="headings", height=4)
        headers = {"name": tr("Name"), "lat": tr("Breite"), "lon": tr("Länge"), "radius": tr("R1 (m)"),
                   "r_min": tr("R2 (m)"), "angles": tr("A1/A2 (°)"), "max_alt": tr("MaxAlt (m)"), "finish": tr("Ziel")}
        widths = {"name": 120, "lat": 90, "lon": 90, "radius": 70, "r_min": 60,
                  "angles": 80, "max_alt": 70, "finish": 50}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        btns_zone = ttk.Frame(frm_zones)
        btns_zone.pack(side="left", fill="y", padx=6)
        ttk.Button(btns_zone, text=tr("Aus CUP-Datei hinzufügen..."), command=self._add_zone_from_cup).pack(fill="x", pady=2)
        ttk.Button(btns_zone, text=tr("Manuell hinzufügen..."), command=self._add_zone_manual).pack(fill="x", pady=2)
        ttk.Button(btns_zone, text=tr("Bearbeiten..."), command=self._edit_zone).pack(fill="x", pady=2)
        ttk.Button(btns_zone, text=tr("Löschen"), command=self._delete_zone).pack(fill="x", pady=2)
        ttk.Button(btns_zone, text=tr("Nach oben"), command=lambda: self._move_zone(-1)).pack(fill="x", pady=2)
        ttk.Button(btns_zone, text=tr("Nach unten"), command=lambda: self._move_zone(1)).pack(fill="x", pady=2)

        # --- Log ---
        frm_log = ttk.LabelFrame(self.body, text=tr("Protokoll"))
        frm_log.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(frm_log, height=6, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        self._sync_ui_state()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Einstellungen merken (nicht: Wertungstag und Toröffnung -> beim Start heute / 00:00:00)
    _STR_VARS = [
        ("start_lat", "start_lat_var"), ("start_lon", "start_lon_var"),
        ("start_radius", "start_radius_var"), ("tz", "tz_var"),
        ("max_gsp", "max_gsp_var"), ("max_loh", "max_loh_var"), ("loh_per_pt", "loh_per_pt_var"),
        ("pev_interval", "pev_interval_var"), ("pev_cluster", "pev_cluster_var"),
        ("tolerance", "tolerance_var"), ("tolerance_pts", "tolerance_pts_var"),
        ("task_time", "task_time_var"), ("ref_elev", "ref_elev_var"), ("cal_n", "cal_n_var"),
        ("src", "src_var"), ("dst", "dst_var"),
    ]

    def _restore_settings(self):
        saved = self.settings.get("values", {})
        for key, attr in self._STR_VARS:
            if key in saved:
                getattr(self, attr).set(str(saved[key]))
        if "cal_on" in saved:
            self.cal_on_var.set(bool(saved["cal_on"]))
        try:
            self.zones = [Zone(**z) for z in saved.get("zones", [])]
        except TypeError:
            self.zones = []
        self._refresh_tree()
        m = self.settings.get("multi", {})
        self.multi["mode"] = m.get("mode", "folder") if m.get("mode") in ("folder", "logger") else "folder"
        self.multi["date_filter"] = bool(m.get("date_filter", True))
        self.multi["persist_manual"] = bool(m.get("persist_manual", False))
        self.multi["logger_map"] = {str(k).upper(): str(v) for k, v in m.get("logger_map", {}).items()}
        jobs = m.get("jobs") or []
        if m.get("on") and jobs:
            self.multi["on"] = True
            self.jobs = [self._new_job(j.get("name", ""), self._state_from_values(j.get("values", {})))
                         for j in jobs]
            self.cur = min(max(int(m.get("cur", 0)), 0), len(self.jobs) - 1)
            self._restore_state(self.jobs[self.cur]["state"])
        else:
            self.jobs = [self._new_job(m.get("name", ""))]
            self.cur = 0
        self._apply_multi_to_ui()

    def _store_settings(self):
        st = self._param_state()
        self.settings["values"] = self._values_from_state(st)
        jobs = []
        for job in self.jobs:
            js = st if job is self.jobs[self.cur] else (job["state"] or self._default_state())
            jobs.append({"name": job["name"], "values": self._values_from_state(js)})
        m = self.multi
        self.settings["multi"] = {
            "on": m["on"], "mode": m["mode"], "date_filter": m["date_filter"],
            "persist_manual": m["persist_manual"], "logger_map": dict(m["logger_map"]),
            "cur": self.cur, "jobs": jobs, "name": self.jobs[self.cur]["name"]}
        save_settings(self.settings)

    def _on_close(self):
        try:
            self._store_settings()
        finally:
            self.destroy()

    # Dateidialoge: je Dialog wird der zuletzt gewaehlte Ordner gemerkt (auch nach Neustart)
    def _initdir(self, key):
        d = self.settings.get("dirs", {}).get(key)
        return d if d and os.path.isdir(d) else None

    def _remember_dir(self, key, path, is_dir=False):
        if not path:
            return
        d = path if is_dir else os.path.dirname(path)
        if d:
            self.settings.setdefault("dirs", {})[key] = d
            save_settings(self.settings)

    def _ask_file(self, key, **kw):
        init = self._initdir(key)
        if init:
            kw["initialdir"] = init
        path = filedialog.askopenfilename(**kw)
        if path:
            self._remember_dir(key, path)
        return path

    def _ask_save(self, key, **kw):
        init = self._initdir(key)
        if init:
            kw["initialdir"] = init
        path = filedialog.asksaveasfilename(**kw)
        if path:
            self._remember_dir(key, path)
        return path

    def _ask_dir(self, key, **kw):
        init = self._initdir(key)
        if init:
            kw["initialdir"] = init
        d = filedialog.askdirectory(**kw)
        if d:
            self._remember_dir(key, d, is_dir=True)
        return d

    GATE_DEFAULT = "03:00:00"

    def _mark_gate_default(self):
        """Toröffnung gelb + fett, solange sie noch dem Default entspricht (= vermutlich nicht gesetzt)."""
        is_default = self.gate_open_var.get().strip() == self.GATE_DEFAULT
        self.gate_entry.config(
            bg="#FFE699" if is_default else "white",
            font=("TkDefaultFont", 9, "bold") if is_default else "TkDefaultFont")

    def _log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.update_idletasks()

    def _pick_src(self):
        d = self._ask_dir("dir_src", title=tr("Quellordner mit IGC-Dateien wählen"))
        if d:
            self.src_var.set(d)

    def _pick_dst(self):
        d = self._ask_dir("dir_dst", title=tr("Zielordner wählen"))
        if d:
            self.dst_var.set(d)

    # ------------------------------------------------------------------
    # CUP-Datei: einmal waehlen, dauerhaft gespeichert
    def _load_stored_cup(self):
        if os.path.isfile(STORED_CUP):
            try:
                self.cup_points = parse_cup_file(STORED_CUP)
                self.cup_name = self.settings.get("cup_name", "stored.cup")
                self.cup_label_var.set(tr("{name}  ({n} Punkte, gespeichert)", name=self.cup_name, n=len(self.cup_points)))
                return
            except Exception:
                pass
        self.cup_points = []
        self.cup_name = ""
        self.cup_label_var.set(tr("(keine CUP-Datei gespeichert)"))

    def _change_cup(self):
        """Neue CUP-Datei waehlen und dauerhaft speichern. True bei Erfolg."""
        path = self._ask_file(
            "dir_cup",
            title=tr("CUP-Datei mit den Wendepunkten wählen"),
            filetypes=[(tr("CUP-Dateien"), "*.cup"), (tr("Alle Dateien"), "*.*")])
        if not path:
            return False
        try:
            points = parse_cup_file(path)
        except Exception as e:
            messagebox.showerror(tr("Fehler"), tr("CUP-Datei konnte nicht gelesen werden:\n{e}", e=e))
            return False
        if not points:
            messagebox.showerror(tr("Fehler"), tr("In der CUP-Datei wurden keine Wendepunkte gefunden."))
            return False
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            shutil.copyfile(path, STORED_CUP)
        except OSError as e:
            messagebox.showwarning(tr("Hinweis"), tr("CUP-Datei konnte nicht dauerhaft gespeichert werden "
                                                     "(gilt nur für diese Sitzung):\n{e}", e=e))
        self.settings["cup_name"] = os.path.basename(path)
        save_settings(self.settings)
        self.cup_points = points
        self.cup_name = os.path.basename(path)
        self.cup_label_var.set(tr("{name}  ({n} Punkte, gespeichert)", name=self.cup_name, n=len(points)))
        self._log(tr("CUP-Datei gespeichert: {path} ({n} Punkte)", path=path, n=len(points)))
        return True

    def _get_cup_points(self):
        """Gespeicherte CUP verwenden; nur falls keine vorhanden ist, nachfragen."""
        if not self.cup_points:
            if not self._change_cup():
                return None
        return self.cup_points

    def _pick_start_from_cup(self):
        points = self._get_cup_points()
        if not points:
            return
        dlg = CupPickDialog(self, points)
        self.wait_window(dlg)
        if dlg.result:
            name, lat, lon = dlg.result
            self.start_lat_var.set(f"{lat:.6f}")
            self.start_lon_var.set(f"{lon:.6f}")

    def _load_task_from_website(self):
        if not WEB_IMPORT_AVAILABLE:
            messagebox.showerror(
                tr("Nicht verfügbar"),
                tr("Dafür fehlen die Pakete 'requests' und 'beautifulsoup4'. Bitte "
                   "install.bat bzw. build_exe.bat einmal ausführen, das installiert "
                   "sie automatisch."))
            return

        dlg = UrlDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            url, url_date, converted = normalize_task_url(dlg.result)
        except ValueError as e:
            messagebox.showerror(tr("Link nicht verwendbar"), str(e))
            return
        if converted:
            self._log(tr("Link war keine Task-Seite - verwende automatisch: {url}", url=url))
        self.date_var.set(url_date)

        try:
            html = fetch_task_page_html(url)
            info = parse_task_page(html)
        except Exception as e:
            messagebox.showerror(tr("Fehler"), tr("Seite konnte nicht gelesen/erkannt werden:\n{e}", e=e))
            return

        if not info.turnpoints:
            messagebox.showwarning(tr("Keine Streckenpunkte gefunden"),
                                   tr("Auf dieser Seite wurden keine Streckenpunkte erkannt."))
            return

        # gespeicherte CUP verwenden; nur wenn keine da ist oder Namen nicht mehr passen -> neue waehlen
        if not self.cup_points:
            messagebox.showinfo(
                tr("Koordinaten fehlen auf dieser Seite"),
                tr("{n} Streckenpunkte gefunden (inkl. Start). Diese Seite "
                   "enthält keine Koordinaten - bitte im nächsten Schritt die CUP-Datei mit den "
                   "Wendepunkten wählen (wird dauerhaft gespeichert).", n=len(info.turnpoints)))
            if not self._change_cup():
                return
        resolved, unresolved = match_names_to_cup(info.turnpoints, self.cup_points)
        if unresolved:
            if messagebox.askyesno(
                    tr("CUP-Datei passt nicht"),
                    tr("Folgende Punkte der Aufgabe wurden in der gespeicherten CUP-Datei "
                       "({name}) nicht gefunden:", name=self.cup_name) + "\n\n" + "\n".join(unresolved)
                    + "\n\n" + tr("Neue CUP-Datei wählen?")):
                if self._change_cup():
                    resolved, unresolved = match_names_to_cup(info.turnpoints, self.cup_points)
        if unresolved:
            messagebox.showwarning(
                tr("Nicht alle Punkte gefunden"),
                tr("Für folgende Streckenpunkte fehlen die Koordinaten - bitte manuell "
                   "nachtragen/korrigieren:") + "\n\n" + "\n".join(unresolved))

        start_tp = info.turnpoints[0]
        if start_tp.name in resolved:
            lat, lon = resolved[start_tp.name]
            self.start_lat_var.set(f"{lat:.6f}")
            self.start_lon_var.set(f"{lon:.6f}")
        if start_tp.radius_m:
            self.start_radius_var.set(f"{start_tp.radius_m:.0f}")

        self.zones = []
        for i, tp in enumerate(info.turnpoints[1:]):
            is_last = (i == len(info.turnpoints) - 2)
            if tp.name in resolved:
                lat, lon = resolved[tp.name]
            else:
                lat, lon = 0.0, 0.0  # Platzhalter, muss manuell nachgetragen werden
            self.zones.append(Zone(
                name=tp.name, lat=lat, lon=lon, radius_m=tp.radius_m or 0.0,
                r_min_m=tp.r_min_m, angle_max_deg=tp.angle_deg, is_finish=is_last,
            ))
        self._refresh_tree()

        if info.task_duration:
            self.task_time_var.set(info.task_duration)
        # Datum kommt aus dem Link (verlaesslicher als die Seitenueberschrift)

        self._log(tr("Aufgabe von Webseite geladen: {url}", url=url))
        self._log(tr("  {n} Streckenpunkte, AAT-Zeit: {t}", n=len(self.zones),
                     t=info.task_duration or tr("(keine, Racing Task)")))
        if unresolved:
            self._log(tr("  ACHTUNG - Koordinaten fehlen für: {names} (0.0/0.0 eingetragen)",
                         names=", ".join(unresolved)))

        if info.task_notes:
            NotesDialog(self, info.task_notes)
        else:
            self._log(tr("  Keine 'Task notes' auf dieser Seite - Toröffnung, Max. Groundspeed "
                         "und Max. Loss of Height bitte manuell eintragen."))

    def _load_task_from_soaringspot(self):
        path = self._ask_file(
            "dir_igc",
            title=tr("Eine beliebige (originale) IGC-Datei des Wertungstages wählen"),
            filetypes=[(tr("IGC-Dateien"), "*.igc"), (tr("Alle Dateien"), "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="latin-1", errors="replace") as f:
                lines = [ln.rstrip("\r\n") for ln in f.readlines()]
            block = find_soaringspot_block(lines)
        except Exception as e:
            messagebox.showerror(tr("Fehler"), tr("Datei konnte nicht gelesen werden:\n{e}", e=e))
            return
        if block is None:
            messagebox.showwarning(
                tr("Kein SoaringSpot-Block gefunden"),
                tr("In dieser Datei wurde kein SoaringSpot-Aufgabenblock (LCU::/LSEEYOU) "
                   "gefunden. Bitte eine Original-IGC-Datei von SoaringSpot verwenden, "
                   "oder die Aufgabe per CUP-Datei/manuell eingeben."))
            return

        start_wp = block.waypoints[0]
        self.start_lat_var.set(f"{start_wp.lat:.6f}")
        self.start_lon_var.set(f"{start_wp.lon:.6f}")
        if start_wp.radius_m and start_wp.radius_m > 5:
            self.start_radius_var.set(f"{start_wp.radius_m:.0f}")
        else:
            self._log(tr("Hinweis: Diese Datei enthält beim Start bereits einen Mini-Zylinder "
                         "(vermutlich schon einmal verarbeitet) - bitte den echten Zylinderradius "
                         "von Hand eintragen, er wurde NICHT automatisch übernommen."))
        if block.gate_open_local:
            self.gate_open_var.set(block.gate_open_local)
        if block.tz_offset_h is not None:
            self.tz_var.set(str(block.tz_offset_h))

        m = re.search(r'HFDTEDATE[^\d]*(\d{2})(\d{2})(\d{2})', "\n".join(lines))
        if m:
            dd, mm, yy = m.groups()
            self.date_var.set(f"{dd}.{mm}.20{yy}")

        self.zones = zones_from_block(block)
        self._refresh_tree()
        self._log(tr("Aufgabe geladen aus: {path}\n  {n} Streckenpunkte, Toröffnung {gate}, Zeitzone {tz}",
                     path=path, n=len(self.zones), gate=block.gate_open_local, tz=block.tz_offset_h))

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for z in self.zones:
            self.tree.insert("", "end", values=(
                z.name, f"{z.lat:.5f}", f"{z.lon:.5f}", f"{z.radius_m:.0f}",
                f"{z.r_min_m:.0f}", f"{z.angle_max_deg:g}/{z.angle_min_deg:g}",
                f"{z.max_alt_m:g}", tr("Ziel") if z.is_finish else ""))

    def _add_zone_from_cup(self):
        points = self._get_cup_points()
        if not points:
            return
        dlg = CupPickDialog(self, points)
        self.wait_window(dlg)
        if dlg.result:
            zdlg = ZoneDialog(self, prefill=dlg.result)
            self.wait_window(zdlg)
            if zdlg.result:
                self.zones.append(zdlg.result)
                self._refresh_tree()

    def _add_zone_manual(self):
        dlg = ZoneDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self.zones.append(dlg.result)
            self._refresh_tree()

    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def _edit_zone(self):
        idx = self._selected_index()
        if idx is None:
            return
        dlg = ZoneDialog(self, zone=self.zones[idx])
        self.wait_window(dlg)
        if dlg.result:
            self.zones[idx] = dlg.result
            self._refresh_tree()

    def _delete_zone(self):
        idx = self._selected_index()
        if idx is None:
            return
        del self.zones[idx]
        self._refresh_tree()

    def _move_zone(self, direction):
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(self.zones):
            self.zones[idx], self.zones[new_idx] = self.zones[new_idx], self.zones[idx]
            self._refresh_tree()
            children = self.tree.get_children()
            self.tree.selection_set(children[new_idx])

    # ------------------------------------------------------------------
    def _collect_task(self) -> TaskParams:
        return self._task_from_state(self._param_state())

    def _save_params(self):
        path = self._ask_save("dir_params", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            task = self._collect_task()
        except ValueError:
            messagebox.showerror(tr("Fehler"), tr("Bitte alle Parameter als Zahl eingeben, bevor gespeichert wird."))
            return
        data = asdict(task)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._log(tr("Parameter gespeichert: {path}", path=path))

    def _load_params(self):
        path = self._ask_file("dir_params", filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.start_lat_var.set(str(data.get("start_lat", "")))
        self.start_lon_var.set(str(data.get("start_lon", "")))
        self.start_radius_var.set(str(data.get("start_radius_m", "")))
        self.gate_open_var.set(str(data.get("gate_open_local", "")))
        self.tz_var.set(str(data.get("tz_offset_h", "")))
        self.date_var.set(str(data.get("date_str", "")))
        self.pev_interval_var.set(str(data.get("min_pev_interval_s", 600) / 60))
        self.pev_cluster_var.set(str(data.get("pev_cluster_s", "")))
        self.tolerance_var.set(str(data.get("tolerance_m", "")))
        self.tolerance_pts_var.set(str(data.get("tolerance_penalty_pts", "")))
        self.max_gsp_var.set(str(data.get("max_groundspeed_kmh", "")))
        self.max_loh_var.set(str(data.get("max_loss_of_height_m", "")))
        self.loh_per_pt_var.set(str(data.get("loh_m_per_point", 3)))
        ref = data.get("ref_elevation_m")
        self.cal_on_var.set(ref is not None)
        self.ref_elev_var.set("" if ref is None else str(ref))
        self.cal_n_var.set(str(data.get("baro_cal_fixes", 60)))
        self.task_time_var.set(str(data.get("task_time_str", "")))
        self.zones = [Zone(**z) for z in data.get("zones", [])]
        self._refresh_tree()
        self._log(tr("Parameter geladen: {path}", path=path))

    # ------------------------------------------------------------------
    # Zustand der Eingabemaske / Auswertungen (Reiter)
    # ------------------------------------------------------------------
    @staticmethod
    def _new_job(name="", state=None):
        return {"name": name, "state": state, "run": None, "snapshot": None, "auto": False,
                "report_pending": False, "report_error": "", "last_report_try": 0.0}

    @property
    def _run_data(self):
        return self.jobs[self.cur]["run"]

    @_run_data.setter
    def _run_data(self, value):
        self.jobs[self.cur]["run"] = value

    def _default_state(self):
        return {
            "start_lat_var": "", "start_lon_var": "", "start_radius_var": "10000", "tz_var": "2.0",
            "max_gsp_var": "160", "max_loh_var": "800", "loh_per_pt_var": "3",
            "pev_interval_var": "10", "pev_cluster_var": "30", "tolerance_var": "0",
            "tolerance_pts_var": "50", "task_time_var": "", "ref_elev_var": "", "cal_n_var": "60",
            "src_var": "", "dst_var": "", "gate_open_var": self.GATE_DEFAULT,
            "date_var": datetime.date.today().strftime("%d.%m.%Y"), "cal_on_var": False,
            "zones_objs": [],
        }

    def _param_state(self):
        st = {attr: getattr(self, attr).get() for _k, attr in self._STR_VARS}
        for attr in ("gate_open_var", "date_var", "cal_on_var"):
            st[attr] = getattr(self, attr).get()
        st["zones_objs"] = copy.deepcopy(self.zones)
        return st

    def _restore_state(self, st):
        for k, v in st.items():
            if k == "zones_objs":
                self.zones = copy.deepcopy(v)
            else:
                getattr(self, k).set(v)
        self._refresh_tree()
        self._mark_gate_default()

    def _values_from_state(self, st):
        """Zustand -> speicherbares Dict (ohne Wertungstag/Toroeffnung)."""
        values = {key: st[attr] for key, attr in self._STR_VARS}
        values["cal_on"] = bool(st["cal_on_var"])
        values["zones"] = [asdict(z) for z in st["zones_objs"]]
        return values

    def _state_from_values(self, values):
        st = self._default_state()
        for key, attr in self._STR_VARS:
            if key in values:
                st[attr] = str(values[key])
        st["cal_on_var"] = bool(values.get("cal_on", False))
        try:
            st["zones_objs"] = [Zone(**z) for z in values.get("zones", [])]
        except TypeError:
            st["zones_objs"] = []
        return st

    def _job_state(self, job):
        return self._param_state() if job is self.jobs[self.cur] else job["state"]

    def _save_cur_state(self):
        self.jobs[self.cur]["state"] = self._param_state()

    @staticmethod
    def _task_from_state(st):
        def f(k):
            return float(str(st[k]).replace(",", "."))
        return TaskParams(
            start_lat=f("start_lat_var"), start_lon=f("start_lon_var"),
            start_radius_m=f("start_radius_var"),
            gate_open_local=str(st["gate_open_var"]).strip(),
            tz_offset_h=f("tz_var"),
            date_str=str(st["date_var"]).strip(),
            min_pev_interval_s=int(f("pev_interval_var") * 60),
            pev_cluster_s=int(f("pev_cluster_var")),
            tolerance_m=f("tolerance_var"),
            tolerance_penalty_pts=f("tolerance_pts_var"),
            max_groundspeed_kmh=f("max_gsp_var"),
            max_loss_of_height_m=f("max_loh_var"),
            loh_m_per_point=f("loh_per_pt_var"),
            ref_elevation_m=(f("ref_elev_var") if st["cal_on_var"] else None),
            baro_cal_fixes=int(float(str(st["cal_n_var"]).replace(",", ".") or "60")),
            task_time_str=str(st["task_time_var"]).strip(),
            zones=list(st["zones_objs"]),
        )

    # ------------------------------------------------------------------
    # Mehrere Klassen / Tage: Reiter, Zuordnung der Dateien
    # ------------------------------------------------------------------
    def _tab_text(self, job):
        date = str(self._job_state(job)["date_var"]).strip()
        name = job["name"] or tr("(Klasse?)")
        return f"{name} · {date}" if date else name

    def _relabel_tab(self):
        try:
            if self.multi["on"] and self.job_nb.winfo_exists() and self.cur < len(self.job_nb.tabs()):
                self.job_nb.tab(self.cur, text=self._tab_text(self.jobs[self.cur]))
        except (tk.TclError, AttributeError):
            pass

    def _rebuild_tabs(self):
        self._tab_lock = True
        try:
            for t in self.job_nb.tabs():
                self.job_nb.forget(t)
            for job in self.jobs:
                fr = ttk.Frame(self.job_nb, height=1)
                self.job_nb.add(fr, text=self._tab_text(job))
            self.job_nb.select(self.cur)
        finally:
            self._tab_lock = False

    def _apply_multi_to_ui(self):
        """self.multi / self.jobs in die Oberflaeche uebernehmen."""
        m = self.multi
        self.multi_on_var.set(m["on"])
        self.mode_var.set(m["mode"])
        self.date_filter_var.set(m["date_filter"])
        self.persist_var.set(m["persist_manual"])
        if m["on"]:
            self.multi_opts.pack(fill="x", padx=6, pady=(0, 6))
            self.job_bar.pack(side="top", fill="x", padx=6, pady=(2, 0), before=self._mid)
            self._rebuild_tabs()
        else:
            self.multi_opts.pack_forget()
            self.job_bar.pack_forget()
        if m["on"] and m["mode"] == "logger":
            self.logger_frame.pack(fill="x", pady=(4, 0))
        else:
            self.logger_frame.pack_forget()
        self._refresh_logger_tree()
        self._sync_ui_state()

    def _on_multi_toggle(self):
        want = bool(self.multi_on_var.get())
        if want == self.multi["on"]:
            return
        if want:
            cur = self.jobs[self.cur]
            res = ask_fields(self, tr("Klasse benennen"),
                             tr("Name der Klasse für den aktuellen Reiter (z. B. Standard, 18m, Club):"),
                             [(tr("Klasse:"), cur["name"], None)])
            if not res or not res[0].strip():
                self.multi_on_var.set(False)
                return
            cur["name"] = res[0].strip()
            self.multi["on"] = True
        else:
            if len(self.jobs) > 1:
                if not messagebox.askyesno(
                        tr("Mehrere Klassen / Tage ausschalten"),
                        tr("Es bleibt nur der aktuelle Reiter erhalten, alle anderen Reiter werden geschlossen "
                           "(bereits geschriebene Reports und IGC-Kopien bleiben bestehen). Fortfahren?")):
                    self.multi_on_var.set(True)
                    return
                self.jobs = [self.jobs[self.cur]]
                self.cur = 0
            self.multi["on"] = False
        self._apply_multi_to_ui()
        self._refresh_choice_dialog(None, reload=True)

    def _on_multi_option(self):
        self.multi["mode"] = self.mode_var.get()
        self.multi["date_filter"] = bool(self.date_filter_var.get())
        self.multi["persist_manual"] = bool(self.persist_var.get())
        if self.multi["on"] and self.multi["mode"] == "logger":
            self.logger_frame.pack(fill="x", pady=(4, 0))
        else:
            self.logger_frame.pack_forget()

    def _on_tab_changed(self, event=None):
        if self._tab_lock:
            return
        try:
            idx = self.job_nb.index("current")
        except tk.TclError:
            return
        if idx != self.cur and 0 <= idx < len(self.jobs):
            self._switch_job(idx)

    def _switch_job(self, idx):
        job = self.jobs[self.cur]
        if self._auto_active and job["auto"] and self._params_changed(job):
            with self._Busy(self):
                self._handle_param_change(job)
        self._save_cur_state()
        self.cur = idx
        self._restore_state(self.jobs[idx]["state"])
        self._tab_lock = True
        try:
            self.job_nb.select(idx)
        finally:
            self._tab_lock = False
        self._relabel_tab()
        self._sync_ui_state()
        self._refresh_choice_dialog(None, reload=True)

    def _add_job(self):
        res = ask_fields(self, tr("Neuer Reiter"),
                         tr("Name der Klasse für den neuen Reiter. Die Einstellungen des aktuellen Reiters "
                            "werden als Vorlage kopiert (Wertungstag und Ordner danach anpassen)."),
                         [(tr("Klasse:"), "", None)])
        if not res or not res[0].strip():
            return
        self._save_cur_state()
        state = copy.deepcopy(self.jobs[self.cur]["state"])
        job = self._new_job(res[0].strip(), state)
        self.jobs.append(job)
        self._rebuild_tabs()
        self._switch_job(len(self.jobs) - 1)

    def _rename_job(self):
        job = self.jobs[self.cur]
        if job["auto"]:
            return
        res = ask_fields(self, tr("Reiter umbenennen"), tr("Neuer Name der Klasse:"),
                         [(tr("Klasse:"), job["name"], None)])
        if not res or not res[0].strip():
            return
        job["name"] = res[0].strip()
        self._relabel_tab()

    def _delete_job(self):
        if len(self.jobs) <= 1:
            return
        job = self.jobs[self.cur]
        if not messagebox.askyesno(tr("Reiter schließen"),
                                   tr("Reiter \"{n}\" schließen? Bereits geschriebene Reports und "
                                      "IGC-Kopien bleiben bestehen.", n=job["name"])):
            return
        del self.jobs[self.cur]
        self.cur = min(self.cur, len(self.jobs) - 1)
        self._restore_state(self.jobs[self.cur]["state"])
        self._rebuild_tabs()
        self._sync_ui_state()
        self._refresh_choice_dialog(None, reload=True)

    # --- Logger-Liste ---
    def _refresh_logger_tree(self):
        self.logger_tree.delete(*self.logger_tree.get_children())
        for lid, cls in sorted(self.multi["logger_map"].items()):
            self.logger_tree.insert("", "end", iid=lid, values=(lid, cls))

    def _logger_edit(self, new):
        lid, cls = "", ""
        if not new:
            sel = self.logger_tree.selection()
            if not sel:
                return
            lid, cls = sel[0], self.multi["logger_map"].get(sel[0], "")
        names = [j["name"] for j in self.jobs if j["name"]]
        res = ask_fields(self, tr("Logger-ID zuordnen"),
                         tr("Logger-ID (Flightrecorder-ID) und zugehörige Klasse."),
                         [(tr("Logger-ID:"), lid, None), (tr("Klasse:"), cls, names)])
        if not res or not res[0].strip() or not res[1].strip():
            return
        if not new and lid != res[0].strip().upper():
            self.multi["logger_map"].pop(lid, None)
        self.multi["logger_map"][res[0].strip().upper()] = res[1].strip()
        self._refresh_logger_tree()

    def _logger_delete(self):
        for iid in self.logger_tree.selection():
            self.multi["logger_map"].pop(iid, None)
        self._refresh_logger_tree()

    def _logger_clear(self):
        if self.multi["logger_map"] and messagebox.askyesno(
                tr("Liste leeren"), tr("Alle Zuordnungen der Logger-Liste löschen?")):
            self.multi["logger_map"].clear()
            self._refresh_logger_tree()

    @staticmethod
    def _read_logger_file(path):
        """CSV/TXT (Trenner ; , oder Tab) oder XLSX; erste zwei Spalten: Logger-ID, Klasse."""
        rows = []
        if path.lower().endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for r in wb.worksheets[0].iter_rows(values_only=True):
                rows.append([("" if c is None else str(c)) for c in r[:2]])
            wb.close()
        else:
            text = None
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    with open(path, "r", encoding=enc) as f:
                        text = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            for line in (text or "").splitlines():
                if line.strip():
                    rows.append(re.split(r"[;\t,]", line, maxsplit=1))
        pairs = []
        for i, r in enumerate(rows):
            if len(r) < 2:
                continue
            a, b = r[0].strip().strip('"'), r[1].strip().strip('"')
            if not a or not b:
                continue
            if i == 0 and b.lower() in ("klasse", "class", "wertungsklasse", "classe"):
                continue          # Kopfzeile
            pairs.append((a.upper(), b))
        return pairs

    def _logger_load_file(self):
        path = self._ask_file("dir_logger", title=tr("Logger-Liste wählen"),
                              filetypes=[(tr("Liste (CSV, TXT, Excel)"), "*.csv *.txt *.xlsx *.xlsm"),
                                         (tr("Alle Dateien"), "*.*")])
        if not path:
            return
        try:
            pairs = self._read_logger_file(path)
        except Exception as e:
            messagebox.showerror(tr("Fehler"), tr("Die Liste konnte nicht gelesen werden:\n{e}", e=e))
            return
        for lid, cls in pairs:
            self.multi["logger_map"][lid] = cls
        self._refresh_logger_tree()
        tabs = {j["name"].casefold() for j in self.jobs}
        missing = sorted({c for _l, c in pairs if c.casefold() not in tabs})
        msg = tr("{n} Zuordnungen geladen.", n=len(pairs))
        if missing:
            msg += "\n\n" + tr("Für diese Klassen gibt es noch keinen Reiter: {c}", c=", ".join(missing))
        messagebox.showinfo(tr("Logger-Liste"), msg)

    # --- Dateien den Reitern zuordnen ---
    @staticmethod
    def _date_key(s):
        nums = re.findall(r"\d+", s or "")
        if len(nums) < 3:
            return None
        d, m, y = int(nums[0]), int(nums[1]), int(nums[2])
        return (d, m, y + 2000 if y < 100 else y)

    def _header(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return {"mfr": "", "serial": "", "date_str": ""}
        key = (path, st.st_mtime, st.st_size)
        h = self._hdr_cache.get(key)
        if h is None:
            try:
                h = read_igc_header(path)
            except OSError:
                h = {"mfr": "", "serial": "", "date_str": ""}
            if len(self._hdr_cache) > 5000:
                self._hdr_cache.clear()
            self._hdr_cache[key] = h
        return h

    def _class_of(self, h):
        cands = {h.get("serial", "").upper(), (h.get("mfr", "") + h.get("serial", "")).upper()} - {""}
        for c in cands:
            if c in self.multi["logger_map"]:
                return self.multi["logger_map"][c]
        return None

    def _check_file(self, name, date_str, path):
        """Gehoert die Datei zu Klasse 'name' und Tag 'date_str'? -> (ok, code, info)"""
        if not self.multi["on"]:
            return True, None, None
        h = self._header(path)
        if self.multi["mode"] == "logger":
            cls = self._class_of(h)
            if cls is None:
                return False, "logger", (h.get("mfr", "") + h.get("serial", "")) or "?"
            if cls.casefold() != name.casefold():
                return False, "class", cls
        if self.multi["date_filter"] and self._date_key(h.get("date_str")) != self._date_key(date_str):
            return False, "date", h.get("date_str") or "?"
        return True, None, None

    def _job_files(self, name, date_str, src):
        return [f for f in self._list_igc(src)
                if self._check_file(name, date_str, os.path.join(src, f))[0]]

    def _scan_unassigned(self):
        """Dateien, die in keinem Reiter ausgewertet werden, melden (einmal je Datei/Grund)."""
        if not self.multi["on"]:
            self._unassigned = {}
            return
        groups = {}
        for job in self.jobs:
            st = self._job_state(job)
            src = str(st["src_var"]).strip()
            if src and os.path.isdir(src):
                groups.setdefault(os.path.normcase(os.path.abspath(src)), (src, []))[1].append(
                    (job["name"], str(st["date_var"]).strip()))
        new = {}
        for src, jobs_here in groups.values():
            try:
                files = self._list_igc(src)
            except OSError:
                continue
            for f in files:
                p = os.path.join(src, f)
                reasons, ok = [], False
                for name, date in jobs_here:
                    r = self._check_file(name, date, p)
                    if r[0]:
                        ok = True
                        break
                    reasons.append(r)
                if ok:
                    continue
                dates = [r for r in reasons if r[1] == "date"]
                lg = [r for r in reasons if r[1] == "logger"]
                if dates:
                    txt = tr("Flugdatum {d} passt zu keinem Reiter dieser Klasse", d=dates[0][2])
                elif lg:
                    txt = tr("Logger-ID {i} ist in der Logger-Liste nicht eingetragen", i=lg[0][2])
                else:
                    txt = tr("Klasse {c} hat keinen Reiter", c=reasons[0][2] if reasons else "?")
                new[(src, f)] = txt
        for k, v in new.items():
            if self._unassigned.get(k) != v:
                self._log(tr("[NICHT ZUGEORDNET] {fname}: {reason}", fname=k[1], reason=v))
        self._unassigned = new

    # ------------------------------------------------------------------
    # Auswertung (einmalig, alle neu berechnen, Auto-Auswertung)
    # ------------------------------------------------------------------
    AUTO_INTERVAL_S = 60       # Pruefintervall der Auto-Auswertung
    REPORT_RETRY_S = 10        # erneuter Schreibversuch bei gesperrtem Report
    YOUNG_FILE_S = 5           # Dateien juenger als 5 s gelten als evtl. noch im Kopiervorgang

    @staticmethod
    def _list_igc(src):
        return [f for f in sorted(os.listdir(src)) if f.lower().endswith(".igc")]

    @staticmethod
    def _sort_results(results):
        """Nach Kennung (Wettbewerbskennzeichen) sortieren, leere Kennung ans Ende."""
        def key(item):
            fname, r = item
            cid = (r.comp_id or "").strip()
            return (cid == "", cid.upper(), fname.lower())
        return dict(sorted(results.items(), key=key))

    @staticmethod
    def _file_sig(path):
        st = os.stat(path)
        return (st.st_mtime, st.st_size)

    class _Busy:
        def __init__(self, app):
            self.app = app

        def __enter__(self):
            self.prev = self.app._busy
            self.app._busy = True

        def __exit__(self, *a):
            self.app._busy = self.prev

    def _msg_prefix(self, job):
        return f"[{job['name']}] " if self.multi["on"] and job["name"] else ""

    def _prepare_run(self, job, ask_no_zones=True):
        """Eingaben pruefen. Gibt (src, dst, task) zurueck oder None."""
        st = self._job_state(job)
        pre = self._msg_prefix(job)
        src = str(st["src_var"]).strip()
        dst = str(st["dst_var"]).strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror(tr("Fehler"), pre + tr("Bitte einen gültigen Quellordner wählen."))
            return None
        if not dst:
            messagebox.showerror(tr("Fehler"), pre + tr("Bitte einen Zielordner wählen."))
            return None
        try:
            os.makedirs(dst, exist_ok=True)
        except OSError as e:
            messagebox.showerror(tr("Fehler"), pre + str(e))
            return None
        self._store_settings()
        try:
            task = self._task_from_state(st)
        except (ValueError, KeyError):
            messagebox.showerror(tr("Fehler"), pre + tr("Bitte alle Zahlenfelder prüfen (Radius, Geschwindigkeit, ...)."))
            return None
        if not task.zones and ask_no_zones:
            if not messagebox.askyesno(tr("Keine Streckenpunkte"),
                                       pre + tr("Es sind keine Streckenpunkte definiert - Ziel/Höhendifferenz kann dann "
                                                "nicht geprüft werden. Trotzdem fortfahren?")):
                return None
        return src, dst, task

    def _evaluate_file(self, fname, src, dst, task, forced=None):
        """Eine IGC-Datei auswerten, Kopie schreiben, ins Protokoll eintragen."""
        flight = parse_igc(os.path.join(src, fname))
        if forced is not None and forced not in {o.key for o in list_start_options(flight, task)}:
            self._log(tr("  {fname}: der manuell gewählte Start ist nicht mehr möglich - "
                         "automatische Wertung wird verwendet", fname=fname))
            forced = None
        result = evaluate_pilot(flight, task, forced)
        out_name = os.path.splitext(fname)[0] + "_cyl.igc"
        write_output_igc(flight, result.start, task, os.path.join(dst, out_name))
        sev = result.worst_sev
        status = {3: tr("STRAFE/PRÜFEN"), 2: tr("PRÜFEN"), 1: tr("OK (Hinweis)"), 0: "OK"}[sev]
        if not result.start.valid or not result.speed_valid:
            status = tr("UNGÜLTIG")
        if result.date_mismatch:
            status = tr("DATUM!")
            self._log(tr("  !!! {fname}: Dateidatum ({d1}) passt nicht zum Wertungstag ({d2}) !!!",
                         fname=fname, d1=result.flight_date, d2=task.date_str))
        self._log(tr("[{status}] {fname}: {pilot} - Start {t} UTC ({method})",
                     status=status, fname=fname, pilot=result.pilot or tr("(ohne Namen)"),
                     t=seconds_to_hms(result.start.time_s),
                     method=method_label(result.start.method)))
        for n in result.notes:
            if n.sev >= 2:
                self._log(f"      - {n.text}")
        return flight, result

    def _job_header_line(self, job, task):
        if self.multi["on"]:
            self._log(tr("=== Klasse {c} - Wertungstag {d} ===", c=job["name"], d=task.date_str))

    def _evaluate_all(self, job, initial, auto_start=False, clear_log=True):
        """Alle IGC-Dateien des Quellordners (neu) auswerten. initial=True: Log leeren und
        ggf. nach Streckenpunkten fragen. Manuell gewaehlte Starts werden einzeln abgefragt
        (Ja / Nein / Alle ja / Alle nein / Abbrechen). Gibt True bei Erfolg zurueck."""
        prep = self._prepare_run(job, ask_no_zones=initial)
        if not prep:
            return False
        src, dst, task = prep
        label = job["name"] if self.multi["on"] else ""
        try:
            files = self._job_files(job["name"], task.date_str, src) if self.multi["on"] \
                else self._list_igc(src)
        except OSError as e:
            messagebox.showerror(tr("Fehler"), str(e))
            return False
        if not files and not auto_start:
            messagebox.showwarning(tr("Keine Dateien"),
                                   self._msg_prefix(job) + tr("Im Quellordner wurden keine passenden .igc-Dateien gefunden."))
            return False

        # manuell gewaehlte Starts einzeln abfragen
        old = job["run"]["results"] if job["run"] else {}
        keep = {}
        decision = None
        for fname, r in old.items():
            if not (r.start.manual and fname in files):
                continue
            if decision is None:
                ans = ask_choice(
                    self, tr("Manuell gewählter Start"),
                    self._msg_prefix(job) +
                    tr("Für {pilot} ({fname}) wurde der Start manuell gewählt: {method} um {t} UTC.\n\n"
                       "Diese Wahl bei der Neuberechnung beibehalten?",
                       pilot=r.pilot or tr("(ohne Namen)"), fname=fname,
                       method=method_label(r.start.method), t=seconds_to_hms(r.start.time_s)),
                    [("yes", tr("Ja")), ("no", tr("Nein")), ("all_yes", tr("Alle ja")),
                     ("all_no", tr("Alle nein")), ("cancel", tr("Abbrechen"))], "cancel")
                if ans == "cancel":
                    return False
                if ans in ("all_yes", "all_no"):
                    decision = ans
                    ans = "yes" if ans == "all_yes" else "no"
            else:
                ans = "yes" if decision == "all_yes" else "no"
            if ans == "yes":
                keep[fname] = (r.start.method, r.start.time_s)

        # gespeicherte manuelle Startwahlen (optional) fuer Dateien ohne Eintrag im Speicher
        if self.multi["persist_manual"]:
            for fname, key in self._load_manual(label, task, dst, src).items():
                if fname in files and fname not in old and fname not in keep:
                    keep[fname] = key
                    self._log(tr("  {fname}: gespeicherte manuelle Startwahl wird übernommen", fname=fname))

        if initial and clear_log:
            self.log.delete("1.0", "end")
        elif not initial:
            self._log("\n" + tr("--- Alle Piloten werden neu berechnet ---"))
        self._job_header_line(job, task)
        self._log(tr("{n} IGC-Dateien gefunden. Starte Auswertung...", n=len(files)))

        results, flights, processed = {}, {}, {}
        for fname in files:
            try:
                sig = self._file_sig(os.path.join(src, fname))
                flight, result = self._evaluate_file(fname, src, dst, task, keep.get(fname))
                results[fname] = result
                flights[fname] = flight
                processed[fname] = sig
            except Exception as e:
                self._log(tr("[FEHLER] {fname}: {e}", fname=fname, e=e))
                self._log(traceback.format_exc())
            self.update_idletasks()

        job["run"] = {"task": task, "src": src, "dst": dst, "flights": flights, "label": label,
                      "results": self._sort_results(results), "processed": processed,
                      "summary": self._build_task_summary(task, label), "report_path": None}
        if results:
            self._try_write_report(job)
        self._save_manual(job)
        self._scan_unassigned()
        self._sync_ui_state()
        if job is self.jobs[self.cur]:
            self._refresh_choice_dialog()
        return True

    # --- gespeicherte manuelle Startwahlen (optional) ---
    def _manual_file(self, label, task, dst):
        return self._report_file(label, task, dst, "_manuell.json" if get_lang() == "de" else "_manual.json")

    def _save_manual(self, job):
        rd = job["run"]
        if not rd or not self.multi["persist_manual"]:
            return
        data = {}
        for f, r in rd["results"].items():
            if r.start.manual:
                sig = rd["processed"].get(f)
                data[f] = {"method": r.start.method, "time_s": r.start.time_s,
                           "sig": list(sig) if sig else None}
        try:
            with open(self._manual_file(rd["label"], rd["task"], rd["dst"]), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def _load_manual(self, label, task, dst, src):
        path = self._manual_file(label, task, dst)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        out = {}
        for f, d in data.items():
            try:
                sig = self._file_sig(os.path.join(src, f))
                if d.get("sig") and abs(d["sig"][0] - sig[0]) < 1e-3 and int(d["sig"][1]) == sig[1]:
                    out[f] = (d["method"], d["time_s"])
            except (OSError, KeyError, TypeError, ValueError, IndexError):
                continue
        return out

    def _run(self):
        job = self.jobs[self.cur]
        if self._auto_active and job["auto"]:
            return
        with self._Busy(self):
            if not self._evaluate_all(job, initial=True):
                return
            rd = job["run"]
            if self._auto_active:          # neuer Reiter waehrend laufender Auto-Auswertung
                job["auto"] = True
                job["snapshot"] = self._param_state()
                self._sync_ui_state()
            if not rd["results"]:
                return
            self._log("\n" + tr("Fertig. Report: {p}", p=self._report_path(job)))
            self._log(tr("Hinweis: Über \"Andere Abflüge wählen...\" lassen sich einzelne Starts "
                         "manuell ändern (z. B. anderer PEV oder Ausflug)."))
            messagebox.showinfo(tr("Fertig"), tr("{n} Piloten ausgewertet.\nReport: {p}",
                                                 n=len(rd["results"]), p=self._report_path(job)))

    def _recalc_clicked(self):
        """Button 'Alle neu berechnen' (aktueller Reiter)."""
        job = self.jobs[self.cur]
        if not job["run"]:
            return
        with self._Busy(self):
            if self._evaluate_all(job, initial=False):
                if self._auto_active and job["auto"]:
                    job["snapshot"] = self._param_state()
                    self._auto_next = time.time() + self.AUTO_INTERVAL_S
                self._log(tr("Neuberechnung abgeschlossen: {n} Piloten.", n=len(job["run"]["results"])))

    # ------------------------------------------------------------------
    # Auto-Auswertung (alle Reiter)
    # ------------------------------------------------------------------
    def _global_state(self):
        m = self.multi
        return {"on": m["on"], "mode": m["mode"], "date_filter": m["date_filter"],
                "map": dict(m["logger_map"])}

    def _auto_toggle(self):
        with self._Busy(self):
            if self._auto_active:
                self._auto_active = False
                for j in self.jobs:
                    j["auto"] = False
                    j["snapshot"] = None
                self._auto_global = None
                self._log(tr("Auto-Auswertung beendet."))
                self._sync_ui_state()
                return
            first = True
            for job in self.jobs:
                if not self._evaluate_all(job, initial=True, auto_start=True, clear_log=first):
                    return
                first = False
            self._auto_active = True
            for job in self.jobs:
                job["auto"] = True
                job["snapshot"] = self._job_state(job)
            self._auto_global = self._global_state()
            self._auto_next = time.time() + self.AUTO_INTERVAL_S
            self._log("\n" + tr("Auto-Auswertung aktiv: der Quellordner wird alle {s} s auf neue "
                                "IGC-Dateien geprüft.", s=self.AUTO_INTERVAL_S))
            self._sync_ui_state()

    def _auto_cycle(self, job):
        """Quellordner pruefen und nur neue/geaenderte Dateien auswerten.
        Gibt True zurueck, wenn Dateien noch zu frisch waren (bald erneut pruefen)."""
        rd = job["run"]
        src, dst, task = rd["src"], rd["dst"], rd["task"]
        try:
            files = self._job_files(job["name"], task.date_str, src) if self.multi["on"] \
                else self._list_igc(src)
        except OSError as e:
            self._log(tr("[FEHLER] Quellordner nicht lesbar: {e}", e=e))
            return False
        now = time.time()
        young = False
        todo = []
        for fname in files:
            try:
                sig = self._file_sig(os.path.join(src, fname))
            except OSError:
                continue
            if rd["processed"].get(fname) == sig:
                continue
            if now - sig[0] < self.YOUNG_FILE_S:
                young = True
                continue
            todo.append((fname, sig))
        if not todo:
            return young
        self._log("\n" + tr("Auto-Auswertung: {n} neue/geänderte Datei(en) gefunden.", n=len(todo)))
        self._job_header_line(job, task)
        changed = []
        for fname, sig in todo:
            replaced = fname in rd["results"]
            try:
                flight, result = self._evaluate_file(fname, src, dst, task)
                if replaced and rd["results"][fname].start.manual:
                    self._log(tr("  {fname}: Datei wurde geändert - manuell gewählter Start zurückgesetzt",
                                 fname=fname))
                rd["results"][fname] = result
                rd["flights"][fname] = flight
                changed.append(fname)
            except Exception as e:
                self._log(tr("[FEHLER] {fname}: {e}", fname=fname, e=e))
            rd["processed"][fname] = sig      # auch bei Fehler merken (kein Log-Spam jede Minute)
            self.update_idletasks()
        if changed:
            rd["results"] = self._sort_results(rd["results"])
            self._try_write_report(job)
            self._save_manual(job)
            if job is self.jobs[self.cur]:
                self._refresh_choice_dialog(changed)
        self._sync_ui_state()
        return young

    # --- Parameter-Schutz waehrend die Auto-Auswertung laeuft ---
    def _params_changed(self, job):
        snap = job["snapshot"]
        if snap is None:
            return False
        cur = self._param_state()
        for k, v in snap.items():
            if k == "zones_objs":
                if [asdict(z) for z in v] != [asdict(z) for z in cur[k]]:
                    return True
            elif cur.get(k) != v:
                return True
        return False

    def _entry_has_focus(self):
        try:
            w = self.focus_get()
        except Exception:
            return False
        return isinstance(w, (tk.Entry, ttk.Entry))

    def _handle_param_change(self, job):
        ans = ask_choice(
            self, tr("Parameter geändert"),
            self._msg_prefix(job) +
            tr("Die Parameter wurden geändert, während die Auto-Auswertung läuft.\n\n"
               "Alle Piloten mit den neuen Werten neu berechnen oder die Änderungen verwerfen? "
               "(Ohne Neuberechnung sind Änderungen nicht möglich.)"),
            [("recalc", tr("Alle neu berechnen")), ("discard", tr("Änderungen verwerfen"))], "discard")
        if ans == "recalc" and self._evaluate_all(job, initial=False):
            job["snapshot"] = self._param_state()
            self._auto_next = time.time() + self.AUTO_INTERVAL_S
            self._log(tr("Neuberechnung abgeschlossen: {n} Piloten.", n=len(job["run"]["results"])))
            return
        self._restore_state(job["snapshot"])
        self._log(tr("Parameteränderungen verworfen."))

    def _global_changed(self):
        return self._auto_global is not None and self._auto_global != self._global_state()

    def _handle_global_change(self):
        ans = ask_choice(
            self, tr("Zuordnung geändert"),
            tr("Die Zuordnung der Dateien zu den Klassen (Unterscheidung, Logger-Liste oder Datumsfilter) "
               "wurde geändert, während die Auto-Auswertung läuft.\n\n"
               "Alle Reiter mit der neuen Zuordnung neu berechnen oder die Änderungen verwerfen?"),
            [("recalc", tr("Alle neu berechnen")), ("discard", tr("Änderungen verwerfen"))], "discard")
        if ans == "recalc":
            ok = True
            for job in self.jobs:
                if job["auto"] and not self._evaluate_all(job, initial=False):
                    ok = False
                    break
            if ok:
                self._auto_global = self._global_state()
                self._auto_next = time.time() + self.AUTO_INTERVAL_S
                self._log(tr("Neuberechnung abgeschlossen."))
                return
        g = self._auto_global
        self.multi.update({"mode": g["mode"], "date_filter": g["date_filter"], "logger_map": dict(g["map"])})
        self._apply_multi_to_ui()
        self._log(tr("Parameteränderungen verworfen."))

    # --- Timer ---
    def _tick(self):
        try:
            if not self._busy:
                self._busy = True
                try:
                    self._tick_inner()
                finally:
                    self._busy = False
        except Exception:
            try:
                self._log(traceback.format_exc())
            except Exception:
                pass
        self.after(1000, self._tick)

    def _tick_inner(self):
        now = time.time()
        for job in self.jobs:
            if job["report_pending"] and now - job["last_report_try"] >= self.REPORT_RETRY_S:
                self._retry_report(job)
        if self._auto_active:
            cur = self.jobs[self.cur]
            if cur["auto"] and self._params_changed(cur) and not self._entry_has_focus():
                self._handle_param_change(cur)
            if self._global_changed() and not self._entry_has_focus():
                self._handle_global_change()
            if now >= self._auto_next:
                young = False
                for job in self.jobs:
                    if job["auto"] and job["run"]:
                        young = self._auto_cycle(job) or young
                self._scan_unassigned()
                self._auto_next = time.time() + (self.YOUNG_FILE_S + 1 if young else self.AUTO_INTERVAL_S)
        self._update_status()

    def _update_status(self):
        if self._auto_active:
            left = max(int(self._auto_next - time.time()), 0)
            n = sum(len(j["run"]["results"]) for j in self.jobs if j["auto"] and j["run"])
            txt = tr("AUTO-AUSWERTUNG AKTIV - nächste Prüfung in {s} s - {n} Piloten", s=left, n=n)
            if self._unassigned:
                txt += tr(" - {k} nicht zugeordnet", k=len(self._unassigned))
            self.lbl_auto.config(text=txt, fg="#1E7B34")
        else:
            self.lbl_auto.config(text="")

    def _sync_ui_state(self):
        job = self.jobs[self.cur]
        rd = job["run"]
        running_here = self._auto_active and job["auto"]
        self.btn_start.config(state="disabled" if running_here else "normal")
        self.btn_auto.config(text=tr("Auto-Auswertung stoppen") if self._auto_active
                             else tr("Auto-Auswertung starten"))
        self.btn_recalc.config(state="normal" if rd else "disabled")
        self.btn_choose.config(state="normal" if (rd and rd["results"]) else "disabled")
        rp = rd.get("report_path") if rd else None
        self.btn_report.config(state="normal" if (rp and os.path.isfile(rp)) else "disabled")
        self.chk_multi.config(state="disabled" if self._auto_active else "normal")
        self.btn_rename.config(state="disabled" if job["auto"] else "normal")
        self.btn_close_tab.config(state="normal" if len(self.jobs) > 1 else "disabled")
        self._sync_banner()
        self._update_status()

    # --- Report ---
    def _build_task_summary(self, task, label=""):
        """Kopfzeilen des Reports: Wertungstag (Zeile 2), dann nebeneinander in Zeile 3."""
        s = {
            tr("Wertungstag"): task.date_str,
            tr("Toröffnung (Ortszeit)"): task.gate_open_local,
            tr("Max. GS"): f"{task.max_groundspeed_kmh:.0f} km/h",
            tr("Max. LoH"): f"{task.max_loss_of_height_m:.0f} m",
            tr("PEV-Mindestintervall"): f"{task.min_pev_interval_s // 60} min",
        }
        if label:
            s[tr("Klasse")] = label
        return s

    @staticmethod
    def _report_file(label, task, dst, ext=".xlsx"):
        day = re.sub(r"\D", "", task.date_str or "")
        parts = [tr("Zylinderabflug_Report")]
        if label:
            parts.append(re.sub(r"[^\w\-]+", "_", label).strip("_"))
        if day:
            parts.append(day)
        return os.path.join(dst, "_".join(p for p in parts if p) + ext)

    def _report_path(self, job=None):
        job = job or self.jobs[self.cur]
        rd = job["run"]
        return self._report_file(rd["label"], rd["task"], rd["dst"])

    def _write_report(self, job):
        rd = job["run"]
        path = self._report_path(job)
        write_report_xlsx(list(rd["results"].values()), path, rd["summary"])
        rd["report_path"] = path
        return path

    def _try_write_report(self, job=None):
        """Report schreiben; ist die Datei gesperrt (z. B. in Excel offen), wird ein rotes
        Banner angezeigt und es wird automatisch erneut versucht."""
        job = job or self.jobs[self.cur]
        try:
            path = self._write_report(job)
        except OSError as e:
            if not job["report_pending"]:
                self._log(self._msg_prefix(job) + tr("[FEHLER] Report konnte nicht geschrieben werden: {e}", e=e))
            job["report_pending"] = True
            job["report_error"] = str(e)
            job["last_report_try"] = time.time()
            self._sync_ui_state()
            return False
        if job["report_pending"]:
            self._log(tr("Report wurde aktualisiert: {p}", p=path))
        job["report_pending"] = False
        self._sync_ui_state()
        return True

    def _retry_report(self, job=None):
        jobs = [job] if job is not None else [j for j in self.jobs if j["report_pending"]]
        for j in jobs:
            j["last_report_try"] = time.time()
            if j["run"] and j["run"]["results"]:
                self._try_write_report(j)

    def _sync_banner(self):
        pend = [j for j in self.jobs if j["report_pending"] and j["run"]]
        if pend:
            names = ", ".join(os.path.basename(self._report_path(j)) for j in pend)
            self.banner_lbl.config(text=tr(
                "REPORT GESPERRT: {f} kann nicht geschrieben werden (vermutlich in Excel geöffnet). "
                "Bitte die Datei schließen - es wird automatisch erneut versucht. "
                "Die IGC-Kopien und die Tool-Liste sind bereits aktuell.", f=names))
            if not self.banner.winfo_ismapped():
                self.banner.pack(side="top", fill="x", before=self._mid)
        else:
            self.banner.pack_forget()

    def _open_report(self):
        """Report mit dem Standardprogramm (Excel) oeffnen."""
        path = (self._run_data or {}).get("report_path")
        if not path or not os.path.isfile(path):
            messagebox.showwarning(tr("Hinweis"), tr("Es gibt noch keinen Report - bitte zuerst die Auswertung starten."))
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror(tr("Fehler"), tr("Der Report konnte nicht geöffnet werden:\n{e}", e=e))

    # --- Manuelle Startwahl ---
    def _open_choice(self):
        if not self._run_data:
            return
        if self._choice_dlg is not None and self._choice_dlg.winfo_exists():
            self._choice_dlg.lift()
            self._choice_dlg.focus_set()
            return
        self._choice_dlg = StartChoiceDialog(self)

    def _refresh_choice_dialog(self, changed=None, reload=False):
        dlg = self._choice_dlg
        if dlg is not None and dlg.winfo_exists():
            if reload:
                dlg.reload_job()
            else:
                dlg.refresh(changed)

    def _apply_start_choice(self, fname, key):
        """Wertet einen Piloten mit manuell gewaehltem Start (key) bzw. automatisch (None)
        neu aus, schreibt die IGC-Kopie und den Report neu. Gibt True bei Erfolg zurueck."""
        job = self.jobs[self.cur]
        rd = job["run"]
        task, flight = rd["task"], rd["flights"][fname]
        with self._Busy(self):
            try:
                result = evaluate_pilot(flight, task, forced=key)
                out_name = os.path.splitext(fname)[0] + "_cyl.igc"
                write_output_igc(flight, result.start, task, os.path.join(rd["dst"], out_name))
            except Exception as e:
                messagebox.showerror(tr("Fehler"), tr("[FEHLER] {fname}: {e}", fname=fname, e=e))
                return False
            rd["results"][fname] = result
            if key is None:
                self._log(tr("Start von {pilot} ({fname}) auf automatische Wertung zurückgesetzt: {t} UTC ({method})",
                             pilot=result.pilot or tr("(ohne Namen)"), fname=fname,
                             t=seconds_to_hms(result.start.time_s), method=method_label(result.start.method)))
            else:
                self._log(tr("Start von {pilot} ({fname}) manuell geändert: {t} UTC ({method})",
                             pilot=result.pilot or tr("(ohne Namen)"), fname=fname,
                             t=seconds_to_hms(result.start.time_s), method=method_label(result.start.method)))
            self._try_write_report(job)      # bei gesperrtem Report: Banner + automatischer Neuversuch
            self._save_manual(job)
            return True


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
