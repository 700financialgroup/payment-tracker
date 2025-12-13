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
DATE_FMT = "%Y-%m-%d"

FREQ_MAP_DAYS = {
    "Weekly": 7,
    "Biweekly": 14,
    "Monthly (Same Day)": 30,  # monthly uses month logic below
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


# =========================
# APP STATE
# =========================
@dataclass
class AppState:
    db_path: str


# =========================
# DB CORE
# =========================
def db_connect(db_path: str):
    return sqlite3.connect(db_path)


def init_db(db_path: str):
    conn = db_connect(db_path)
    cur = conn.cursor()

    # Customers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            created_at TEXT
        )
    """)

    # Families
    cur.execute("""
        CREATE TABLE IF NOT EXISTS families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_name TEXT NOT NULL,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS family_members (
            family_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            PRIMARY KEY (family_id, customer_id),
            FOREIGN KEY (family_id) REFERENCES families(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)

    # Plans (multiple per customer)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            plan_name TEXT,
            plan_total REAL NOT NULL,
            deposit_amount REAL NOT NULL DEFAULT 0,
            deposit_date TEXT NOT NULL,
            frequency TEXT NOT NULL,
            recurring_amount REAL NOT NULL,
            first_due_date TEXT NOT NULL,
            created_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)

    # Dues
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            due_date TEXT NOT NULL,
            amount_due REAL NOT NULL,
            paid_amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Due', -- Due / Paid
            paid_date TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
    """)

    # Payments (raw payments)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payer_type TEXT NOT NULL, -- 'Customer' or 'Family'
            payer_id INTEGER NOT NULL,
            payment_date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT
        )
    """)

    # Allocations (how a payment got applied)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER NOT NULL,
            due_id INTEGER NOT NULL,
            applied_amount REAL NOT NULL,
            FOREIGN KEY (payment_id) REFERENCES payments(id),
            FOREIGN KEY (due_id) REFERENCES dues(id)
        )
    """)

    # Settings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


def set_setting(db_path: str, key: str, value: str):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))
    conn.commit()
    conn.close()


def get_setting(db_path: str, key: str, default: str) -> str:
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default


# =========================
# CUSTOMERS
# =========================
def add_customer(db_path: str, name: str, phone: str, email: str) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Customer name is required.")
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO customers (name, phone, email, created_at)
        VALUES (?, ?, ?, ?)
    """, (name, (phone or "").strip(), (email or "").strip(), today_str()))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def search_customers(db_path: str, term: str):
    t = f"%{(term or '').strip()}%"
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, phone, email
        FROM customers
        WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?
        ORDER BY name
    """, (t, t, t))
    rows = cur.fetchall()
    conn.close()
    return rows


# =========================
# FAMILIES (optional)
# =========================
def create_family(db_path: str, family_name: str) -> int:
    fn = (family_name or "").strip()
    if not fn:
        raise ValueError("Family name is required.")
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO families (family_name, created_at)
        VALUES (?, ?)
    """, (fn, today_str()))
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def list_families(db_path: str):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, family_name FROM families ORDER BY family_name")
    rows = cur.fetchall()
    conn.close()
    return rows


def add_member_to_family(db_path: str, family_id: int, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO family_members (family_id, customer_id)
        VALUES (?, ?)
    """, (family_id, customer_id))
    conn.commit()
    conn.close()


def get_family_members(db_path: str, family_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.name, c.phone, c.email
        FROM family_members fm
        JOIN customers c ON c.id = fm.customer_id
        WHERE fm.family_id=?
        ORDER BY c.name
    """, (family_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# =========================
# PLANS + DUES
# =========================
def generate_dues(db_path: str, customer_id: int, plan_id: int,
                  first_due: datetime, remaining: float,
                  frequency: str, recurring_amount: float):
    if remaining <= 0:
        return
    if recurring_amount <= 0:
        raise ValueError("Recurring amount must be > 0")

    conn = db_connect(db_path)
    cur = conn.cursor()

    due_dt = first_due
    rem = float(remaining)

    while rem > 0.00001:
        due_amt = min(float(recurring_amount), rem)
        cur.execute("""
            INSERT INTO dues (customer_id, plan_id, due_date, amount_due, paid_amount, status)
            VALUES (?, ?, ?, ?, 0, 'Due')
        """, (customer_id, plan_id, due_dt.strftime(DATE_FMT), float(due_amt)))
        rem -= due_amt

        if frequency == "Monthly (Same Day)":
            due_dt = calc_next_month_same_day(due_dt)
        else:
            due_dt = due_dt + timedelta(days=FREQ_MAP_DAYS.get(frequency, 30))

    conn.commit()
    conn.close()


def add_plan(db_path: str, customer_id: int, plan_name: str,
             plan_total: float, deposit_amount: float, deposit_date: str,
             frequency: str, recurring_amount: float, first_due_date: str) -> int:

    dep_dt = parse_date(deposit_date)
    first_due_dt = parse_date(first_due_date)

    total = float(plan_total)
    deposit = float(deposit_amount)
    if total <= 0:
        raise ValueError("Plan total must be > 0")
    if deposit < 0:
        raise ValueError("Deposit cannot be negative")
    if deposit > total:
        raise ValueError("Deposit cannot be greater than plan total")
    if frequency not in FREQ_MAP_DAYS:
        raise ValueError("Frequency is invalid")
    if float(recurring_amount) <= 0:
        raise ValueError("Recurring amount must be > 0")

    remaining = max(total - deposit, 0)

    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO plans
        (customer_id, plan_name, plan_total, deposit_amount, deposit_date, frequency, recurring_amount, first_due_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_id,
        (plan_name or "").strip(),
        total,
        deposit,
        dep_dt.strftime(DATE_FMT),
        frequency,
        float(recurring_amount),
        first_due_dt.strftime(DATE_FMT),
        today_str()
    ))
    plan_id = cur.lastrowid
    conn.commit()
    conn.close()

    if remaining > 0:
        generate_dues(db_path, customer_id, plan_id, first_due_dt, remaining, frequency, recurring_amount)

    return plan_id


def list_customer_plans(db_path: str, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, COALESCE(plan_name,''), plan_total, deposit_amount, deposit_date, frequency, recurring_amount, first_due_date
        FROM plans
        WHERE customer_id=?
        ORDER BY id DESC
    """, (customer_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def list_customer_dues(db_path: str, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT d.id, d.due_date, d.amount_due, d.paid_amount, d.status, COALESCE(d.paid_date,''), d.plan_id
        FROM dues d
        WHERE d.customer_id=?
        ORDER BY date(d.due_date) ASC, d.id ASC
    """, (customer_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# =========================
# PAYMENTS ENGINE (E + F)
# =========================
def apply_amount_to_due(cur, due_id: int, pay_date: str, amount_to_apply: float) -> float:
    # Read due
    cur.execute("SELECT amount_due, paid_amount FROM dues WHERE id=?", (due_id,))
    row = cur.fetchone()
    if not row:
        return 0.0
    amount_due, paid_amount = float(row[0]), float(row[1])
    still_owed = amount_due - paid_amount
    if still_owed <= 0:
        cur.execute("UPDATE dues SET status='Paid', paid_date=? WHERE id=?", (pay_date, due_id))
        return 0.0

    applied = min(still_owed, float(amount_to_apply))
    new_paid = paid_amount + applied

    if new_paid >= amount_due - 0.00001:
        cur.execute("""
            UPDATE dues
            SET paid_amount=?, status='Paid', paid_date=?
            WHERE id=?
        """, (amount_due, pay_date, due_id))
    else:
        cur.execute("""
            UPDATE dues
            SET paid_amount=?, status='Due', paid_date=NULL
            WHERE id=?
        """, (new_paid, due_id))

    return float(applied)


def record_payment_row(cur, payer_type: str, payer_id: int, pay_date: str, amount: float, note: str) -> int:
    cur.execute("""
        INSERT INTO payments (payer_type, payer_id, payment_date, amount, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (payer_type, int(payer_id), pay_date, float(amount), (note or "").strip(), today_str()))
    return int(cur.lastrowid)


def list_open_dues_for_customer(db_path: str, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT d.id, c.name, d.due_date, (d.amount_due - d.paid_amount) AS owed
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        WHERE d.customer_id=? AND d.status!='Paid'
        ORDER BY date(d.due_date) ASC, d.id ASC
    """, (customer_id,))
    rows = cur.fetchall()
    conn.close()
    return rows  # (due_id, customer_name, due_date, owed)


def list_open_dues_for_family(db_path: str, family_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT d.id, c.name, d.due_date, (d.amount_due - d.paid_amount) AS owed
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN family_members fm ON fm.customer_id=c.id
        WHERE fm.family_id=? AND d.status!='Paid'
        ORDER BY date(d.due_date) ASC, d.id ASC
    """, (family_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def auto_allocate(db_path: str, payer_type: str, payer_id: int, amount: float, pay_date: str, note: str) -> int:
    _ = parse_date(pay_date)
    amt = float(amount)
    if amt <= 0:
        raise ValueError("Payment amount must be > 0")

    if payer_type == "Customer":
        dues = list_open_dues_for_customer(db_path, payer_id)
    else:
        dues = list_open_dues_for_family(db_path, payer_id)

    conn = db_connect(db_path)
    cur = conn.cursor()

    payment_id = record_payment_row(cur, payer_type, payer_id, pay_date, amt, note)

    remaining = amt
    for due_id, _, _, owed in dues:
        if remaining <= 0:
            break
        applied = apply_amount_to_due(cur, int(due_id), pay_date, remaining)
        if applied > 0:
            cur.execute("""
                INSERT INTO payment_allocations (payment_id, due_id, applied_amount)
                VALUES (?, ?, ?)
            """, (payment_id, int(due_id), float(applied)))
            remaining -= applied

    conn.commit()
    conn.close()
    return payment_id


def manual_allocate(db_path: str, payer_type: str, payer_id: int, amount: float, pay_date: str, note: str,
                    allocations: List[Tuple[int, float]]) -> int:
    """
    allocations: [(due_id, apply_amount), ...]
    Must total exactly the payment amount (small epsilon allowed).
    Must not exceed owed on any due.
    """
    _ = parse_date(pay_date)
    amt = float(amount)
    if amt <= 0:
        raise ValueError("Payment amount must be > 0")

    # Build owed map from actual open dues
    open_dues = list_open_dues_for_customer(db_path, payer_id) if payer_type == "Customer" else list_open_dues_for_family(db_path, payer_id)
    owed_map: Dict[int, float] = {int(due_id): float(owed) for due_id, _, _, owed in open_dues}

    # Validate allocations
    total_apply = 0.0
    for due_id, a in allocations:
        due_id = int(due_id)
        apply_amt = float(a)
        if apply_amt < 0:
            raise ValueError("Manual APPLY values cannot be negative.")
        if apply_amt == 0:
            continue
        if due_id not in owed_map:
            raise ValueError(f"Due ID {due_id} is not an open due for this payer.")
        if apply_amt > owed_map[due_id] + 0.00001:
            raise ValueError(f"Due ID {due_id}: APPLY {apply_amt:.2f} exceeds OWED {owed_map[due_id]:.2f}")
        total_apply += apply_amt

    if abs(total_apply - amt) > 0.01:
        raise ValueError(f"Manual allocations must total EXACTLY ${amt:.2f}. Currently totals ${total_apply:.2f}.")

    # Record
    conn = db_connect(db_path)
    cur = conn.cursor()

    payment_id = record_payment_row(cur, payer_type, payer_id, pay_date, amt, note)

    # Apply exactly as specified, in due_date order for safety/consistency
    # (but amounts are user-defined)
    allocations_sorted = [(int(d), float(a)) for d, a in allocations if float(a) > 0]
    for due_id, apply_amt in allocations_sorted:
        applied = apply_amount_to_due(cur, due_id, pay_date, apply_amt)
        if applied > 0:
            cur.execute("""
                INSERT INTO payment_allocations (payment_id, due_id, applied_amount)
                VALUES (?, ?, ?)
            """, (payment_id, due_id, float(applied)))

    conn.commit()
    conn.close()
    return payment_id


# =========================
# COMPANY SELECTOR (A)
# =========================
def simple_input(parent, title):
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("320x150")
    win.resizable(False, False)

    tk.Label(win, text=title).pack(pady=10)
    entry = tk.Entry(win, width=40)
    entry.pack(pady=5)
    entry.focus_set()

    value = {"text": None}

    def save():
        value["text"] = entry.get().strip()
        win.destroy()

    tk.Button(win, text="OK", command=save).pack(pady=10)
    win.grab_set()
    win.wait_window()
    return value["text"]


def select_company() -> Optional[AppState]:
    os.makedirs(BASE_DIR, exist_ok=True)

    root = tk.Tk()
    root.title("Select Company")
    root.geometry("520x300")
    root.resizable(False, False)

    tk.Label(root, text="Payment Tracker", font=("Arial", 18, "bold")).pack(pady=20)

    state = {"db": None}

    def create_company():
        name = simple_input(root, "Company Name")
        if not name:
            return

        path = filedialog.asksaveasfilename(
            parent=root,
            initialdir=BASE_DIR,
            initialfile=f"{name}.db",
            defaultextension=".db",
            filetypes=[("Database Files", "*.db")]
        )
        if not path:
            return

        init_db(path)
        set_setting(path, "company_name", name)
        state["db"] = path
        root.destroy()

    def open_company():
        path = filedialog.askopenfilename(
            parent=root,
            initialdir=BASE_DIR,
            filetypes=[("Database Files", "*.db")]
        )
        if not path:
            return

        init_db(path)
        state["db"] = path
        root.destroy()

    tk.Button(root, text="➕ Create Company", width=30, height=2, command=create_company).pack(pady=10)
    tk.Button(root, text="📂 Open Company", width=30, height=2, command=open_company).pack(pady=10)

    root.mainloop()

    if not state["db"]:
        return None
    return AppState(db_path=state["db"])


# =========================
# UI HELPERS: Editable Treeview cell (Step F)
# =========================
class TreeCellEditor:
    """In-place editor for a Treeview cell (used for APPLY column)."""
    def __init__(self, tree: ttk.Treeview):
        self.tree = tree
        self.entry: Optional[tk.Entry] = None
        self.item_id = None
        self.col = None

    def begin_edit(self, item_id: str, col: str):
        self.end_edit()

        bbox = self.tree.bbox(item_id, col)
        if not bbox:
            return

        x, y, w, h = bbox
        value = self.tree.set(item_id, col)

        self.entry = tk.Entry(self.tree)
        self.entry.place(x=x, y=y, width=w, height=h)
        self.entry.insert(0, value)
        self.entry.focus_set()

        self.item_id = item_id
        self.col = col

        self.entry.bind("<Return>", lambda e: self.commit())
        self.entry.bind("<Escape>", lambda e: self.end_edit())
        self.entry.bind("<FocusOut>", lambda e: self.commit())

    def commit(self):
        if not self.entry or not self.item_id or not self.col:
            return
        new_val = self.entry.get().strip()
        # sanitize to money-like
        try:
            val = money(new_val)
            self.tree.set(self.item_id, self.col, fmt2(val) if val != 0 else "0.00")
        except Exception:
            # if invalid, revert
            pass
        self.end_edit()

    def end_edit(self):
        if self.entry:
            self.entry.destroy()
        self.entry = None
        self.item_id = None
        self.col = None


# =========================
# MAIN APP (B → F)
# =========================
def launch_app(state: AppState):
    company_name = get_setting(state.db_path, "company_name", "Payment Tracker")

    app = tk.Tk()
    app.title(company_name)
    app.geometry("1250x820")

    top = tk.Frame(app)
    top.pack(fill="x", padx=10, pady=8)
    tk.Label(top, text=f"Company: {company_name}", font=("Arial", 14, "bold")).pack(side="left")
    tk.Label(top, text=f"DB: {state.db_path}", fg="gray").pack(side="left", padx=15)

    nb = ttk.Notebook(app)
    nb.pack(fill="both", expand=True, padx=10, pady=10)

    tab_customers = ttk.Frame(nb)
    tab_families = ttk.Frame(nb)
    tab_plans = ttk.Frame(nb)
    tab_payments = ttk.Frame(nb)

    nb.add(tab_customers, text="B) Customers")
    nb.add(tab_families, text="C) Family Groups (Optional)")
    nb.add(tab_plans, text="D) Plans & Dues")
    nb.add(tab_payments, text="E/F) Payments (Auto + Manual)")

    # -------------------
    # TAB: Customers (B)
    # -------------------
    cust_add = ttk.LabelFrame(tab_customers, text="Add Customer")
    cust_add.pack(fill="x", padx=10, pady=10)

    def add_row(parent, label, default=""):
        row = tk.Frame(parent)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text=label, width=18, anchor="w").pack(side="left")
        ent = tk.Entry(row, width=50)
        ent.pack(side="left")
        if default:
            ent.insert(0, default)
        return ent

    ent_c_name = add_row(cust_add, "Name")
    ent_c_phone = add_row(cust_add, "Phone")
    ent_c_email = add_row(cust_add, "Email")

    cust_search = ttk.LabelFrame(tab_customers, text="Search")
    cust_search.pack(fill="both", expand=True, padx=10, pady=10)

    row_s = tk.Frame(cust_search)
    row_s.pack(fill="x", padx=10, pady=6)
    tk.Label(row_s, text="Search (name/phone/email):").pack(side="left")
    ent_search = tk.Entry(row_s, width=40)
    ent_search.pack(side="left", padx=8)

    cust_tree = ttk.Treeview(cust_search, columns=("id", "name", "phone", "email"), show="headings", height=16)
    for col, w in [("id", 70), ("name", 260), ("phone", 160), ("email", 260)]:
        cust_tree.heading(col, text=col.upper())
        cust_tree.column(col, width=w, anchor="w")
    cust_tree.pack(fill="both", expand=True, padx=10, pady=10)

    def refresh_customer_search():
        clear_tree(cust_tree)
        rows = search_customers(state.db_path, ent_search.get().strip())
        for r in rows:
            cust_tree.insert("", "end", values=r)

    def on_add_customer():
        try:
            cid = add_customer(state.db_path, ent_c_name.get(), ent_c_phone.get(), ent_c_email.get())
            messagebox.showinfo("Success", f"Customer added (ID {cid})")
            refresh_customer_search()
            refresh_family_customer_list()
            refresh_plan_customer_list()
            refresh_payment_targets()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    ttk.Button(cust_add, text="Add Customer", command=on_add_customer).pack(pady=8)
    ttk.Button(row_s, text="Search", command=refresh_customer_search).pack(side="left", padx=6)

    # -------------------
    # TAB: Families (C)
    # -------------------
    fam_top = ttk.LabelFrame(tab_families, text="Create Family (Optional)")
    fam_top.pack(fill="x", padx=10, pady=10)

    ent_family_name = add_row(fam_top, "Family Name")

    fam_mid = tk.Frame(tab_families)
    fam_mid.pack(fill="both", expand=True, padx=10, pady=10)

    left_f = ttk.LabelFrame(fam_mid, text="Families")
    left_f.pack(side="left", fill="y", padx=(0, 10))

    right_f = ttk.LabelFrame(fam_mid, text="Members")
    right_f.pack(side="right", fill="both", expand=True)

    fam_tree = ttk.Treeview(left_f, columns=("id", "family_name"), show="headings", height=18)
    fam_tree.heading("id", text="ID")
    fam_tree.heading("family_name", text="FAMILY")
    fam_tree.column("id", width=70, anchor="w")
    fam_tree.column("family_name", width=220, anchor="w")
    fam_tree.pack(padx=10, pady=10)

    members_tree = ttk.Treeview(right_f, columns=("id", "name", "phone", "email"), show="headings", height=12)
    for col, w in [("id", 70), ("name", 260), ("phone", 160), ("email", 260)]:
        members_tree.heading(col, text=col.upper())
        members_tree.column(col, width=w, anchor="w")
    members_tree.pack(fill="both", expand=True, padx=10, pady=10)

    add_member_box = ttk.LabelFrame(right_f, text="Add Member to Selected Family")
    add_member_box.pack(fill="x", padx=10, pady=(0, 10))

    customer_pick = ttk.Combobox(add_member_box, values=[], state="readonly", width=60)
    customer_pick.pack(side="left", padx=10, pady=10)

    selected_family_id = {"id": None}

    def refresh_family_list():
        clear_tree(fam_tree)
        for fid, fn in list_families(state.db_path):
            fam_tree.insert("", "end", values=(fid, fn))

    def refresh_family_customer_list():
        rows = search_customers(state.db_path, "")
        values = [f"{cid} - {name}" for cid, name, _, _ in rows]
        customer_pick["values"] = values

    def on_create_family():
        try:
            fid = create_family(state.db_path, ent_family_name.get())
            messagebox.showinfo("Success", f"Family created (ID {fid})")
            refresh_family_list()
            refresh_payment_targets()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    ttk.Button(fam_top, text="Create Family", command=on_create_family).pack(pady=8)

    def on_family_select(event=None):
        sel = fam_tree.selection()
        selected_family_id["id"] = None
        clear_tree(members_tree)
        if not sel:
            return
        fid = int(fam_tree.item(sel[0])["values"][0])
        selected_family_id["id"] = fid
        for row in get_family_members(state.db_path, fid):
            members_tree.insert("", "end", values=row)

    fam_tree.bind("<<TreeviewSelect>>", on_family_select)

    def on_add_member():
        fid = selected_family_id["id"]
        if not fid:
            messagebox.showerror("Error", "Select a family first.")
            return
        val = customer_pick.get().strip()
        if not val:
            messagebox.showerror("Error", "Pick a customer to add.")
            return
        cid = int(val.split(" - ")[0])
        add_member_to_family(state.db_path, fid, cid)
        on_family_select()
        refresh_payment_targets()
        messagebox.showinfo("Success", "Member added to family.")

    ttk.Button(add_member_box, text="Add Member", command=on_add_member).pack(side="left", padx=10)

    # -------------------
    # TAB: Plans & Dues (D)
    # -------------------
    plan_box = ttk.LabelFrame(tab_plans, text="Add Plan (Multiple plans allowed)")
    plan_box.pack(fill="x", padx=10, pady=10)

    plan_customer_pick = ttk.Combobox(plan_box, values=[], state="readonly", width=60)
    plan_customer_pick.pack(padx=10, pady=(10, 2), anchor="w")

    ent_plan_name = add_row(plan_box, "Plan Name (optional)")
    ent_plan_total = add_row(plan_box, "Plan Total ($)")
    ent_deposit_amt = add_row(plan_box, "Deposit Amount ($)", "0")
    ent_deposit_date = add_row(plan_box, "Deposit Date (YYYY-MM-DD)", today_str())

    row_freq = tk.Frame(plan_box)
    row_freq.pack(fill="x", padx=10, pady=4)
    tk.Label(row_freq, text="Frequency", width=18, anchor="w").pack(side="left")
    freq_var = tk.StringVar(value="Monthly (Same Day)")
    freq_dd = ttk.Combobox(row_freq, textvariable=freq_var, values=list(FREQ_MAP_DAYS.keys()), width=47, state="readonly")
    freq_dd.pack(side="left")

    ent_recurring_amt = add_row(plan_box, "Recurring Amount ($)")
    ent_first_due = add_row(plan_box, "First Due Date (YYYY-MM-DD)")

    plan_view = ttk.LabelFrame(tab_plans, text="Customer Plans + Dues")
    plan_view.pack(fill="both", expand=True, padx=10, pady=10)

    plan_tree = ttk.Treeview(plan_view, columns=("id","plan_name","total","deposit","dep_date","freq","recurring","first_due"), show="headings", height=6)
    for col, w in [
        ("id",70),("plan_name",220),("total",110),("deposit",110),("dep_date",120),("freq",160),("recurring",120),("first_due",120)
    ]:
        plan_tree.heading(col, text=col.upper())
        plan_tree.column(col, width=w, anchor="w")
    plan_tree.pack(fill="x", padx=10, pady=8)

    dues_tree = ttk.Treeview(plan_view, columns=("due_id","due_date","amount_due","paid_amount","status","paid_date","plan_id"), show="headings", height=10)
    for col, w in [
        ("due_id",80),("due_date",120),("amount_due",120),("paid_amount",120),("status",100),("paid_date",120),("plan_id",80)
    ]:
        dues_tree.heading(col, text=col.upper())
        dues_tree.column(col, width=w, anchor="w")
    dues_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def refresh_plan_customer_list():
        rows = search_customers(state.db_path, "")
        values = [f"{cid} - {name}" for cid, name, _, _ in rows]
        plan_customer_pick["values"] = values

    def refresh_plan_view(customer_id: int):
        clear_tree(plan_tree)
        clear_tree(dues_tree)

        for p in list_customer_plans(state.db_path, customer_id):
            pid, pname, total, dep, depdate, freq, rec, firstdue = p
            plan_tree.insert("", "end", values=(pid, pname, fmt2(total), fmt2(dep), depdate, freq, fmt2(rec), firstdue))

        for d in list_customer_dues(state.db_path, customer_id):
            due_id, due_date, amt_due, paid_amt, status, paid_date, plan_id = d
            dues_tree.insert("", "end", values=(due_id, due_date, fmt2(amt_due), fmt2(paid_amt), status, paid_date, plan_id))

    def on_add_plan():
        pick = plan_customer_pick.get().strip()
        if not pick:
            messagebox.showerror("Error", "Select a customer for the plan.")
            return
        cid = int(pick.split(" - ")[0])
        try:
            pid = add_plan(
                state.db_path,
                customer_id=cid,
                plan_name=ent_plan_name.get(),
                plan_total=money(ent_plan_total.get()),
                deposit_amount=money(ent_deposit_amt.get()),
                deposit_date=ent_deposit_date.get().strip(),
                frequency=freq_var.get(),
                recurring_amount=money(ent_recurring_amt.get()),
                first_due_date=ent_first_due.get().strip()
            )
            messagebox.showinfo("Success", f"Plan created (Plan ID {pid}) and dues generated.")
            refresh_plan_view(cid)
            refresh_payment_targets()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    ttk.Button(plan_box, text="Create Plan + Generate Dues", command=on_add_plan).pack(pady=10)

    # -------------------
    # TAB: Payments (E/F)
    # -------------------
    pay_box = ttk.LabelFrame(tab_payments, text="Record Payment (Auto default: Oldest Due First)")
    pay_box.pack(fill="x", padx=10, pady=10)

    row_target = tk.Frame(pay_box)
    row_target.pack(fill="x", padx=10, pady=(10, 4))
    tk.Label(row_target, text="Pay For:", width=12, anchor="w").pack(side="left")

    payer_type_var = tk.StringVar(value="Customer")
    payer_type_dd = ttk.Combobox(row_target, textvariable=payer_type_var, values=["Customer", "Family"], state="readonly", width=14)
    payer_type_dd.pack(side="left", padx=6)

    payer_target_dd = ttk.Combobox(row_target, values=[], state="readonly", width=60)
    payer_target_dd.pack(side="left", padx=6)

    ent_pay_amt = add_row(pay_box, "Amount ($)", "0")
    ent_pay_date = add_row(pay_box, "Payment Date", today_str())
    ent_pay_note = add_row(pay_box, "Note (optional)", "")

    # Step F toggle
    row_manual = tk.Frame(pay_box)
    row_manual.pack(fill="x", padx=10, pady=(8, 6))
    manual_var = tk.BooleanVar(value=False)
    chk_manual = ttk.Checkbutton(row_manual, text="Manual Distribution (Advanced) — overrides auto allocation", variable=manual_var)
    chk_manual.pack(side="left")

    pay_result = ttk.LabelFrame(tab_payments, text="Open dues (preview / manual distribution)")
    pay_result.pack(fill="both", expand=True, padx=10, pady=10)

    cols = ("due_id", "customer", "due_date", "owed", "apply")
    preview_tree = ttk.Treeview(pay_result, columns=cols, show="headings", height=16)
    preview_tree.heading("due_id", text="DUE_ID")
    preview_tree.heading("customer", text="CUSTOMER")
    preview_tree.heading("due_date", text="DUE_DATE")
    preview_tree.heading("owed", text="OWED")
    preview_tree.heading("apply", text="APPLY (double-click to edit)")

    preview_tree.column("due_id", width=90, anchor="w")
    preview_tree.column("customer", width=280, anchor="w")
    preview_tree.column("due_date", width=140, anchor="w")
    preview_tree.column("owed", width=120, anchor="w")
    preview_tree.column("apply", width=140, anchor="w")

    preview_tree.pack(fill="both", expand=True, padx=10, pady=10)

    editor = TreeCellEditor(preview_tree)

    def refresh_payment_targets():
        cust = search_customers(state.db_path, "")
        cust_values = [f"{cid} - {name}" for cid, name, _, _ in cust]
        fam = list_families(state.db_path)
        fam_values = [f"{fid} - {fname}" for fid, fname in fam]

        if payer_type_var.get() == "Customer":
            payer_target_dd["values"] = cust_values
        else:
            payer_target_dd["values"] = fam_values

    def on_payer_type_change(event=None):
        refresh_payment_targets()
        clear_tree(preview_tree)

    payer_type_dd.bind("<<ComboboxSelected>>", on_payer_type_change)

    def load_open_dues_into_tree():
        clear_tree(preview_tree)
        ptype = payer_type_var.get()
        pick = payer_target_dd.get().strip()
        if not pick:
            return

        pid = int(pick.split(" - ")[0])

        rows = list_open_dues_for_customer(state.db_path, pid) if ptype == "Customer" else list_open_dues_for_family(state.db_path, pid)

        for due_id, cname, due_date, owed in rows:
            preview_tree.insert("", "end", values=(int(due_id), cname, due_date, fmt2(owed), "0.00"))

    def auto_fill_oldest_first():
        """Fill APPLY column based on Oldest Due First for current payment amount."""
        load_open_dues_into_tree()
        amt = money(ent_pay_amt.get())
        remaining = float(amt)

        for item in preview_tree.get_children():
            if remaining <= 0:
                preview_tree.set(item, "apply", "0.00")
                continue
            owed = money(preview_tree.set(item, "owed"))
            apply_amt = min(owed, remaining)
            preview_tree.set(item, "apply", fmt2(apply_amt))
            remaining -= apply_amt

    def clear_apply_column():
        for item in preview_tree.get_children():
            preview_tree.set(item, "apply", "0.00")

    def on_tree_double_click(event):
        if not manual_var.get():
            return
        region = preview_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item_id = preview_tree.identify_row(event.y)
        col = preview_tree.identify_column(event.x)  # e.g. '#5'
        if not item_id:
            return
        # only allow editing APPLY column
        if col != "#5":
            return
        editor.begin_edit(item_id, "apply")

    preview_tree.bind("<Double-1>", on_tree_double_click)

    def record_payment():
        ptype = payer_type_var.get()
        pick = payer_target_dd.get().strip()
        if not pick:
            messagebox.showerror("Error", "Select who you are paying for (Customer or Family).")
            return

        pid = int(pick.split(" - ")[0])

        try:
            amt = money(ent_pay_amt.get())
            pdate = ent_pay_date.get().strip()
            note = ent_pay_note.get().strip()

            if not manual_var.get():
                # Step E: automatic oldest due first
                payment_id = auto_allocate(state.db_path, ptype, pid, amt, pdate, note)
                messagebox.showinfo("Success", f"Payment recorded (Payment ID {payment_id}). Auto-applied (Oldest Due First).")
                load_open_dues_into_tree()
                return

            # Step F: manual distribution
            # ensure open dues list is loaded
            if not preview_tree.get_children():
                load_open_dues_into_tree()

            allocs: List[Tuple[int, float]] = []
            for item in preview_tree.get_children():
                due_id = int(preview_tree.set(item, "due_id"))
                apply_amt = money(preview_tree.set(item, "apply"))
                if apply_amt > 0:
                    allocs.append((due_id, apply_amt))

            payment_id = manual_allocate(state.db_path, ptype, pid, amt, pdate, note, allocs)
            messagebox.showinfo("Success", f"Payment recorded (Payment ID {payment_id}). Applied using MANUAL distribution.")
            load_open_dues_into_tree()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Buttons
    btns = tk.Frame(pay_box)
    btns.pack(pady=8)

    ttk.Button(btns, text="Preview Open Dues", command=load_open_dues_into_tree).pack(side="left", padx=6)
    ttk.Button(btns, text="Auto-Fill (Oldest Due First)", command=auto_fill_oldest_first).pack(side="left", padx=6)
    ttk.Button(btns, text="Clear APPLY", command=clear_apply_column).pack(side="left", padx=6)
    ttk.Button(btns, text="Record Payment", command=record_payment).pack(side="left", padx=6)

    # -------------------
    # Cross-refresh helpers
    # -------------------
    def on_customer_click_in_search(event=None):
        sel = cust_tree.selection()
        if not sel:
            return
        cid = int(cust_tree.item(sel[0])["values"][0])
        refresh_plan_view(cid)

    cust_tree.bind("<<TreeviewSelect>>", on_customer_click_in_search)

    # Initial loads
    refresh_customer_search()
    refresh_family_list()
    refresh_family_customer_list()
    refresh_plan_customer_list()
    refresh_payment_targets()

    app.mainloop()


# =========================
# START
# =========================
if __name__ == "__main__":
    state = select_company()
    if not state:
        raise SystemExit
    init_db(state.db_path)
    launch_app(state)

