# =========================
# PAYMENT TRACKER — BASELINE STABLE + STEP A.1
# DATE FORMAT: MM-DD-YYYY
# =========================

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Optional, List, Tuple, Dict

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# =========================
# CONFIG
# =========================
DATE_FMT = "%m-%d-%Y"   # ✅ STEP A.1 CHANGE

FREQ_MAP_DAYS = {
    "Weekly": 7,
    "Biweekly": 14,
    "Monthly (Same Day)": 30,
}

BASE_DIR = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "Payment Tracker",
    "Companies"
)

# =========================
# UTILS
# =========================
def today_str() -> str:
    return datetime.now().strftime(DATE_FMT)

def parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip(), DATE_FMT)

def money(v: str) -> float:
    if v is None:
        return 0.0
    s = str(v).replace("$", "").replace(",", "").strip()
    if s == "":
        return 0.0
    return float(s)

def fmt2(x: float) -> str:
    return f"{float(x):.2f}"

def calc_next_month_same_day(dt: datetime) -> datetime:
    m = dt.month + 1
    y = dt.year
    if m > 12:
        m = 1
        y += 1
    d = dt.day
    last = monthrange(y, m)[1]
    return datetime(y, m, min(d, last))

def clear_tree(tree: ttk.Treeview):
    for i in tree.get_children():
        tree.delete(i)

def get_selected_tree_id(tree: ttk.Treeview, id_index: int = 0) -> Optional[int]:
    sel = tree.selection()
    if not sel:
        return None
    vals = tree.item(sel[0]).get("values", [])
    if not vals:
        return None
    return int(vals[id_index])

