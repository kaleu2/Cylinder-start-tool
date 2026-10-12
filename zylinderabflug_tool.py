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

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import asdict

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from zylinder_core import (
    TaskParams, Zone, parse_igc, evaluate_pilot, write_output_igc, seconds_to_hms, method_label,
    list_start_options,
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


class StartChoiceDialog(tk.Toplevel):
    """Manuelle Auswahl eines anderen Starts je Pilot (nach der Auswertung).
    Zeigt alle PEVs im Startzylinder plus den Ausflug nach dem letzten gueltigen PEV,
    jeweils mit Hinweistext, warum der Start eigentlich nicht zaehlt."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(tr("Andere Abflüge wählen"))
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
    def _fill_pilots(self, keep=None):
        self.tree_p.delete(*self.tree_p.get_children())
        for fname, res in self.app._run_data["results"].items():
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
        self._run_data = None       # Ergebnisse des letzten Laufs (fuer manuelle Startwahl)
        self._choice_dlg = None
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
        keep = {"date": self.date_var.get(), "gate": self.gate_open_var.get(),
                "log": self.log.get("1.0", "end-1c")}
        self._store_settings()
        self.settings["lang"] = code
        save_settings(self.settings)
        set_lang(code)
        for child in self.winfo_children():
            child.destroy()
        self.title(tr("Zylinderabflug-Auswertetool (Annex A 7.4.4)"))
        self._build_ui()
        self._load_stored_cup()
        self._restore_settings()
        self.date_var.set(keep["date"])
        self.gate_open_var.set(keep["gate"])
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

        # --- Parameter speichern/laden + Start ---
        frm_actions = ttk.Frame(self)
        frm_actions.pack(side="bottom", fill="x", **pad)
        ttk.Button(frm_actions, text=tr("Parameter laden..."), command=self._load_params).pack(side="left", padx=4)
        ttk.Button(frm_actions, text=tr("Parameter speichern..."), command=self._save_params).pack(side="left", padx=4)
        ttk.Button(frm_actions, text=tr("Auswertung starten"), command=self._run).pack(side="right", padx=4)
        self.btn_choose = ttk.Button(frm_actions, text=tr("Andere Abflüge wählen..."),
                                     command=self._open_choice,
                                     state="normal" if self._run_data else "disabled")
        self.btn_choose.pack(side="right", padx=4)
        self.btn_report = ttk.Button(frm_actions, text=tr("Report öffnen"),
                                     command=self._open_report,
                                     state="normal" if self._run_data else "disabled")
        self.btn_report.pack(side="right", padx=4)

        # --- Scrollbarer Hauptbereich (Scrollbalken rechts, Mausrad) ---
        mid = ttk.Frame(self)
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

        # --- Start-Zylinder ---
        frm_start = ttk.LabelFrame(self.body, text=tr("Start-Zylinder (Task Sheet)"))
        frm_start.pack(fill="x", **pad)

        self.start_lat_var = tk.StringVar()
        self.start_lon_var = tk.StringVar()
        self.start_radius_var = tk.StringVar(value="10000")
        self.gate_open_var = tk.StringVar(value=self.GATE_DEFAULT)
        self.tz_var = tk.StringVar(value="2.0")
        self.date_var = tk.StringVar(value=datetime.date.today().strftime("%d.%m.%Y"))

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

    def _store_settings(self):
        values = {key: getattr(self, attr).get() for key, attr in self._STR_VARS}
        values["cal_on"] = bool(self.cal_on_var.get())
        values["zones"] = [asdict(z) for z in self.zones]
        self.settings["values"] = values
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
        return TaskParams(
            start_lat=float(self.start_lat_var.get().replace(",", ".")),
            start_lon=float(self.start_lon_var.get().replace(",", ".")),
            start_radius_m=float(self.start_radius_var.get().replace(",", ".")),
            gate_open_local=self.gate_open_var.get().strip(),
            tz_offset_h=float(self.tz_var.get().replace(",", ".")),
            date_str=self.date_var.get().strip(),
            min_pev_interval_s=int(float(self.pev_interval_var.get().replace(",", ".")) * 60),
            pev_cluster_s=int(float(self.pev_cluster_var.get().replace(",", "."))),
            tolerance_m=float(self.tolerance_var.get().replace(",", ".")),
            tolerance_penalty_pts=float(self.tolerance_pts_var.get().replace(",", ".")),
            max_groundspeed_kmh=float(self.max_gsp_var.get().replace(",", ".")),
            max_loss_of_height_m=float(self.max_loh_var.get().replace(",", ".")),
            loh_m_per_point=float(self.loh_per_pt_var.get().replace(",", ".")),
            ref_elevation_m=(float(self.ref_elev_var.get().replace(",", "."))
                             if self.cal_on_var.get() else None),
            baro_cal_fixes=int(float(self.cal_n_var.get().replace(",", ".") or "60")),
            task_time_str=self.task_time_var.get().strip(),
            zones=list(self.zones),
        )

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
    def _run(self):
        src = self.src_var.get().strip()
        dst = self.dst_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror(tr("Fehler"), tr("Bitte einen gültigen Quellordner wählen."))
            return
        if not dst:
            messagebox.showerror(tr("Fehler"), tr("Bitte einen Zielordner wählen."))
            return
        os.makedirs(dst, exist_ok=True)
        self._store_settings()

        try:
            task = self._collect_task()
        except ValueError:
            messagebox.showerror(tr("Fehler"), tr("Bitte alle Zahlenfelder prüfen (Radius, Geschwindigkeit, ...)."))
            return
        if not task.zones:
            if not messagebox.askyesno(tr("Keine Streckenpunkte"),
                                       tr("Es sind keine Streckenpunkte definiert - Ziel/Höhendifferenz kann dann "
                                          "nicht geprüft werden. Trotzdem fortfahren?")):
                return

        igc_files = [f for f in sorted(os.listdir(src)) if f.lower().endswith(".igc")]
        if not igc_files:
            messagebox.showwarning(tr("Keine Dateien"), tr("Im Quellordner wurden keine .igc-Dateien gefunden."))
            return

        self.log.delete("1.0", "end")
        self._log(tr("{n} IGC-Dateien gefunden. Starte Auswertung...", n=len(igc_files)))

        results = {}
        flights = {}
        for fname in igc_files:
            path = os.path.join(src, fname)
            try:
                flight = parse_igc(path)
                result = evaluate_pilot(flight, task)
                results[fname] = result
                flights[fname] = flight
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
            except Exception as e:
                self._log(tr("[FEHLER] {fname}: {e}", fname=fname, e=e))
                self._log(traceback.format_exc())

        self._run_data = {"task": task, "flights": flights, "results": results,
                          "dst": dst, "summary": self._build_task_summary(task)}
        try:
            report_path = self._write_report()
        except OSError as e:
            self._log(tr("[FEHLER] Report konnte nicht geschrieben werden: {e}", e=e))
            messagebox.showerror(tr("Fehler"), tr(
                "Der Report konnte nicht geschrieben werden (ist die Datei in Excel geöffnet?):\n{e}", e=e))
            return
        self.btn_choose.config(state="normal" if results else "disabled")
        self.btn_report.config(state="normal")
        self._log("\n" + tr("Fertig. Report: {p}", p=report_path))
        if results:
            self._log(tr("Hinweis: Über \"Andere Abflüge wählen...\" lassen sich einzelne Starts "
                         "manuell ändern (z. B. anderer PEV oder Ausflug)."))
        messagebox.showinfo(tr("Fertig"), tr("{n} Piloten ausgewertet.\nReport: {p}", n=len(results), p=report_path))

    # ------------------------------------------------------------------
    def _build_task_summary(self, task):
        """Kopfzeilen des Reports: Wertungstag (Zeile 2), dann nebeneinander in Zeile 3."""
        return {
            tr("Wertungstag"): task.date_str,
            tr("Toröffnung (Ortszeit)"): task.gate_open_local,
            tr("Max. GS"): f"{task.max_groundspeed_kmh:.0f} km/h",
            tr("Max. LoH"): f"{task.max_loss_of_height_m:.0f} m",
            tr("PEV-Mindestintervall"): f"{task.min_pev_interval_s // 60} min",
        }

    def _write_report(self):
        rd = self._run_data
        report_path = os.path.join(rd["dst"], tr("Zylinderabflug_Report.xlsx"))
        write_report_xlsx(list(rd["results"].values()), report_path, rd["summary"])
        rd["report_path"] = report_path
        return report_path

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

    def _open_choice(self):
        if not self._run_data:
            return
        if self._choice_dlg is not None and self._choice_dlg.winfo_exists():
            self._choice_dlg.lift()
            self._choice_dlg.focus_set()
            return
        self._choice_dlg = StartChoiceDialog(self)

    def _apply_start_choice(self, fname, key):
        """Wertet einen Piloten mit manuell gewaehltem Start (key) bzw. automatisch (None)
        neu aus, schreibt die IGC-Kopie und den Report neu. Gibt True bei Erfolg zurueck."""
        rd = self._run_data
        task, flight = rd["task"], rd["flights"][fname]
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
        try:
            self._write_report()
        except OSError as e:
            messagebox.showerror(tr("Fehler"), tr(
                "Der Report konnte nicht geschrieben werden (ist die Datei in Excel geöffnet?):\n{e}\n"
                "Die IGC-Kopie wurde aktualisiert. Bitte die Datei schließen und den Start erneut übernehmen.", e=e))
            return False
        return True


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
