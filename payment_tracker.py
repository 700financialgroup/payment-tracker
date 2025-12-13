import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Optional, List, Tuple, Dict
import json

try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

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

# Database configuration
USE_POSTGRES = os.getenv('USE_POSTGRES', 'false').lower() == 'true'
POSTGRES_CONFIG = {
    'host': os.getenv('PG_HOST', 'localhost'),
    'database': os.getenv('PG_DATABASE', 'payment_tracker'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', 'password'),
    'port': int(os.getenv('PG_PORT', '5432'))
}

def is_postgres() -> bool:
    return USE_POSTGRES

def sql(q: str) -> str:
    return q.replace("?", "%s") if is_postgres() else q

# =========================
# UTILS
# =========================
def today_str() -> str:
    return datetime.now().strftime(DATE_FMT)

def parse_date(s: str) -> datetime:
    if not s or not s.strip():
        raise ValueError("Date is required (YYYY-MM-DD)")
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

def ensure_column(conn, table: str, col: str, ddl: str):
    """
    Adds a column to a table if it doesn't exist.
    Works with both SQLite and PostgreSQL.
    """
    if is_postgres():
        # PostgreSQL - check if column exists
        cur = conn.cursor()
        cur.execute(sql("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """), (table, col))
        if not cur.fetchone():
            cur.execute(sql(ddl))
            conn.commit()
    else:
        # SQLite version
        cur = conn.cursor()
        cur.execute(sql(f"PRAGMA table_info({table})"))
        cols = [r[1] for r in cur.fetchall()]
        if col not in cols:
            cur.execute(sql(ddl))
            conn.commit()

# =========================
# APP STATE
# =========================
@dataclass
class AppState:
    db_path: str

# =========================
# DB CORE
# =========================
def db_connect(db_path: str = None):
    """Connect to database (SQLite or PostgreSQL based on configuration)"""
    if USE_POSTGRES:
        if not HAS_POSTGRES:
            raise ImportError("psycopg2 not installed. Install with: pip install psycopg2-binary")

        try:
            conn = psycopg2.connect(**POSTGRES_CONFIG)
            # Set up JSON encoding for PostgreSQL
            psycopg2.extras.register_json(conn, loads=json.loads, dumps=json.dumps)
            return conn
        except psycopg2.OperationalError as e:
            print(f"PostgreSQL connection failed: {e}")
            print("Falling back to SQLite...")
            # Don't modify global here, just fall back for this connection

    # Fallback to SQLite
    if db_path is None:
        db_path = "payments.db"
    return sqlite3.connect(db_path)

def is_postgres():
    """Check if we're using PostgreSQL"""
    return USE_POSTGRES and HAS_POSTGRES

def init_db(db_path: str = None):
    """Initialize database with schema for both SQLite and PostgreSQL"""
    conn = db_connect(db_path)
    cur = conn.cursor()

    if is_postgres():
        # PostgreSQL schema
        # Drop existing tables if they exist (for clean migration)
        cur.execute(sql("""
            DROP TABLE IF EXISTS payment_allocations CASCADE;
            DROP TABLE IF EXISTS payments CASCADE;
            DROP TABLE IF EXISTS dues CASCADE;
            DROP TABLE IF EXISTS plans CASCADE;
            DROP TABLE IF EXISTS family_members CASCADE;
            DROP TABLE IF EXISTS families CASCADE;
            DROP TABLE IF EXISTS users CASCADE;
            DROP TABLE IF EXISTS settings CASCADE;
            DROP TABLE IF EXISTS customers CASCADE;
        """))

        # Customers
        cur.execute(sql("""
            CREATE TABLE customers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                email VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_customers_name ON customers(name);
            CREATE INDEX idx_customers_active ON customers(is_active);
        """))

        # Families
        cur.execute(sql("""
            CREATE TABLE families (
                id SERIAL PRIMARY KEY,
                family_name VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # Family members
        cur.execute(sql("""
            CREATE TABLE family_members (
                family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                PRIMARY KEY (family_id, customer_id)
            );
        """))

        # Plans
        cur.execute(sql("""
            CREATE TABLE plans (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                plan_name VARCHAR(255),
                plan_total DECIMAL(10,2) NOT NULL,
                deposit_amount DECIMAL(10,2) DEFAULT 0,
                deposit_date DATE,
                deposit_is_active BOOLEAN DEFAULT TRUE,
                deposit_voided_at TIMESTAMP,
                deposit_void_note TEXT,
                frequency VARCHAR(50) NOT NULL,
                recurring_amount DECIMAL(10,2) NOT NULL,
                first_due_date DATE NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_frequency CHECK (frequency IN ('Weekly', 'Biweekly', 'Monthly (Same Day)'))
            );
            CREATE INDEX idx_plans_customer ON plans(customer_id);
            CREATE INDEX idx_plans_active ON plans(is_active);
        """))

        # Dues
        cur.execute(sql("""
            CREATE TABLE dues (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                due_date DATE NOT NULL,
                amount_due DECIMAL(10,2) NOT NULL,
                paid_amount DECIMAL(10,2) DEFAULT 0,
                status VARCHAR(20) DEFAULT 'Due',
                paid_date DATE,
                source VARCHAR(50) DEFAULT 'Schedule',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_status CHECK (status IN ('Due', 'Paid', 'Overdue'))
            );
            CREATE INDEX idx_dues_customer ON dues(customer_id);
            CREATE INDEX idx_dues_date ON dues(due_date);
            CREATE INDEX idx_dues_status ON dues(status);
        """))

        # Payments
        cur.execute(sql("""
            CREATE TABLE payments (
                id SERIAL PRIMARY KEY,
                payer_type VARCHAR(20) NOT NULL,
                payer_id INTEGER NOT NULL,
                payment_date DATE NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                note TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_payer_type CHECK (payer_type IN ('Customer', 'Family'))
            );
            CREATE INDEX idx_payments_date ON payments(payment_date);
            CREATE INDEX idx_payments_payer ON payments(payer_type, payer_id);
        """))

        # Payment allocations
        cur.execute(sql("""
            CREATE TABLE payment_allocations (
                id SERIAL PRIMARY KEY,
                payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
                due_id INTEGER NOT NULL REFERENCES dues(id) ON DELETE CASCADE,
                applied_amount DECIMAL(10,2) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_positive_amount CHECK (applied_amount > 0)
            );
            CREATE INDEX idx_allocations_payment ON payment_allocations(payment_id);
            CREATE INDEX idx_allocations_due ON payment_allocations(due_id);
        """))

        # Users
        cur.execute(sql("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                CONSTRAINT chk_role CHECK (role IN ('admin', 'manager', 'user'))
            );
        """))

        # Settings
        cur.execute(sql("""
            CREATE TABLE settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(100) NOT NULL UNIQUE,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

    else:
        # SQLite schema (legacy compatibility)
        # Customers
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                created_at TEXT
            )
        """))

        # Families
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS families (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_name TEXT NOT NULL,
                created_at TEXT
            )
        """))

        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS family_members (
                family_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                PRIMARY KEY (family_id, customer_id),
                FOREIGN KEY (family_id) REFERENCES families(id),
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """))

        # Plans
        cur.execute(sql("""
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
        """))

        # Dues
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS dues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                amount_due REAL NOT NULL,
                paid_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Due',
                paid_date TEXT,
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (plan_id) REFERENCES plans(id)
            )
        """))

        # Payments
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payer_type TEXT NOT NULL,
                payer_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT,
                created_at TEXT
            )
        """))

        # Allocations
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS payment_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL,
                due_id INTEGER NOT NULL,
                applied_amount REAL NOT NULL,
                FOREIGN KEY (payment_id) REFERENCES payments(id),
                FOREIGN KEY (due_id) REFERENCES dues(id)
            )
        """))

        # Users
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT
            )
        """))

        # Settings
        cur.execute(sql("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """))

    # Apply migrations for both databases
    if is_postgres():
        # PostgreSQL migrations
        ensure_column(conn, "customers", "is_active", "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        ensure_column(conn, "families", "is_active", "ALTER TABLE families ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        ensure_column(conn, "plans", "is_active", "ALTER TABLE plans ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        ensure_column(conn, "payments", "is_active", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        ensure_column(conn, "payment_allocations", "is_active", "ALTER TABLE payment_allocations ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        ensure_column(conn, "plans", "deposit_is_active", "ALTER TABLE plans ADD COLUMN IF NOT EXISTS deposit_is_active BOOLEAN DEFAULT TRUE")
        ensure_column(conn, "plans", "deposit_voided_at", "ALTER TABLE plans ADD COLUMN IF NOT EXISTS deposit_voided_at TIMESTAMP")
        ensure_column(conn, "plans", "deposit_void_note", "ALTER TABLE plans ADD COLUMN IF NOT EXISTS deposit_void_note TEXT")
        ensure_column(conn, "dues", "source", "ALTER TABLE dues ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'Schedule'")
        # Migrate 'Partial' status to 'Due'
        cur.execute(sql("UPDATE dues SET status = 'Due' WHERE status = 'Partial'"))
    else:
        # SQLite migrations
        ensure_column(conn, "customers", "is_active", "ALTER TABLE customers ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "families", "is_active", "ALTER TABLE families ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "plans", "is_active", "ALTER TABLE plans ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "payments", "is_active", "ALTER TABLE payments ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "payment_allocations", "is_active", "ALTER TABLE payment_allocations ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "plans", "deposit_is_active", "ALTER TABLE plans ADD COLUMN deposit_is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "plans", "deposit_voided_at", "ALTER TABLE plans ADD COLUMN deposit_voided_at TEXT")
        ensure_column(conn, "plans", "deposit_void_note", "ALTER TABLE plans ADD COLUMN deposit_void_note TEXT")
        ensure_column(conn, "dues", "source", "ALTER TABLE dues ADD COLUMN source TEXT NOT NULL DEFAULT 'Schedule'")
        # Migrate 'Partial' status to 'Due'
        cur.execute(sql("UPDATE dues SET status = 'Due' WHERE status = 'Partial'"))

    conn.commit()
    conn.close()

def set_setting(db_path: str, key: str, value: str):
    """Set a setting value (works with both SQLite and PostgreSQL)"""
    conn = db_connect(db_path)
    cur = conn.cursor()

    if is_postgres():
        cur.execute(sql("""
            INSERT INTO settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
        """), (key, value))
    else:
        cur.execute(sql("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        """), (key, value))

    conn.commit()
    conn.close()

def get_setting(db_path: str, key: str, default: str = "") -> str:
    """Get a setting value (works with both SQLite and PostgreSQL)"""
    conn = db_connect(db_path)
    cur = conn.cursor()

    cur.execute(sql("SELECT value FROM settings WHERE key=%s" if is_postgres() else "SELECT value FROM settings WHERE key=?"), (key,))
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
    if is_postgres():
        cur.execute(sql("""
            INSERT INTO customers (name, phone, email, created_at, is_active)
            VALUES (?, ?, ?, ?, 1)
            RETURNING id
        """), (name, (phone or "").strip(), (email or "").strip(), today_str()))
        cid = cur.fetchone()[0]
    else:
        cur.execute(sql("""
            INSERT INTO customers (name, phone, email, created_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        """), (name, (phone or "").strip(), (email or "").strip(), today_str()))
        cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid

def update_customer(db_path: str, customer_id: int, name: str, phone: str, email: str):
    name = (name or "").strip()
    if not name:
        raise ValueError("Customer name is required.")
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        UPDATE customers
        SET name=?, phone=?, email=?
        WHERE id=? AND is_active=1
    """), (name, (phone or "").strip(), (email or "").strip(), int(customer_id)))
    conn.commit()
    conn.close()

def can_deactivate_customer(db_path: str, customer_id: int) -> Tuple[bool, str]:
    conn = db_connect(db_path)
    cur = conn.cursor()

    cur.execute(sql("""
        SELECT COUNT(*)
        FROM payments
        WHERE payer_type='Customer' AND payer_id=? AND is_active=1
    """), (int(customer_id),))
    pay_cnt = int(cur.fetchone()[0] or 0)
    if pay_cnt > 0:
        conn.close()
        return False, "Cannot deactivate: customer has recorded payments. Void payments first if needed."

    cur.execute(sql("""
        SELECT COUNT(*)
        FROM dues d
        JOIN plans p ON p.id=d.plan_id
        WHERE d.customer_id=? AND p.is_active=1 AND d.paid_amount > 0
    """), (int(customer_id),))
    paid_dues = int(cur.fetchone()[0] or 0)
    if paid_dues > 0:
        conn.close()
        return False, "Cannot deactivate: customer has paid dues history."

    conn.close()
    return True, ""

def deactivate_customer(db_path: str, customer_id: int):
    ok, msg = can_deactivate_customer(db_path, customer_id)
    if not ok:
        raise ValueError(msg)
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("UPDATE customers SET is_active=0 WHERE id=?"), (int(customer_id),))
    conn.commit()
    conn.close()

def search_customers(db_path: str, term: str, include_inactive: bool = False):
    t = f"%{(term or '').strip()}%"
    conn = db_connect(db_path)
    cur = conn.cursor()

    if include_inactive:
        cur.execute(sql("""
            SELECT id, name, phone, email, is_active
            FROM customers
            WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?
            ORDER BY name
        """), (t, t, t))
        rows = cur.fetchall()
        conn.close()
        return rows

    cur.execute(sql("""
        SELECT id, name, phone, email
        FROM customers
        WHERE is_active=1 AND (name LIKE ? OR phone LIKE ? OR email LIKE ?)
        ORDER BY name
    """), (t, t, t))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_customer(db_path: str, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("SELECT id, name, phone, email, is_active FROM customers WHERE id=?"), (int(customer_id),))
    row = cur.fetchone()
    conn.close()
    return row

# =========================
# FAMILIES
# =========================
def create_family(db_path: str, family_name: str) -> int:
    fn = (family_name or "").strip()
    if not fn:
        raise ValueError("Family name is required.")
    conn = db_connect(db_path)
    cur = conn.cursor()
    if is_postgres():
        cur.execute(
            sql("""
                INSERT INTO families (family_name, created_at, is_active)
                VALUES (?, ?, 1)
                RETURNING id
            """),
            (fn, today_str())
        )
        fid = cur.fetchone()[0]
    else:
        cur.execute(
            sql("""
                INSERT INTO families (family_name, created_at, is_active)
                VALUES (?, ?, 1)
            """),
            (fn, today_str())
        )
        fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid

def update_family(db_path: str, family_id: int, family_name: str):
    fn = (family_name or "").strip()
    if not fn:
        raise ValueError("Family name is required.")
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(
        sql("""
            UPDATE families
            SET family_name=?
            WHERE id=? AND is_active=1
        """),
        (fn, int(family_id))
    )
    conn.commit()
    conn.close()

def list_families(db_path: str, include_inactive: bool = False):
    conn = db_connect(db_path)
    cur = conn.cursor()
    if include_inactive:
        cur.execute(sql("SELECT id, family_name, is_active FROM families ORDER BY family_name"))
        rows = cur.fetchall()
        conn.close()
        return rows
    cur.execute(sql("SELECT id, family_name FROM families WHERE is_active=1 ORDER BY family_name"))
    rows = cur.fetchall()
    conn.close()
    return rows

def add_member_to_family(db_path: str, family_id: int, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(
        sql("""
            INSERT OR IGNORE INTO family_members (family_id, customer_id)
            VALUES (?, ?)
        """),
        (int(family_id), int(customer_id))
    )
    conn.commit()
    conn.close()

def remove_member_from_family(db_path: str, family_id: int, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(
        sql("""
            DELETE FROM family_members
            WHERE family_id=? AND customer_id=?
        """),
        (int(family_id), int(customer_id))
    )
    conn.commit()
    conn.close()

def get_family_members(db_path: str, family_id: int, include_inactive_customers: bool = False):
    conn = db_connect(db_path)
    cur = conn.cursor()
    if include_inactive_customers:
        cur.execute(
            sql("""
                SELECT c.id, c.name, c.phone, c.email, c.is_active
                FROM family_members fm
                JOIN customers c ON c.id = fm.customer_id
                WHERE fm.family_id=?
                ORDER BY c.name
            """),
            (int(family_id),)
        )
        rows = cur.fetchall()
        conn.close()
        return rows

    cur.execute(
        sql("""
            SELECT c.id, c.name, c.phone, c.email
            FROM family_members fm
            JOIN customers c ON c.id = fm.customer_id
            WHERE fm.family_id=? AND c.is_active=1
            ORDER BY c.name
        """),
        (int(family_id),)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def can_deactivate_family(db_path: str, family_id: int) -> Tuple[bool, str]:
    conn = db_connect(db_path)
    cur = conn.cursor()

    cur.execute(
        sql("""
            SELECT COUNT(*)
            FROM payments
            WHERE payer_type='Family' AND payer_id=? AND is_active=1
        """),
        (int(family_id),)
    )
    pay_cnt = int(cur.fetchone()[0] or 0)
    if pay_cnt > 0:
        conn.close()
        return False, "Cannot deactivate: family has recorded payments. Void payments first if needed."

    cur.execute(
        sql("""
            SELECT COUNT(*)
            FROM family_members
            WHERE family_id=?
        """),
        (int(family_id),)
    )
    mem_cnt = int(cur.fetchone()[0] or 0)
    if mem_cnt > 0:
        conn.close()
        return False, "Cannot deactivate: family still has members. Remove members first."

    conn.close()
    return True, ""

def deactivate_family(db_path: str, family_id: int):
    ok, msg = can_deactivate_family(db_path, family_id)
    if not ok:
        raise ValueError(msg)
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("UPDATE families SET is_active=0 WHERE id=?"), (int(family_id),))
    conn.commit()
    conn.close()

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
        cur.execute(
            sql("""
                INSERT INTO dues (customer_id, plan_id, due_date, amount_due, paid_amount, status, source)
                VALUES (?, ?, ?, ?, 0, 'Due', 'Schedule')
            """),
            (int(customer_id), int(plan_id), due_dt.strftime(DATE_FMT), float(due_amt))
        )
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
    if is_postgres():
        cur.execute(
            sql("""
                INSERT INTO plans
                (customer_id, plan_name, plan_total, deposit_amount, deposit_date, frequency, recurring_amount, first_due_date, created_at, is_active, deposit_is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                RETURNING id
            """),
            (
                int(customer_id),
                (plan_name or "").strip(),
                total,
                deposit,
                dep_dt.strftime(DATE_FMT),
                frequency,
                float(recurring_amount),
                first_due_dt.strftime(DATE_FMT),
                today_str()
            )
        )
        plan_id = int(cur.fetchone()[0])
    else:
        cur.execute(
            sql("""
                INSERT INTO plans
                (customer_id, plan_name, plan_total, deposit_amount, deposit_date, frequency, recurring_amount, first_due_date, created_at, is_active, deposit_is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
            """),
            (
                int(customer_id),
                (plan_name or "").strip(),
                total,
                deposit,
                dep_dt.strftime(DATE_FMT),
                frequency,
                float(recurring_amount),
                first_due_dt.strftime(DATE_FMT),
                today_str()
            )
        )
        plan_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    if remaining > 0:
        generate_dues(db_path, customer_id, plan_id, first_due_dt, remaining, frequency, recurring_amount)

    return plan_id

def update_plan_name(db_path: str, plan_id: int, new_name: str):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(
        sql("""
            UPDATE plans
            SET plan_name=?
            WHERE id=? AND is_active=1
        """),
        ((new_name or "").strip(), int(plan_id))
    )
    conn.commit()
    conn.close()

def can_deactivate_plan(db_path: str, plan_id: int) -> Tuple[bool, str]:
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(
        sql("""
            SELECT COUNT(*)
            FROM dues
            WHERE plan_id=? AND paid_amount > 0
        """),
        (int(plan_id),)
    )
    paid_cnt = int(cur.fetchone()[0] or 0)
    conn.close()
    if paid_cnt > 0:
        return False, "Cannot deactivate: plan has paid dues history."
    return True, ""

def deactivate_plan(db_path: str, plan_id: int):
    ok, msg = can_deactivate_plan(db_path, plan_id)
    if not ok:
        raise ValueError(msg)
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("UPDATE plans SET is_active=0 WHERE id=?"), (int(plan_id),))
    conn.commit()
    conn.close()

def list_customer_plans(db_path: str, customer_id: int, include_inactive: bool = False):
    conn = db_connect(db_path)
    cur = conn.cursor()
    if include_inactive:
        cur.execute(sql("""
            SELECT id, COALESCE(plan_name,''), plan_total, deposit_amount, deposit_date, frequency, recurring_amount, first_due_date, is_active,
                   deposit_is_active
            FROM plans
            WHERE customer_id=?
            ORDER BY id DESC
        """), (int(customer_id),))
        rows = cur.fetchall()
        conn.close()
        return rows

    cur.execute(sql("""
        SELECT id, COALESCE(plan_name,''), plan_total, deposit_amount, deposit_date, frequency, recurring_amount, first_due_date, deposit_is_active
        FROM plans
        WHERE customer_id=? AND is_active=1
        ORDER BY id DESC
    """), (int(customer_id),))
    rows = cur.fetchall()
    conn.close()
    return rows

def list_customer_dues(db_path: str, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        SELECT d.id, d.due_date, d.amount_due, d.paid_amount, d.status, COALESCE(d.paid_date,''), d.plan_id, d.source
        FROM dues d
        JOIN plans p ON p.id=d.plan_id
        JOIN customers c ON c.id=d.customer_id
        WHERE d.customer_id=? AND p.is_active=1 AND c.is_active=1
        ORDER BY date(d.due_date) ASC, d.id ASC
    """), (int(customer_id),))
    rows = cur.fetchall()
    conn.close()
    return rows

def void_deposit(db_path: str, plan_id: int, void_note: str = ""):
    """
    Soft-void the deposit on a plan:
    - Marks deposit as inactive on the plan
    - Creates a NEW due for the deposit amount (so totals/owed become correct)
    Safety:
    - Only if plan is active
    - Only if deposit_is_active=1
    - Only if deposit_amount > 0
    """
    conn = db_connect(db_path)
    cur = conn.cursor()

    cur.execute(sql("""
        SELECT customer_id, plan_total, deposit_amount, deposit_date, is_active, deposit_is_active
        FROM plans
        WHERE id=?
    """), (int(plan_id),))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise ValueError("Plan not found.")

    customer_id, _plan_total, dep_amt, dep_date, is_active, dep_is_active = r
    if int(is_active) != 1:
        conn.close()
        raise ValueError("Plan is inactive.")
    if float(dep_amt or 0) <= 0:
        conn.close()
        raise ValueError("This plan has no deposit amount to void.")
    if int(dep_is_active or 0) != 1:
        conn.close()
        raise ValueError("Deposit is already voided.")

    # Mark deposit voided
    cur.execute(sql("""
        UPDATE plans
        SET deposit_is_active=0,
            deposit_voided_at=?,
            deposit_void_note=?
        WHERE id=?
    """), (today_str(), (void_note or "").strip(), int(plan_id)))

    # Create due that represents the now-owed deposit
    # Due date uses the deposit_date (keeping timeline consistent)
    cur.execute(sql("""
        INSERT INTO dues (customer_id, plan_id, due_date, amount_due, paid_amount, status, paid_date, source)
        VALUES (?, ?, ?, ?, 0, 'Due', NULL, 'DepositVoid')
    """), (int(customer_id), int(plan_id), str(dep_date), float(dep_amt)))

    conn.commit()
    conn.close()

# =========================
# PAYMENTS ENGINE (E + F) + VOID PAYMENT
# =========================
def apply_amount_to_due(cur, due_id: int, pay_date: str, amount_to_apply: float) -> float:
    cur.execute(sql("SELECT amount_due, paid_amount FROM dues WHERE id=?"), (int(due_id),))
    row = cur.fetchone()
    if not row:
        return 0.0
    amount_due, paid_amount = float(row[0]), float(row[1])
    still_owed = amount_due - paid_amount
    if still_owed <= 0:
        cur.execute(sql("UPDATE dues SET status='Paid', paid_date=? WHERE id=?"), (pay_date, int(due_id)))
        return 0.0

    applied = min(still_owed, float(amount_to_apply))
    new_paid = paid_amount + applied

    if new_paid >= amount_due - 0.00001:
        cur.execute(sql("""
            UPDATE dues
            SET paid_amount=?, status='Paid', paid_date=?
            WHERE id=?
        """), (amount_due, pay_date, int(due_id)))
    else:
        cur.execute(sql("""
            UPDATE dues
            SET paid_amount=?, status='Due', paid_date=NULL
            WHERE id=?
        """), (new_paid, int(due_id)))

    return float(applied)

def record_payment_row(cur, payer_type: str, payer_id: int, pay_date: str, amount: float, note: str, is_postgres: bool = False) -> int:
    if is_postgres:
        cur.execute(sql("""
            INSERT INTO payments (payer_type, payer_id, payment_date, amount, note, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            RETURNING id
        """), (payer_type, int(payer_id), pay_date, float(amount), (note or "").strip(), today_str()))
        return int(cur.fetchone()[0])
    else:
        cur.execute(sql("""
            INSERT INTO payments (payer_type, payer_id, payment_date, amount, note, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """), (payer_type, int(payer_id), pay_date, float(amount), (note or "").strip(), today_str()))
        return int(cur.lastrowid)

def list_open_dues_for_customer(db_path: str, customer_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        SELECT d.id, c.name, d.due_date, (d.amount_due - d.paid_amount) AS owed
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE d.customer_id=? AND d.status!='Paid'
          AND c.is_active=1
          AND p.is_active=1
        ORDER BY date(d.due_date) ASC, d.id ASC
    """), (int(customer_id),))
    rows = cur.fetchall()
    conn.close()
    return rows

def list_open_dues_for_family(db_path: str, family_id: int):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        SELECT d.id, c.name, d.due_date, (d.amount_due - d.paid_amount) AS owed
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        JOIN family_members fm ON fm.customer_id=c.id
        JOIN families f ON f.id=fm.family_id
        WHERE fm.family_id=? AND d.status!='Paid'
          AND c.is_active=1
          AND p.is_active=1
          AND f.is_active=1
        ORDER BY date(d.due_date) ASC, d.id ASC
    """, (int(family_id),))
    rows = cur.fetchall()
    conn.close()
    return rows

def auto_allocate(db_path: str, payer_type: str, payer_id: int, amount: float, pay_date: str, note: str) -> int:
    _ = parse_date(pay_date)
    amt = float(amount)
    if amt <= 0:
        raise ValueError("Payment amount must be > 0")

    dues = list_open_dues_for_customer(db_path, payer_id) if payer_type == "Customer" else list_open_dues_for_family(db_path, payer_id)

    conn = db_connect(db_path)
    cur = conn.cursor()

    payment_id = record_payment_row(cur, payer_type, payer_id, pay_date, amt, note, is_postgres(db_path))

    remaining = amt
    for due_id, _, _, _owed in dues:
        if remaining <= 0:
            break
        applied = apply_amount_to_due(cur, int(due_id), pay_date, remaining)
        if applied > 0:
            cur.execute(sql("""
                INSERT INTO payment_allocations (payment_id, due_id, applied_amount, is_active)
                VALUES (?, ?, ?, 1)
            """), (int(payment_id), int(due_id), float(applied)))
            remaining -= applied

    conn.commit()
    conn.close()
    return int(payment_id)

def manual_allocate(db_path: str, payer_type: str, payer_id: int, amount: float, pay_date: str, note: str,
                    allocations: List[Tuple[int, float]]) -> int:
    _ = parse_date(pay_date)
    amt = float(amount)
    if amt <= 0:
        raise ValueError("Payment amount must be > 0")

    open_dues = list_open_dues_for_customer(db_path, payer_id) if payer_type == "Customer" else list_open_dues_for_family(db_path, payer_id)
    owed_map: Dict[int, float] = {int(due_id): float(owed) for due_id, _, _, owed in open_dues}

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

    conn = db_connect(db_path)
    cur = conn.cursor()

    payment_id = record_payment_row(cur, payer_type, payer_id, pay_date, amt, note, is_postgres(db_path))

    allocations_sorted = [(int(d), float(a)) for d, a in allocations if float(a) > 0]
    for due_id, apply_amt in allocations_sorted:
        applied = apply_amount_to_due(cur, due_id, pay_date, apply_amt)
        if applied > 0:
            cur.execute(sql("""
                INSERT INTO payment_allocations (payment_id, due_id, applied_amount, is_active)
                VALUES (?, ?, ?, 1)
            """, (int(payment_id), int(due_id), float(applied)))

    conn.commit()
    conn.close()
    return int(payment_id)

def list_payments(db_path: str, include_inactive: bool = False) -> List[Tuple]:
    conn = db_connect(db_path)
    cur = conn.cursor()

    if include_inactive:
        cur.execute(sql("""
            SELECT id, payer_type, payer_id, payment_date, amount, COALESCE(note,''), is_active
            FROM payments
            ORDER BY date(payment_date) DESC, id DESC
            LIMIT 1000
        """)
        rows = cur.fetchall()
        conn.close()
        return rows

    cur.execute(sql("""
        SELECT id, payer_type, payer_id, payment_date, amount, COALESCE(note,'')
        FROM payments
        WHERE is_active=1
        ORDER BY date(payment_date) DESC, id DESC
        LIMIT 1000
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def list_payments_for_customer(db_path: str, customer_id: int, include_inactive: bool = False) -> List[Tuple]:
    conn = db_connect(db_path)
    cur = conn.cursor()
    if include_inactive:
        cur.execute(sql("""
            SELECT id, payer_type, payer_id, payment_date, amount, COALESCE(note,''), is_active
            FROM payments
            WHERE payer_type='Customer' AND payer_id=?
            ORDER BY date(payment_date) DESC, id DESC
            LIMIT 1000
        """), (int(customer_id),))
        rows = cur.fetchall()
        conn.close()
        return rows

    cur.execute(sql("""
        SELECT id, payer_type, payer_id, payment_date, amount, COALESCE(note,'')
        FROM payments
        WHERE payer_type='Customer' AND payer_id=? AND is_active=1
        ORDER BY date(payment_date) DESC, id DESC
        LIMIT 1000
    """), (int(customer_id),))
    rows = cur.fetchall()
    conn.close()
    return rows

def payment_display_target(db_path: str, payer_type: str, payer_id: int) -> str:
    conn = db_connect(db_path)
    cur = conn.cursor()
    if payer_type == "Customer":
        cur.execute(sql("SELECT name FROM customers WHERE id=?", (int(payer_id),))
        r = cur.fetchone()
        conn.close()
        return r[0] if r else f"Customer #{payer_id}"
    else:
        cur.execute(sql("SELECT family_name FROM families WHERE id=?", (int(payer_id),))
        r = cur.fetchone()
        conn.close()
        return r[0] if r else f"Family #{payer_id}"

def update_payment_note(db_path: str, payment_id: int, new_note: str):
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        UPDATE payments
        SET note=?
        WHERE id=? AND is_active=1
    """, ((new_note or "").strip(), int(payment_id)))
    conn.commit()
    conn.close()

def void_payment(db_path: str, payment_id: int):
    """
    Soft-delete payment + allocations, and reverse their effects on dues.
    Safe constraints:
    - Only void active payment.
    """
    conn = db_connect(db_path)
    cur = conn.cursor()

    cur.execute(sql("SELECT is_active FROM payments WHERE id=?", (int(payment_id),))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise ValueError("Payment not found.")
    if int(r[0]) != 1:
        conn.close()
        raise ValueError("Payment is already voided.")

    cur.execute(sql("""
        SELECT id, due_id, applied_amount
        FROM payment_allocations
        WHERE payment_id=? AND is_active=1
        ORDER BY id ASC
    """, (int(payment_id),))
    allocs = cur.fetchall()

    for alloc_id, due_id, applied_amount in allocs:
        applied_amount = float(applied_amount)

        cur.execute(sql("SELECT amount_due, paid_amount FROM dues WHERE id=?", (int(due_id),))
        dr = cur.fetchone()
        if not dr:
            continue
        amount_due, paid_amount = float(dr[0]), float(dr[1])

        new_paid = paid_amount - applied_amount
        if new_paid < -0.00001:
            conn.close()
            raise ValueError("Unsafe void: would make a due negative (data inconsistency).")

        if new_paid <= 0.00001:
            cur.execute(sql("""
                UPDATE dues
                SET paid_amount=0, status='Due', paid_date=NULL
                WHERE id=?
            """, (int(due_id),))
        else:
            if new_paid >= amount_due - 0.00001:
                cur.execute(sql("""
                    UPDATE dues
                    SET paid_amount=?, status='Paid'
                    WHERE id=?
                """, (amount_due, int(due_id)))
            else:
                cur.execute(sql("""
                    UPDATE dues
                    SET paid_amount=?, status='Due', paid_date=NULL
                    WHERE id=?
                """, (new_paid, int(due_id)))

        cur.execute(sql("UPDATE payment_allocations SET is_active=0 WHERE id=?", (int(alloc_id),))

    cur.execute(sql("UPDATE payments SET is_active=0 WHERE id=?", (int(payment_id),))

    conn.commit()
    conn.close()

# =========================
# COMPANY SELECTOR
# =========================
def simple_input(parent, title):
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("360x170")
    win.resizable(False, False)

    tk.Label(win, text=title).pack(pady=10)
    entry = tk.Entry(win, width=45)
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
# UI HELPERS: Editable Treeview cell
# =========================
class TreeCellEditor:
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
        try:
            val = money(new_val)
            self.tree.set(self.item_id, self.col, fmt2(val) if val != 0 else "0.00")
        except Exception:
            pass
        self.end_edit()

    def end_edit(self):
        if self.entry:
            self.entry.destroy()
        self.entry = None
        self.item_id = None
        self.col = None

# =========================
# DASHBOARD QUERIES (soft deletes + deposits)
# =========================
def dashboard_summary(db_path: str) -> Dict[str, float]:
    conn = db_connect(db_path)
    cur = conn.cursor()

    def one(sql: str, params=()):
        cur.execute(sql(sql, params)
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else 0

    customers = one("SELECT COUNT(*) FROM customers WHERE is_active=1")
    families = one("SELECT COUNT(*) FROM families WHERE is_active=1")
    plans = one("SELECT COUNT(*) FROM plans WHERE is_active=1")

    dues_total = one("""
        SELECT COUNT(*)
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE c.is_active=1 AND p.is_active=1
    """)

    open_dues = one("""
        SELECT COUNT(*)
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE d.status!='Paid' AND c.is_active=1 AND p.is_active=1
    """)

    total_owed = one("""
        SELECT COALESCE(SUM(d.amount_due - d.paid_amount),0)
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE d.status!='Paid' AND c.is_active=1 AND p.is_active=1
    """)

    total_paid = one("""
        SELECT COALESCE(SUM(d.paid_amount),0)
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE c.is_active=1 AND p.is_active=1
    """)

    payments_count = one("SELECT COUNT(*) FROM payments WHERE is_active=1")
    payments_sum = one("SELECT COALESCE(SUM(amount),0) FROM payments WHERE is_active=1")

    deposits_sum = one("""
        SELECT COALESCE(SUM(deposit_amount),0)
        FROM plans
        WHERE is_active=1 AND deposit_is_active=1
    """)

    conn.close()
    payments_sum = float(payments_sum)
    deposits_sum = float(deposits_sum)
    return {
        "customers": float(customers),
        "families": float(families),
        "plans": float(plans),
        "dues_total": float(dues_total),
        "open_dues": float(open_dues),
        "total_owed": float(total_owed),
        "total_paid": float(total_paid),
        "payments_count": float(payments_count),
        "payments_sum": payments_sum,
        "deposits_sum": deposits_sum,
        "cash_received": payments_sum + deposits_sum,
    }

def dashboard_overdue(db_path: str) -> List[Tuple[int, str, str, float]]:
    today = today_str()
    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        SELECT d.id, c.name, d.due_date, (d.amount_due - d.paid_amount) AS owed
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE d.status!='Paid'
          AND date(d.due_date) < date(?)
          AND c.is_active=1
          AND p.is_active=1
        ORDER BY date(d.due_date) ASC, d.id ASC
        LIMIT 200
    """, (today,))
    rows = cur.fetchall()
    conn.close()
    return [(int(r[0]), str(r[1]), str(r[2]), float(r[3])) for r in rows]

def dashboard_upcoming(db_path: str, days_ahead: int = 30) -> List[Tuple[int, str, str, float]]:
    start = today_str()
    end = (datetime.now() + timedelta(days=days_ahead)).strftime(DATE_FMT)

    conn = db_connect(db_path)
    cur = conn.cursor()
    cur.execute(sql("""
        SELECT d.id, c.name, d.due_date, (d.amount_due - d.paid_amount) AS owed
        FROM dues d
        JOIN customers c ON c.id=d.customer_id
        JOIN plans p ON p.id=d.plan_id
        WHERE d.status!='Paid'
          AND date(d.due_date) >= date(?)
          AND date(d.due_date) <= date(?)
          AND c.is_active=1
          AND p.is_active=1
        ORDER BY date(d.due_date) ASC, d.id ASC
        LIMIT 200
    """, (start, end))
    rows = cur.fetchall()
    conn.close()
    return [(int(r[0]), str(r[1]), str(r[2]), float(r[3])) for r in rows]

# =========================
# MAIN APP
# =========================
def launch_app(state: AppState):
    company_name = get_setting(state.db_path, "company_name", "Payment Tracker")

    app = tk.Tk()
    app.title(company_name)
    app.geometry("1380x900")

    top = tk.Frame(app)
    top.pack(fill="x", padx=10, pady=8)
    tk.Label(top, text=f"Company: {company_name}", font=("Arial", 14, "bold")).pack(side="left")
    tk.Label(top, text=f"DB: {state.db_path}", fg="gray").pack(side="left", padx=15)

    nb = ttk.Notebook(app)
    nb.pack(fill="both", expand=True, padx=10, pady=10)

    tab_dashboard = ttk.Frame(nb)
    tab_customers = ttk.Frame(nb)
    tab_families = ttk.Frame(nb)
    tab_plans = ttk.Frame(nb)
    tab_payments = ttk.Frame(nb)

    nb.add(tab_dashboard, text="A) Dashboard")
    nb.add(tab_customers, text="B) Customers")
    nb.add(tab_families, text="C) Family Groups (Optional)")
    nb.add(tab_plans, text="D) Plans & Dues")
    nb.add(tab_payments, text="E/F) Payments (Auto + Manual) + History")

    def add_row(parent, label, default=""):
        row = tk.Frame(parent)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text=label, width=22, anchor="w").pack(side="left")
        ent = tk.Entry(row, width=55)
        ent.pack(side="left")
        if default:
            ent.insert(0, default)
        return ent

    # =========================
    # TAB A: DASHBOARD
    # =========================
    dash_top = ttk.Frame(tab_dashboard)
    dash_top.pack(fill="x", padx=10, pady=10)

    ttk.Label(dash_top, text="Company Dashboard", font=("Arial", 16, "bold")).pack(side="left")

    dash_btns = ttk.Frame(dash_top)
    dash_btns.pack(side="right")

    dash_cards = ttk.LabelFrame(tab_dashboard, text="Summary")
    dash_cards.pack(fill="x", padx=10, pady=(0, 10))

    card_grid = ttk.Frame(dash_cards)
    card_grid.pack(fill="x", padx=10, pady=10)

    dash_vals: Dict[str, tk.Label] = {}

    def make_card(parent, title: str, key: str):
        frame = ttk.Frame(parent, relief="ridge", padding=10)
        ttk.Label(frame, text=title).pack(anchor="w")
        lbl = tk.Label(frame, text="0", font=("Arial", 14, "bold"))
        lbl.pack(anchor="w", pady=(6, 0))
        dash_vals[key] = lbl
        return frame

    cards = [
        ("Customers", "customers"),
        ("Families", "families"),
        ("Plans", "plans"),
        ("Total Dues", "dues_total"),
        ("Open Dues", "open_dues"),
        ("Total Owed (Open)", "total_owed"),
        ("Total Paid", "total_paid"),
        ("Payments (Count)", "payments_count"),
        ("Payments (Sum)", "payments_sum"),
        ("Deposits (Sum)", "deposits_sum"),
        ("Cash Received", "cash_received"),
    ]

    for i, (title, key) in enumerate(cards):
        r = i // 3
        c = i % 3
        frame = make_card(card_grid, title, key)
        frame.grid(row=r, column=c, sticky="nsew", padx=8, pady=8)

    for c in range(3):
        card_grid.columnconfigure(c, weight=1)

    dash_mid = ttk.Frame(tab_dashboard)
    dash_mid.pack(fill="both", expand=True, padx=10, pady=10)

    left_tbl = ttk.LabelFrame(dash_mid, text="Overdue Open Dues")
    right_tbl = ttk.LabelFrame(dash_mid, text="Upcoming Open Dues (Next 30 Days)")
    left_tbl.pack(side="left", fill="both", expand=True, padx=(0, 10))
    right_tbl.pack(side="right", fill="both", expand=True)

    overdue_tree = ttk.Treeview(left_tbl, columns=("due_id", "customer", "due_date", "owed"), show="headings", height=10)
    for col, w in [("due_id", 90), ("customer", 260), ("due_date", 120), ("owed", 110)]:
        overdue_tree.heading(col, text=col.upper())
        overdue_tree.column(col, width=w, anchor="w")
    overdue_tree.pack(fill="both", expand=True, padx=10, pady=10)

    upcoming_tree = ttk.Treeview(right_tbl, columns=("due_id", "customer", "due_date", "owed"), show="headings", height=10)
    for col, w in [("due_id", 90), ("customer", 260), ("due_date", 120), ("owed", 110)]:
        upcoming_tree.heading(col, text=col.upper())
        upcoming_tree.column(col, width=w, anchor="w")
    upcoming_tree.pack(fill="both", expand=True, padx=10, pady=10)

    # ---- Dashboard Customer Search + Quick Actions ----
    dash_customer = ttk.LabelFrame(tab_dashboard, text="Dashboard Customer Search + Quick Payment")
    dash_customer.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    sr = tk.Frame(dash_customer)
    sr.pack(fill="x", padx=10, pady=10)

    tk.Label(sr, text="Search Customer (name/phone/email):").pack(side="left")
    dash_search_ent = tk.Entry(sr, width=40)
    dash_search_ent.pack(side="left", padx=8)

    dash_search_btn = ttk.Button(sr, text="Search")
    dash_search_btn.pack(side="left", padx=6)

    dash_pick = ttk.Combobox(sr, values=[], state="readonly", width=60)
    dash_pick.pack(side="left", padx=10)

    dash_load_btn = ttk.Button(sr, text="Load Customer")
    dash_load_btn.pack(side="left", padx=6)

    dash_detail = ttk.Frame(dash_customer)
    dash_detail.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    dash_left = ttk.Frame(dash_detail)
    dash_left.pack(side="left", fill="both", expand=True, padx=(0, 10))

    dash_right = ttk.Frame(dash_detail)
    dash_right.pack(side="right", fill="both", expand=True)

    # Customer info
    dash_info = ttk.LabelFrame(dash_left, text="Customer Info")
    dash_info.pack(fill="x", padx=0, pady=(0, 10))

    dash_info_lbl = tk.Label(dash_info, text="No customer loaded.", anchor="w", justify="left")
    dash_info_lbl.pack(fill="x", padx=10, pady=10)

    # Plans
    dash_plans_box = ttk.LabelFrame(dash_left, text="Plans (Active)")
    dash_plans_box.pack(fill="both", expand=True, padx=0, pady=(0, 10))

    dash_plans_tree = ttk.Treeview(dash_plans_box,
                                   columns=("id","plan_name","total","deposit","dep_date","dep_active","freq","recurring","first_due"),
                                   show="headings", height=6)
    cols_pl = [
        ("id",70),("plan_name",180),("total",90),("deposit",90),("dep_date",110),("dep_active",90),
        ("freq",140),("recurring",90),("first_due",110)
    ]
    for col, w in cols_pl:
        dash_plans_tree.heading(col, text=col.upper())
        dash_plans_tree.column(col, width=w, anchor="w")
    dash_plans_tree.pack(fill="both", expand=True, padx=10, pady=10)

    dash_plan_actions = tk.Frame(dash_plans_box)
    dash_plan_actions.pack(fill="x", padx=10, pady=(0, 10))

    dash_void_deposit_btn = ttk.Button(dash_plan_actions, text="Void Deposit (Selected Plan)")
    dash_void_deposit_btn.pack(side="left", padx=6)

    # Open dues + quick payment
    dash_pay_box = ttk.LabelFrame(dash_right, text="Quick Payment (Customer Only)")
    dash_pay_box.pack(fill="x", padx=0, pady=(0, 10))

    dash_pay_amt = add_row(dash_pay_box, "Amount ($)", "0")
    dash_pay_date = add_row(dash_pay_box, "Payment Date", today_str())
    dash_pay_note = add_row(dash_pay_box, "Note (optional)", "")

    dash_manual_row = tk.Frame(dash_pay_box)
    dash_manual_row.pack(fill="x", padx=10, pady=(8, 6))
    dash_manual_var = tk.BooleanVar(value=False)
    dash_manual_chk = ttk.Checkbutton(
        dash_manual_row,
        text="Manual Distribution (Advanced) — overrides auto allocation",
        variable=dash_manual_var
    )
    dash_manual_chk.pack(side="left")

    dash_open_dues = ttk.LabelFrame(dash_right, text="Loaded Customer — Open Dues (Auto/Manual Preview)")
    dash_open_dues.pack(fill="both", expand=True, padx=0, pady=(0, 10))

    dash_cols = ("due_id","due_date","owed","apply")
    dash_dues_tree = ttk.Treeview(dash_open_dues, columns=dash_cols, show="headings", height=8)
    for col, w in [("due_id", 90), ("due_date", 120), ("owed", 120), ("apply", 120)]:
        dash_dues_tree.heading(col, text=col.upper())
        dash_dues_tree.column(col, width=w, anchor="w")
    dash_dues_tree.pack(fill="both", expand=True, padx=10, pady=10)

    dash_editor = TreeCellEditor(dash_dues_tree)

    dash_pay_btns = tk.Frame(dash_pay_box)
    dash_pay_btns.pack(pady=8)

    dash_preview_btn = ttk.Button(dash_pay_btns, text="Preview Open Dues")
    dash_preview_btn.pack(side="left", padx=6)
    dash_autofill_btn = ttk.Button(dash_pay_btns, text="Auto-Fill (Oldest Due First)")
    dash_autofill_btn.pack(side="left", padx=6)
    dash_clear_btn = ttk.Button(dash_pay_btns, text="Clear APPLY")
    dash_clear_btn.pack(side="left", padx=6)
    dash_submit_btn = ttk.Button(dash_pay_btns, text="Record Payment")
    dash_submit_btn.pack(side="left", padx=6)

    # Payment history for loaded customer
    dash_hist = ttk.LabelFrame(dash_right, text="Loaded Customer — Payment History")
    dash_hist.pack(fill="both", expand=True, padx=0, pady=(0, 10))

    dash_hist_tree = ttk.Treeview(dash_hist, columns=("id","date","amount","note","status"),
                                  show="headings", height=8)
    for col, w in [("id", 70), ("date", 120), ("amount", 120), ("note", 420), ("status", 90)]:
        dash_hist_tree.heading(col, text=col.upper())
        dash_hist_tree.column(col, width=w, anchor="w")
    dash_hist_tree.pack(fill="both", expand=True, padx=10, pady=10)

    dash_hist_actions = tk.Frame(dash_hist)
    dash_hist_actions.pack(fill="x", padx=10, pady=(0, 10))

    dash_show_voided_var = tk.BooleanVar(value=False)
    dash_show_voided_chk = ttk.Checkbutton(dash_hist_actions, text="Show Voided", variable=dash_show_voided_var)
    dash_show_voided_chk.pack(side="left")

    dash_void_payment_btn = ttk.Button(dash_hist_actions, text="Void Selected Payment")
    dash_void_payment_btn.pack(side="left", padx=6)

    # Dashboard state
    dash_loaded_customer_id = {"id": None}

    def refresh_dashboard():
        s = dashboard_summary(state.db_path)
        dash_vals["customers"].config(text=str(int(s["customers"])))
        dash_vals["families"].config(text=str(int(s["families"])))
        dash_vals["plans"].config(text=str(int(s["plans"])))
        dash_vals["dues_total"].config(text=str(int(s["dues_total"])))
        dash_vals["open_dues"].config(text=str(int(s["open_dues"])))
        dash_vals["total_owed"].config(text=f"${fmt2(s['total_owed'])}")
        dash_vals["total_paid"].config(text=f"${fmt2(s['total_paid'])}")
        dash_vals["payments_count"].config(text=str(int(s["payments_count"])))
        dash_vals["payments_sum"].config(text=f"${fmt2(s['payments_sum'])}")
        dash_vals["deposits_sum"].config(text=f"${fmt2(s['deposits_sum'])}")
        dash_vals["cash_received"].config(text=f"${fmt2(s['cash_received'])}")

        clear_tree(overdue_tree)
        for due_id, cname, due_date, owed in dashboard_overdue(state.db_path):
            overdue_tree.insert("", "end", values=(due_id, cname, due_date, fmt2(owed)))

        clear_tree(upcoming_tree)
        for due_id, cname, due_date, owed in dashboard_upcoming(state.db_path, 30):
            upcoming_tree.insert("", "end", values=(due_id, cname, due_date, fmt2(owed)))

    ttk.Button(dash_btns, text="Refresh Dashboard", command=refresh_dashboard).pack()

    def dash_search():
        term = dash_search_ent.get().strip()
        rows = search_customers(state.db_path, term)
        dash_pick["values"] = [f"{cid} - {name}" for cid, name, *_ in rows]
        if rows:
            dash_pick.current(0)

    def dash_load_customer():
        pick = dash_pick.get().strip()
        if not pick:
            messagebox.showerror("Error", "Select a customer from the dropdown.")
            return
        cid = int(pick.split(" - ")[0])
        dash_loaded_customer_id["id"] = cid

        row = get_customer(state.db_path, cid)
        if not row:
            dash_info_lbl.config(text="Customer not found.")
            return
        _, name, phone, email, _is_active = row
        dash_info_lbl.config(text=f"ID: {cid}\nName: {name}\nPhone: {phone or ''}\nEmail: {email or ''}")

        # Plans
        clear_tree(dash_plans_tree)
        for p in list_customer_plans(state.db_path, cid):
            # returns: id, name, total, deposit, dep_date, freq, rec, first_due, deposit_is_active
            pid, pname, total, dep, depdate, freq, rec, firstdue, dep_active = p
            dash_plans_tree.insert(
                "", "end",
                values=(pid, pname, fmt2(total), fmt2(dep), depdate, "YES" if int(dep_active or 0) == 1 else "NO",
                        freq, fmt2(rec), firstdue)
            )

        dash_preview_open_dues()
        dash_refresh_customer_history()

    def dash_preview_open_dues():
        clear_tree(dash_dues_tree)
        cid = dash_loaded_customer_id["id"]
        if not cid:
            return
        rows = list_open_dues_for_customer(state.db_path, cid)
        for due_id, _cname, due_date, owed in rows:
            dash_dues_tree.insert("", "end", values=(int(due_id), due_date, fmt2(owed), "0.00"))

    def dash_autofill():
        dash_preview_open_dues()
        amt = money(dash_pay_amt.get())
        remaining = float(amt)
        for item in dash_dues_tree.get_children():
            if remaining <= 0:
                dash_dues_tree.set(item, "apply", "0.00")
                continue
            owed = money(dash_dues_tree.set(item, "owed"))
            apply_amt = min(owed, remaining)
            dash_dues_tree.set(item, "apply", fmt2(apply_amt))
            remaining -= apply_amt

    def dash_clear_apply():
        for item in dash_dues_tree.get_children():
            dash_dues_tree.set(item, "apply", "0.00")

    def dash_on_dues_double_click(event):
        if not dash_manual_var.get():
            return
        region = dash_dues_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item_id = dash_dues_tree.identify_row(event.y)
        col = dash_dues_tree.identify_column(event.x)
        if not item_id:
            return
        if col != "#4":
            return
        dash_editor.begin_edit(item_id, "apply")

    dash_dues_tree.bind("<Double-1>", dash_on_dues_double_click)

    def dash_reset_payment_fields():
        dash_pay_amt.delete(0, tk.END); dash_pay_amt.insert(0, "0")
        dash_pay_date.delete(0, tk.END); dash_pay_date.insert(0, today_str())
        dash_pay_note.delete(0, tk.END)
        dash_manual_var.set(False)
        dash_pay_amt.focus_set()
        dash_clear_apply()

    def dash_record_payment():
        cid = dash_loaded_customer_id["id"]
        if not cid:
            messagebox.showerror("Error", "Load a customer first.")
            return

        try:
            amt = money(dash_pay_amt.get())
            pdate = dash_pay_date.get().strip()
            note = (dash_pay_note.get() or "").strip()

            if not dash_manual_var.get():
                payment_id = auto_allocate(state.db_path, "Customer", cid, amt, pdate, note)
                messagebox.showinfo("Success", f"Payment recorded (Payment ID {payment_id}). Auto-applied (Oldest Due First).")
            else:
                if not dash_dues_tree.get_children():
                    dash_preview_open_dues()
                allocs: List[Tuple[int, float]] = []
                for item in dash_dues_tree.get_children():
                    due_id = int(dash_dues_tree.set(item, "due_id"))
                    apply_amt = money(dash_dues_tree.set(item, "apply"))
                    if apply_amt > 0:
                        allocs.append((due_id, apply_amt))
                payment_id = manual_allocate(state.db_path, "Customer", cid, amt, pdate, note, allocs)
                messagebox.showinfo("Success", f"Payment recorded (Payment ID {payment_id}). Applied using MANUAL distribution.")

            dash_reset_payment_fields()
            dash_preview_open_dues()
            dash_refresh_customer_history()
            refresh_dashboard()
            refresh_payment_targets()
            refresh_payments_history()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def dash_refresh_customer_history():
        clear_tree(dash_hist_tree)
        cid = dash_loaded_customer_id["id"]
        if not cid:
            return
        show_voided = dash_show_voided_var.get()
        rows = list_payments_for_customer(state.db_path, cid, include_inactive=show_voided)
        for r in rows:
            if show_voided:
                pid, _ptype, _payer_id, pdate, amt, note, is_active = r
                status = "ACTIVE" if int(is_active) == 1 else "VOIDED"
            else:
                pid, _ptype, _payer_id, pdate, amt, note = r
                status = "ACTIVE"
            dash_hist_tree.insert("", "end", values=(pid, pdate, fmt2(float(amt)), note, status))

    def dash_void_selected_payment():
        pid = get_selected_tree_id(dash_hist_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a payment first.")
            return
        if not messagebox.askyesno("Confirm", "VOID this payment (soft delete)?\n\nThis will REVERSE allocations from dues."):
            return
        try:
            void_payment(state.db_path, pid)
            dash_preview_open_dues()
            dash_refresh_customer_history()
            refresh_dashboard()
            refresh_payments_history()
            messagebox.showinfo("Done", "Payment voided and allocations reversed.")
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

    def dash_void_deposit_selected_plan():
        cid = dash_loaded_customer_id["id"]
        if not cid:
            messagebox.showerror("Error", "Load a customer first.")
            return
        pid = get_selected_tree_id(dash_plans_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a plan first.")
            return
        if not messagebox.askyesno("Confirm", "VOID this deposit?\n\nThis will (1) mark deposit voided and (2) create a new DUE for the deposit amount."):
            return

        # optional note prompt
        note = simple_input(app, "Void Note (optional)") or ""
        try:
            void_deposit(state.db_path, pid, note)
            messagebox.showinfo("Done", "Deposit voided. A new due was created for the deposit amount.")
            dash_load_customer()  # reload UI
            refresh_dashboard()
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

    dash_search_btn.config(command=dash_search)
    dash_load_btn.config(command=dash_load_customer)
    dash_preview_btn.config(command=dash_preview_open_dues)
    dash_autofill_btn.config(command=dash_autofill)
    dash_clear_btn.config(command=dash_clear_apply)
    dash_submit_btn.config(command=dash_record_payment)
    dash_void_payment_btn.config(command=dash_void_selected_payment)
    dash_void_deposit_btn.config(command=dash_void_deposit_selected_plan)
    dash_show_voided_chk.config(command=dash_refresh_customer_history)

    # =========================
    # TAB B: CUSTOMERS
    # =========================
    cust_add = ttk.LabelFrame(tab_customers, text="Add Customer")
    cust_add.pack(fill="x", padx=10, pady=10)

    ent_c_name = add_row(cust_add, "Name")
    ent_c_phone = add_row(cust_add, "Phone")
    ent_c_email = add_row(cust_add, "Email")

    cust_search = ttk.LabelFrame(tab_customers, text="Search (Active Only)")
    cust_search.pack(fill="both", expand=True, padx=10, pady=10)

    row_s = tk.Frame(cust_search)
    row_s.pack(fill="x", padx=10, pady=6)
    tk.Label(row_s, text="Search (name/phone/email):").pack(side="left")
    ent_search = tk.Entry(row_s, width=40)
    ent_search.pack(side="left", padx=8)

    cust_tree = ttk.Treeview(cust_search, columns=("id", "name", "phone", "email"), show="headings", height=16)
    for col, w in [("id", 70), ("name", 300), ("phone", 170), ("email", 320)]:
        cust_tree.heading(col, text=col.upper())
        cust_tree.column(col, width=w, anchor="w")
    cust_tree.pack(fill="both", expand=True, padx=10, pady=10)

    cust_actions = tk.Frame(cust_search)
    cust_actions.pack(fill="x", padx=10, pady=(0, 10))

    def refresh_customer_search():
        clear_tree(cust_tree)
        rows = search_customers(state.db_path, ent_search.get().strip())
        for r in rows:
            cust_tree.insert("", "end", values=r)

    def reset_customer_entries():
        ent_c_name.delete(0, tk.END)
        ent_c_phone.delete(0, tk.END)
        ent_c_email.delete(0, tk.END)
        ent_c_name.focus_set()

    def on_add_customer():
        try:
            cid = add_customer(state.db_path, ent_c_name.get(), ent_c_phone.get(), ent_c_email.get())
            messagebox.showinfo("Success", f"Customer added (ID {cid})")
            reset_customer_entries()
            refresh_customer_search()
            refresh_family_customer_list()
            refresh_plan_customer_list()
            refresh_payment_targets()
            refresh_dashboard()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_edit_customer():
        cid = get_selected_tree_id(cust_tree, 0)
        if not cid:
            messagebox.showerror("Error", "Select a customer first.")
            return
        row = get_customer(state.db_path, cid)
        if not row:
            messagebox.showerror("Error", "Customer not found.")
            return

        win = tk.Toplevel(app)
        win.title("Edit Customer")
        win.geometry("520x250")
        win.resizable(False, False)

        _, name, phone, email, is_active = row
        if int(is_active) != 1:
            messagebox.showerror("Error", "Customer is inactive.")
            win.destroy()
            return

        e_name = add_row(win, "Name", name)
        e_phone = add_row(win, "Phone", phone or "")
        e_email = add_row(win, "Email", email or "")

        def save():
            try:
                update_customer(state.db_path, cid, e_name.get(), e_phone.get(), e_email.get())
                win.destroy()
                refresh_customer_search()
                refresh_family_customer_list()
                refresh_plan_customer_list()
                refresh_payment_targets()
                refresh_dashboard()
            except Exception as ex:
                messagebox.showerror("Error", str(ex))

        ttk.Button(win, text="Save Changes", command=save).pack(pady=12)
        win.grab_set()
        win.wait_window()

    def on_deactivate_customer():
        cid = get_selected_tree_id(cust_tree, 0)
        if not cid:
            messagebox.showerror("Error", "Select a customer first.")
            return
        if not messagebox.askyesno("Confirm", "Deactivate (soft delete) this customer?\n\nThis hides them but keeps history."):
            return
        try:
            deactivate_customer(state.db_path, cid)
            refresh_customer_search()
            refresh_family_customer_list()
            refresh_plan_customer_list()
            refresh_payment_targets()
            refresh_dashboard()
            messagebox.showinfo("Done", "Customer deactivated.")
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

    ttk.Button(cust_add, text="Add Customer", command=on_add_customer).pack(pady=8)
    ttk.Button(row_s, text="Search", command=refresh_customer_search).pack(side="left", padx=6)

    ttk.Button(cust_actions, text="Edit Selected", command=on_edit_customer).pack(side="left", padx=6)
    ttk.Button(cust_actions, text="Deactivate Selected (Soft)", command=on_deactivate_customer).pack(side="left", padx=6)

    # =========================
    # TAB C: FAMILIES
    # =========================
    fam_top = ttk.LabelFrame(tab_families, text="Create Family (Optional)")
    fam_top.pack(fill="x", padx=10, pady=10)

    ent_family_name = add_row(fam_top, "Family Name")

    fam_mid = tk.Frame(tab_families)
    fam_mid.pack(fill="both", expand=True, padx=10, pady=10)

    left_f = ttk.LabelFrame(fam_mid, text="Families (Active Only)")
    left_f.pack(side="left", fill="y", padx=(0, 10))

    right_f = ttk.LabelFrame(fam_mid, text="Members")
    right_f.pack(side="right", fill="both", expand=True)

    fam_tree = ttk.Treeview(left_f, columns=("id", "family_name"), show="headings", height=18)
    fam_tree.heading("id", text="ID")
    fam_tree.heading("family_name", text="FAMILY")
    fam_tree.column("id", width=70, anchor="w")
    fam_tree.column("family_name", width=260, anchor="w")
    fam_tree.pack(padx=10, pady=10)

    fam_actions = tk.Frame(left_f)
    fam_actions.pack(fill="x", padx=10, pady=(0, 10))

    members_tree = ttk.Treeview(right_f, columns=("id", "name", "phone", "email"), show="headings", height=12)
    for col, w in [("id", 70), ("name", 280), ("phone", 170), ("email", 320)]:
        members_tree.heading(col, text=col.upper())
        members_tree.column(col, width=w, anchor="w")
    members_tree.pack(fill="both", expand=True, padx=10, pady=10)

    member_actions = tk.Frame(right_f)
    member_actions.pack(fill="x", padx=10, pady=(0, 10))

    add_member_box = ttk.LabelFrame(right_f, text="Add Member to Selected Family")
    add_member_box.pack(fill="x", padx=10, pady=(0, 10))

    customer_pick = ttk.Combobox(add_member_box, values=[], state="readonly", width=70)
    customer_pick.pack(side="left", padx=10, pady=10)

    selected_family_id = {"id": None}

    def refresh_family_list():
        clear_tree(fam_tree)
        for fid, fn in list_families(state.db_path):
            fam_tree.insert("", "end", values=(fid, fn))

    def refresh_family_customer_list():
        rows = search_customers(state.db_path, "")
        values = [f"{cid} - {name}" for cid, name, *_ in rows]
        customer_pick["values"] = values

    def reset_family_entries():
        ent_family_name.delete(0, tk.END)
        ent_family_name.focus_set()

    def on_create_family():
        try:
            fid = create_family(state.db_path, ent_family_name.get())
            messagebox.showinfo("Success", f"Family created (ID {fid})")
            reset_family_entries()
            refresh_family_list()
            refresh_payment_targets()
            refresh_dashboard()
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

    def on_edit_family():
        fid = get_selected_tree_id(fam_tree, 0)
        if not fid:
            messagebox.showerror("Error", "Select a family first.")
            return
        win = tk.Toplevel(app)
        win.title("Edit Family")
        win.geometry("520x200")
        win.resizable(False, False)

        fams = list_families(state.db_path, include_inactive=True)
        current = None
        for f in fams:
            if int(f[0]) == int(fid):
                current = f
                break
        if not current:
            messagebox.showerror("Error", "Family not found.")
            win.destroy()
            return

        _, fname, is_active = current
        if int(is_active) != 1:
            messagebox.showerror("Error", "Family is inactive.")
            win.destroy()
            return

        e_name = add_row(win, "Family Name", fname)

        def save():
            try:
                update_family(state.db_path, fid, e_name.get())
                win.destroy()
                refresh_family_list()
                refresh_payment_targets()
                refresh_dashboard()
            except Exception as ex:
                messagebox.showerror("Error", str(ex))

        ttk.Button(win, text="Save Changes", command=save).pack(pady=12)
        win.grab_set()
        win.wait_window()

    def on_deactivate_family():
        fid = get_selected_tree_id(fam_tree, 0)
        if not fid:
            messagebox.showerror("Error", "Select a family first.")
            return
        if not messagebox.askyesno("Confirm", "Deactivate (soft delete) this family?\n\nYou must remove members and void payments first."):
            return
        try:
            deactivate_family(state.db_path, fid)
            refresh_family_list()
            clear_tree(members_tree)
            refresh_payment_targets()
            refresh_dashboard()
            messagebox.showinfo("Done", "Family deactivated.")
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

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
        refresh_dashboard()
        messagebox.showinfo("Success", "Member added to family.")

    def on_remove_member():
        fid = selected_family_id["id"]
        if not fid:
            messagebox.showerror("Error", "Select a family first.")
            return
        cid = get_selected_tree_id(members_tree, 0)
        if not cid:
            messagebox.showerror("Error", "Select a member first.")
            return
        if not messagebox.askyesno("Confirm", "Remove this member from the family?"):
            return
        remove_member_from_family(state.db_path, fid, cid)
        on_family_select()
        refresh_payment_targets()
        refresh_dashboard()

    ttk.Button(fam_actions, text="Edit Selected", command=on_edit_family).pack(side="left", padx=6)
    ttk.Button(fam_actions, text="Deactivate Selected (Soft)", command=on_deactivate_family).pack(side="left", padx=6)

    ttk.Button(add_member_box, text="Add Member", command=on_add_member).pack(side="left", padx=10)
    ttk.Button(member_actions, text="Remove Selected Member", command=on_remove_member).pack(side="left", padx=6)

    # =========================
    # TAB D: PLANS & DUES
    # =========================
    plan_box = ttk.LabelFrame(tab_plans, text="Add Plan (Multiple plans allowed)")
    plan_box.pack(fill="x", padx=10, pady=10)

    plan_customer_pick = ttk.Combobox(plan_box, values=[], state="readonly", width=70)
    plan_customer_pick.pack(padx=10, pady=(10, 2), anchor="w")

    ent_plan_name = add_row(plan_box, "Plan Name (optional)")
    ent_plan_total = add_row(plan_box, "Plan Total ($)")
    ent_deposit_amt = add_row(plan_box, "Deposit Amount ($)", "0")
    ent_deposit_date = add_row(plan_box, "Deposit Date (YYYY-MM-DD)", today_str())

    row_freq = tk.Frame(plan_box)
    row_freq.pack(fill="x", padx=10, pady=4)
    tk.Label(row_freq, text="Frequency", width=22, anchor="w").pack(side="left")
    freq_var = tk.StringVar(value="Monthly (Same Day)")
    freq_dd = ttk.Combobox(row_freq, textvariable=freq_var, values=list(FREQ_MAP_DAYS.keys()), width=52, state="readonly")
    freq_dd.pack(side="left")

    ent_recurring_amt = add_row(plan_box, "Recurring Amount ($)")
    ent_first_due = add_row(plan_box, "First Due Date (YYYY-MM-DD)")

    plan_view = ttk.LabelFrame(tab_plans, text="Customer Plans + Dues (Active Plans Only)")
    plan_view.pack(fill="both", expand=True, padx=10, pady=10)

    plan_tree = ttk.Treeview(plan_view, columns=("id","plan_name","total","deposit","dep_date","dep_active","freq","recurring","first_due"),
                             show="headings", height=6)
    for col, w in [
        ("id",70),("plan_name",220),("total",110),("deposit",110),("dep_date",120),("dep_active",90),
        ("freq",160),("recurring",120),("first_due",120)
    ]:
        plan_tree.heading(col, text=col.upper())
        plan_tree.column(col, width=w, anchor="w")
    plan_tree.pack(fill="x", padx=10, pady=8)

    plan_actions = tk.Frame(plan_view)
    plan_actions.pack(fill="x", padx=10, pady=(0, 10))

    dues_tree = ttk.Treeview(plan_view, columns=("due_id","due_date","amount_due","paid_amount","status","paid_date","plan_id","source"),
                             show="headings", height=10)
    for col, w in [
        ("due_id",80),("due_date",120),("amount_due",120),("paid_amount",120),("status",100),
        ("paid_date",120),("plan_id",80),("source",120)
    ]:
        dues_tree.heading(col, text=col.upper())
        dues_tree.column(col, width=w, anchor="w")
    dues_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    current_plan_customer_id = {"id": None}

    def refresh_plan_customer_list():
        rows = search_customers(state.db_path, "")
        values = [f"{cid} - {name}" for cid, name, *_ in rows]
        plan_customer_pick["values"] = values

    def reset_plan_entries():
        ent_plan_name.delete(0, tk.END)
        ent_plan_total.delete(0, tk.END)
        ent_deposit_amt.delete(0, tk.END); ent_deposit_amt.insert(0, "0")
        ent_deposit_date.delete(0, tk.END); ent_deposit_date.insert(0, today_str())
        freq_var.set("Monthly (Same Day)")
        ent_recurring_amt.delete(0, tk.END)
        ent_first_due.delete(0, tk.END)
        ent_plan_name.focus_set()

    def refresh_plan_view(customer_id: int):
        current_plan_customer_id["id"] = int(customer_id)
        clear_tree(plan_tree)
        clear_tree(dues_tree)

        for p in list_customer_plans(state.db_path, customer_id):
            pid, pname, total, dep, depdate, freq, rec, firstdue, dep_active = p
            plan_tree.insert("", "end", values=(pid, pname, fmt2(total), fmt2(dep), depdate, "YES" if int(dep_active or 0) == 1 else "NO",
                                                freq, fmt2(rec), firstdue))

        for d in list_customer_dues(state.db_path, customer_id):
            due_id, due_date, amt_due, paid_amt, status, paid_date, plan_id, source = d
            dues_tree.insert("", "end", values=(due_id, due_date, fmt2(amt_due), fmt2(paid_amt), status, paid_date, plan_id, source))

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
            reset_plan_entries()
            refresh_plan_view(cid)
            refresh_payment_targets()
            refresh_dashboard()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_edit_plan_name():
        pid = get_selected_tree_id(plan_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a plan first.")
            return
        win = tk.Toplevel(app)
        win.title("Edit Plan Name")
        win.geometry("520x200")
        win.resizable(False, False)

        current_name = plan_tree.item(plan_tree.selection()[0])["values"][1] if plan_tree.selection() else ""
        e_name = add_row(win, "Plan Name", current_name)

        def save():
            try:
                update_plan_name(state.db_path, pid, e_name.get())
                win.destroy()
                cid = current_plan_customer_id["id"]
                if cid:
                    refresh_plan_view(cid)
                refresh_dashboard()
            except Exception as ex:
                messagebox.showerror("Error", str(ex))

        ttk.Button(win, text="Save Changes", command=save).pack(pady=12)
        win.grab_set()
        win.wait_window()

    def on_deactivate_plan():
        pid = get_selected_tree_id(plan_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a plan first.")
            return
        if not messagebox.askyesno("Confirm", "Deactivate (soft delete) this plan?\n\nBlocked if plan has paid dues history."):
            return
        try:
            deactivate_plan(state.db_path, pid)
            cid = current_plan_customer_id["id"]
            if cid:
                refresh_plan_view(cid)
            refresh_dashboard()
            messagebox.showinfo("Done", "Plan deactivated.")
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

    def on_void_plan_deposit():
        pid = get_selected_tree_id(plan_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a plan first.")
            return
        if not messagebox.askyesno("Confirm", "VOID this plan deposit?\n\nThis will create a new DUE for the deposit amount."):
            return
        note = simple_input(app, "Void Note (optional)") or ""
        try:
            void_deposit(state.db_path, pid, note)
            cid = current_plan_customer_id["id"]
            if cid:
                refresh_plan_view(cid)
            refresh_dashboard()
            messagebox.showinfo("Done", "Deposit voided. A due was created for the deposit amount.")
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

    ttk.Button(plan_box, text="Create Plan + Generate Dues", command=on_add_plan).pack(pady=10)
    ttk.Button(plan_actions, text="Edit Selected Plan Name", command=on_edit_plan_name).pack(side="left", padx=6)
    ttk.Button(plan_actions, text="Void Deposit (Selected Plan)", command=on_void_plan_deposit).pack(side="left", padx=6)
    ttk.Button(plan_actions, text="Deactivate Selected Plan (Soft)", command=on_deactivate_plan).pack(side="left", padx=6)

    # =========================
    # TAB E/F: PAYMENTS + HISTORY
    # =========================
    pay_box = ttk.LabelFrame(tab_payments, text="Record Payment (Auto default: Oldest Due First)")
    pay_box.pack(fill="x", padx=10, pady=10)

    row_target = tk.Frame(pay_box)
    row_target.pack(fill="x", padx=10, pady=(10, 4))
    tk.Label(row_target, text="Pay For:", width=12, anchor="w").pack(side="left")

    payer_type_var = tk.StringVar(value="Customer")
    payer_type_dd = ttk.Combobox(row_target, textvariable=payer_type_var, values=["Customer", "Family"], state="readonly", width=14)
    payer_type_dd.pack(side="left", padx=6)

    payer_target_dd = ttk.Combobox(row_target, values=[], state="readonly", width=70)
    payer_target_dd.pack(side="left", padx=6)

    ent_pay_amt = add_row(pay_box, "Amount ($)", "0")
    ent_pay_date = add_row(pay_box, "Payment Date", today_str())
    ent_pay_note = add_row(pay_box, "Note (optional)", "")

    row_manual = tk.Frame(pay_box)
    row_manual.pack(fill="x", padx=10, pady=(8, 6))
    manual_var = tk.BooleanVar(value=False)
    chk_manual = ttk.Checkbutton(row_manual, text="Manual Distribution (Advanced) — overrides auto allocation", variable=manual_var)
    chk_manual.pack(side="left")

    pay_result = ttk.LabelFrame(tab_payments, text="Open dues (preview / manual distribution)")
    pay_result.pack(fill="both", expand=True, padx=10, pady=10)

    cols = ("due_id", "customer", "due_date", "owed", "apply")
    preview_tree = ttk.Treeview(pay_result, columns=cols, show="headings", height=10)
    preview_tree.heading("due_id", text="DUE_ID")
    preview_tree.heading("customer", text="CUSTOMER")
    preview_tree.heading("due_date", text="DUE_DATE")
    preview_tree.heading("owed", text="OWED")
    preview_tree.heading("apply", text="APPLY (double-click to edit)")

    preview_tree.column("due_id", width=90, anchor="w")
    preview_tree.column("customer", width=300, anchor="w")
    preview_tree.column("due_date", width=140, anchor="w")
    preview_tree.column("owed", width=120, anchor="w")
    preview_tree.column("apply", width=140, anchor="w")
    preview_tree.pack(fill="both", expand=True, padx=10, pady=10)

    editor = TreeCellEditor(preview_tree)

    def refresh_payment_targets():
        cust = search_customers(state.db_path, "")
        cust_values = [f"{cid} - {name}" for cid, name, *_ in cust]
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

    def reset_payment_entries():
        ent_pay_amt.delete(0, tk.END); ent_pay_amt.insert(0, "0")
        ent_pay_date.delete(0, tk.END); ent_pay_date.insert(0, today_str())
        ent_pay_note.delete(0, tk.END)
        manual_var.set(False)
        ent_pay_amt.focus_set()
        clear_apply_column()

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
        col = preview_tree.identify_column(event.x)
        if not item_id:
            return
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
                payment_id = auto_allocate(state.db_path, ptype, pid, amt, pdate, note)
                messagebox.showinfo("Success", f"Payment recorded (Payment ID {payment_id}). Auto-applied (Oldest Due First).")
            else:
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

            reset_payment_entries()
            load_open_dues_into_tree()
            refresh_payments_history()
            refresh_dashboard()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    btns = tk.Frame(pay_box)
    btns.pack(pady=8)

    ttk.Button(btns, text="Preview Open Dues", command=load_open_dues_into_tree).pack(side="left", padx=6)
    ttk.Button(btns, text="Auto-Fill (Oldest Due First)", command=auto_fill_oldest_first).pack(side="left", padx=6)
    ttk.Button(btns, text="Clear APPLY", command=clear_apply_column).pack(side="left", padx=6)
    ttk.Button(btns, text="Record Payment", command=record_payment).pack(side="left", padx=6)

    # History
    hist = ttk.LabelFrame(tab_payments, text="Payment History — Edit Note / Void (Soft Delete)")
    hist.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    pay_hist_tree = ttk.Treeview(hist, columns=("id","payer_type","target","date","amount","note","status"),
                                 show="headings", height=10)
    for col, w in [
        ("id", 80), ("payer_type", 110), ("target", 260), ("date", 120), ("amount", 120), ("note", 360), ("status", 90)
    ]:
        pay_hist_tree.heading(col, text=col.upper())
        pay_hist_tree.column(col, width=w, anchor="w")
    pay_hist_tree.pack(fill="both", expand=True, padx=10, pady=10)

    hist_actions = tk.Frame(hist)
    hist_actions.pack(fill="x", padx=10, pady=(0, 10))

    show_voided_var = tk.BooleanVar(value=False)
    chk_show_voided = ttk.Checkbutton(hist_actions, text="Show Voided", variable=show_voided_var)
    chk_show_voided.pack(side="left")

    def refresh_payments_history():
        clear_tree(pay_hist_tree)
        show_voided = show_voided_var.get()
        rows = list_payments(state.db_path, include_inactive=show_voided)
        for r in rows:
            if show_voided:
                pid, ptype, payer_id, pdate, amt, note, is_active = r
                status = "ACTIVE" if int(is_active) == 1 else "VOIDED"
            else:
                pid, ptype, payer_id, pdate, amt, note = r
                status = "ACTIVE"

            target = payment_display_target(state.db_path, ptype, int(payer_id))
            pay_hist_tree.insert("", "end", values=(pid, ptype, target, pdate, fmt2(float(amt)), note, status))

    def on_edit_payment_note():
        pid = get_selected_tree_id(pay_hist_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a payment first.")
            return
        current_note = pay_hist_tree.item(pay_hist_tree.selection()[0])["values"][5] if pay_hist_tree.selection() else ""

        win = tk.Toplevel(app)
        win.title("Edit Payment Note")
        win.geometry("700x220")
        win.resizable(False, False)

        tk.Label(win, text="Note:", anchor="w").pack(fill="x", padx=10, pady=(10, 4))
        txt = tk.Text(win, height=5, width=80)
        txt.pack(padx=10)
        txt.insert("1.0", current_note or "")

        def save():
            update_payment_note(state.db_path, pid, txt.get("1.0", "end").strip())
            win.destroy()
            refresh_payments_history()
            refresh_dashboard()

        ttk.Button(win, text="Save Note", command=save).pack(pady=10)
        win.grab_set()
        win.wait_window()

    def on_void_payment():
        pid = get_selected_tree_id(pay_hist_tree, 0)
        if not pid:
            messagebox.showerror("Error", "Select a payment first.")
            return
        if not messagebox.askyesno("Confirm", "VOID this payment (soft delete)?\n\nThis will REVERSE allocations from dues."):
            return
        try:
            void_payment(state.db_path, pid)
            refresh_payments_history()
            load_open_dues_into_tree()
            refresh_dashboard()
            messagebox.showinfo("Done", "Payment voided and allocations reversed.")
        except Exception as e:
            messagebox.showerror("Blocked", str(e))

    ttk.Button(hist_actions, text="Edit Selected Note", command=on_edit_payment_note).pack(side="left", padx=6)
    ttk.Button(hist_actions, text="Void Selected Payment (Soft)", command=on_void_payment).pack(side="left", padx=6)
    ttk.Button(hist_actions, text="Refresh History", command=refresh_payments_history).pack(side="left", padx=6)
    chk_show_voided.config(command=refresh_payments_history)

    # =========================
    # Cross-refresh helpers
    # =========================
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
    refresh_payments_history()
    refresh_dashboard()

    app.mainloop()
