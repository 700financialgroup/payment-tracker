import sqlite3
import csv
from datetime import datetime, timedelta

CSV_FILE = "DISPUTE LIST TRACKER - Sheet11.csv"
DB_FILE = "payments.db"

# =========================
# Helpers
# =========================
def parse_money(value):
    if not value:
        return 0.0
    return float(
        value.replace("$", "")
             .replace(",", "")
             .strip()
    )

# =========================
# Database Upgrade (SAFE)
# =========================
def upgrade_customers_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(customers)")
    columns = [col[1] for col in cursor.fetchall()]

    if "phone" not in columns:
        cursor.execute("ALTER TABLE customers ADD COLUMN phone TEXT")

    if "email" not in columns:
        cursor.execute("ALTER TABLE customers ADD COLUMN email TEXT")

    conn.commit()
    conn.close()

# =========================
# Import CSV
# =========================
def import_csv():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    with open(CSV_FILE, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            name = (row.get("Full Name") or "").strip()
            phone = (row.get("Phone Number") or "").strip()
            email = (row.get("E-Mail") or "").strip()

            # Skip empty rows
            if not name:
                continue

            plan_amount = parse_money(row.get("Payment Plan"))
            balance = parse_money(row.get("Remaining Balance"))
            deposit = parse_money(row.get("Deposit Amount Received"))

            # Skip if customer already exists
            cursor.execute(
                "SELECT id FROM customers WHERE name=? AND phone=?",
                (name, phone)
            )
            if cursor.fetchone():
                print(f"Skipping existing customer: {name}")
                continue

            interval_days = 30

            cursor.execute("""
                INSERT INTO customers (
                    name,
                    plan_amount,
                    balance,
                    payment_interval_days,
                    phone,
                    email
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                name,
                plan_amount,
                balance,
                interval_days,
                phone,
                email
            ))

            customer_id = cursor.lastrowid

            # Determine next due date
            try:
                next_due = datetime.strptime(
                    row.get("1st Payment"), "%m/%d/%Y"
                )
            except Exception:
                next_due = datetime.now() + timedelta(days=30)

            cursor.execute("""
                INSERT INTO payments (
                    customer_id,
                    payment_date,
                    amount,
                    next_due_date
                )
                VALUES (?, ?, ?, ?)
            """, (
                customer_id,
                datetime.now().strftime("%Y-%m-%d"),
                deposit,
                next_due.strftime("%Y-%m-%d")
            ))

            print(f"Imported: {name}")

    conn.commit()
    conn.close()
    print("IMPORT COMPLETE")

# =========================
# Run
# =========================
if __name__ == "__main__":
    upgrade_customers_table()
    import_csv()
