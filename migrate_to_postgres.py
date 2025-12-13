#!/usr/bin/env python3
"""
PostgreSQL Migration Script for Payment Tracker
Step 5: Production Readiness & Scalability
"""

# ⚠️ PYTHON VERSION RECOMMENDATION
# For production migration scripts, use Python 3.11 or 3.12
# Python 3.14+ is experimental and may cause psycopg2/packaging issues
#
# Setup recommended environment:
# python3.11 -m venv venv
# venv\Scripts\activate  # Windows
# pip install psycopg2-binary

import sqlite3
import psycopg2
import psycopg2.extras
import os
import sys
from datetime import datetime

class DatabaseMigrator:
    def __init__(self, sqlite_path='payments.db'):
        self.sqlite_path = sqlite_path
        self.pg_conn = None
        self.sqlite_conn = None

    def connect_sqlite(self):
        """Connect to SQLite database"""
        if not os.path.exists(self.sqlite_path):
            raise FileNotFoundError(f"SQLite database {self.sqlite_path} not found")

        self.sqlite_conn = sqlite3.connect(self.sqlite_path)
        self.sqlite_conn.row_factory = sqlite3.Row
        return self.sqlite_conn

    def connect_postgres(self, host='localhost', database='payment_tracker',
                        user='postgres', password='password', port=5432):
        """Connect to PostgreSQL database"""
        try:
            self.pg_conn = psycopg2.connect(
                host=host,
                database=database,
                user=user,
                password=password,
                port=port
            )
            self.pg_conn.autocommit = False
            return self.pg_conn
        except psycopg2.OperationalError as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            print("💡 Make sure PostgreSQL is running and credentials are correct")
            return None

    def create_postgres_schema(self):
        """Create PostgreSQL tables with improved schema"""
        if not self.pg_conn:
            return False

        cur = self.pg_conn.cursor()

        try:
            # ⚠️ WARNING: Destructive operation
            confirm = input("⚠️ This will DROP all PostgreSQL tables. Type YES to continue: ")
            if confirm != "YES":
                raise Exception("Migration cancelled by user")

            cur.execute("""
                DROP TABLE IF EXISTS payment_allocations CASCADE;
                DROP TABLE IF EXISTS payments CASCADE;
                DROP TABLE IF EXISTS dues CASCADE;
                DROP TABLE IF EXISTS plans CASCADE;
                DROP TABLE IF EXISTS family_members CASCADE;
                DROP TABLE IF EXISTS families CASCADE;
                DROP TABLE IF EXISTS users CASCADE;
                DROP TABLE IF EXISTS settings CASCADE;
                DROP TABLE IF EXISTS customers CASCADE;
                DROP TABLE IF EXISTS audit_log CASCADE;
            """)

            # Customers table with enhanced fields
            cur.execute("""
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
            """)

            # Families table
            cur.execute("""
                CREATE TABLE families (
                    id SERIAL PRIMARY KEY,
                    family_name VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Family members junction table
            cur.execute("""
                CREATE TABLE family_members (
                    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                    PRIMARY KEY (family_id, customer_id)
                );
            """)

            # Plans table with enhanced tracking
            cur.execute("""
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

                    CONSTRAINT chk_frequency CHECK (frequency IN ('weekly', 'biweekly', 'monthly', 'quarterly'))
                );

                CREATE INDEX idx_plans_customer ON plans(customer_id);
                CREATE INDEX idx_plans_active ON plans(is_active);
            """)

            # Dues table
            cur.execute("""
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
            """)

            # Payments table with enhanced tracking
            cur.execute("""
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
            """)

            # Payment allocations
            cur.execute("""
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
            """)

            # Users table for authentication
            cur.execute("""
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
            """)

            # Settings table
            cur.execute("""
                CREATE TABLE settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create audit log table for compliance
            cur.execute("""
                CREATE TABLE audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    action VARCHAR(100) NOT NULL,
                    table_name VARCHAR(50),
                    record_id INTEGER,
                    old_values JSONB,
                    new_values JSONB,
                    ip_address INET,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX idx_audit_user ON audit_log(user_id);
                CREATE INDEX idx_audit_action ON audit_log(action);
                CREATE INDEX idx_audit_created ON audit_log(created_at);
            """)

            self.pg_conn.commit()
            print("✅ PostgreSQL schema created successfully")
            return True

        except Exception as e:
            self.pg_conn.rollback()
            print(f"❌ Failed to create schema: {e}")
            return False

    def migrate_data(self):
        """Migrate all data from SQLite to PostgreSQL"""
        if not self.sqlite_conn or not self.pg_conn:
            print("❌ Database connections not established")
            return False

        try:
            # Migrate customers
            print("📊 Migrating customers...")
            sqlite_cur = self.sqlite_conn.cursor()
            pg_cur = self.pg_conn.cursor()

            sqlite_cur.execute("""
                SELECT id, name, phone, email, is_active,
                       created_at, created_at as updated_at
                FROM customers
            """)
            customers = sqlite_cur.fetchall()

            psycopg2.extras.execute_values(
                pg_cur,
                """
                INSERT INTO customers (id, name, phone, email, is_active, created_at, updated_at)
                VALUES %s
                """,
                customers
            )

            # Update sequence
            pg_cur.execute("SELECT setval('customers_id_seq', (SELECT MAX(id) FROM customers))")

            # Migrate families
            print("📊 Migrating families...")
            sqlite_cur.execute("""
                SELECT id, family_name, is_active,
                       created_at, created_at as updated_at
                FROM families
            """)
            families = sqlite_cur.fetchall()

            psycopg2.extras.execute_values(
                pg_cur,
                """
                INSERT INTO families (id, family_name, is_active, created_at, updated_at)
                VALUES %s
                """,
                families
            )
            pg_cur.execute("SELECT setval('families_id_seq', (SELECT MAX(id) FROM families))")

            # Migrate family members
            print("📊 Migrating family members...")
            sqlite_cur.execute("SELECT family_id, customer_id FROM family_members")
            family_members = sqlite_cur.fetchall()

            if family_members:
                psycopg2.extras.execute_values(
                    pg_cur,
                    "INSERT INTO family_members (family_id, customer_id) VALUES %s",
                    family_members
                )

            # Migrate plans
            print("📊 Migrating plans...")
            sqlite_cur.execute("""
                SELECT id, customer_id, plan_name, plan_total, deposit_amount,
                       deposit_date, deposit_is_active, deposit_voided_at,
                       deposit_void_note, frequency, recurring_amount,
                       first_due_date, is_active, created_at, created_at as updated_at
                FROM plans
            """)
            plans = sqlite_cur.fetchall()

            psycopg2.extras.execute_values(
                pg_cur,
                """
                INSERT INTO plans (id, customer_id, plan_name, plan_total, deposit_amount,
                                 deposit_date, deposit_is_active, deposit_voided_at,
                                 deposit_void_note, frequency, recurring_amount,
                                 first_due_date, is_active, created_at, updated_at)
                VALUES %s
                """,
                plans
            )
            pg_cur.execute("SELECT setval('plans_id_seq', (SELECT MAX(id) FROM plans))")

            # Migrate dues
            print("📊 Migrating dues...")
            sqlite_cur.execute("""
                SELECT id, customer_id, plan_id, due_date, amount_due,
                       paid_amount, status, paid_date, source, created_at
                FROM dues
            """)
            dues = sqlite_cur.fetchall()

            psycopg2.extras.execute_values(
                pg_cur,
                """
                INSERT INTO dues (id, customer_id, plan_id, due_date, amount_due,
                                paid_amount, status, paid_date, source, created_at)
                VALUES %s
                """,
                dues
            )
            pg_cur.execute("SELECT setval('dues_id_seq', (SELECT MAX(id) FROM dues))")

            # Migrate payments
            print("📊 Migrating payments...")
            sqlite_cur.execute("""
                SELECT id, payer_type, payer_id, payment_date, amount,
                       note, is_active, created_at, created_at as updated_at
                FROM payments
            """)
            payments = sqlite_cur.fetchall()

            psycopg2.extras.execute_values(
                pg_cur,
                """
                INSERT INTO payments (id, payer_type, payer_id, payment_date, amount,
                                    note, is_active, created_at, updated_at)
                VALUES %s
                """,
                payments
            )
            pg_cur.execute("SELECT setval('payments_id_seq', (SELECT MAX(id) FROM payments))")

            # Migrate payment allocations
            print("📊 Migrating payment allocations...")
            sqlite_cur.execute("""
                SELECT id, payment_id, due_id, applied_amount, is_active, created_at
                FROM payment_allocations
            """)
            allocations = sqlite_cur.fetchall()

            if allocations:
                psycopg2.extras.execute_values(
                    pg_cur,
                    """
                    INSERT INTO payment_allocations (id, payment_id, due_id, applied_amount,
                                                   is_active, created_at)
                    VALUES %s
                    """,
                    allocations
                )
                pg_cur.execute("SELECT setval('payment_allocations_id_seq', (SELECT MAX(id) FROM payment_allocations))")

            # Migrate settings
            print("📊 Migrating settings...")
            sqlite_cur.execute("""
                SELECT key, value
                FROM settings
            """)
            settings = sqlite_cur.fetchall()

            if settings:
                psycopg2.extras.execute_values(
                    pg_cur,
                    "INSERT INTO settings (key, value) VALUES %s",
                    settings
                )

            self.pg_conn.commit()
            print("✅ Data migration completed successfully")
            return True

        except Exception as e:
            self.pg_conn.rollback()
            print(f"❌ Data migration failed: {e}")
            return False

    def verify_migration(self):
        """Verify that migration was successful"""
        if not self.pg_conn or not self.sqlite_conn:
            return False

        try:
            pg_cur = self.pg_conn.cursor()
            sqlite_cur = self.sqlite_conn.cursor()

            tables = [
                'customers',
                'families',
                'family_members',
                'plans',
                'dues',
                'payments',
                'payment_allocations',
                'settings'
            ]

            print("\n🔍 MIGRATION VERIFICATION")
            print("-" * 50)

            all_ok = True

            for table in tables:
                sqlite_cur.execute(f"SELECT COUNT(*) FROM {table}")
                sqlite_count = sqlite_cur.fetchone()[0]

                pg_cur.execute(f"SELECT COUNT(*) FROM {table}")
                pg_count = pg_cur.fetchone()[0]

                status = "✅" if sqlite_count == pg_count else "❌"
                if sqlite_count != pg_count:
                    all_ok = False

                print(f"{status} {table:<22} SQLite: {sqlite_count:<6} PostgreSQL: {pg_count}")

            return all_ok

        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return False

    def close_connections(self):
        """Close all database connections"""
        if self.sqlite_conn:
            self.sqlite_conn.close()
        if self.pg_conn:
            self.pg_conn.close()


def main():
    # Check Python version
    if sys.version_info >= (3, 14):
        print("⚠️ WARNING: Python 3.14+ detected")
        print("   For production use, consider Python 3.11 or 3.12")
        print("   Experimental versions may cause psycopg2 issues\n")

    print("🚀 PAYMENT TRACKER - STEP 5: PostgreSQL Migration")
    print("=" * 55)

    migrator = DatabaseMigrator()

    # Connect to SQLite
    print("\n1️⃣ Connecting to SQLite database...")
    try:
        migrator.connect_sqlite()
        print("✅ SQLite connection established")
    except Exception as e:
        print(f"❌ SQLite connection failed: {e}")
        return

    # Connect to PostgreSQL
    print("\n2️⃣ Connecting to PostgreSQL database...")
    # Note: Update these credentials for your PostgreSQL setup
    pg_conn = migrator.connect_postgres(
        host='localhost',
        database='payment_tracker',
        user='postgres',
        password='password',  # Change this to your actual password
        port=5432
    )

    if not pg_conn:
        print("\n💡 PostgreSQL Setup Instructions:")
        print("   1. Install PostgreSQL: https://www.postgresql.org/download/")
        print("   2. Create database: CREATE DATABASE payment_tracker;")
        print("   3. Update credentials in this script")
        print("   4. Run this script again")
        migrator.close_connections()
        return

    # Create schema
    print("\n3️⃣ Creating PostgreSQL schema...")
    if not migrator.create_postgres_schema():
        migrator.close_connections()
        return

    # Migrate data
    print("\n4️⃣ Migrating data from SQLite to PostgreSQL...")
    if not migrator.migrate_data():
        migrator.close_connections()
        return

    # Verify migration
    print("\n5️⃣ Verifying migration...")
    migrator.verify_migration()

    migrator.close_connections()

    print("\n🎉 MIGRATION COMPLETE!")
    print("   Your application is now ready for production with PostgreSQL!")
    print("\n📝 Next Steps:")
    print("   1. Update your application config to use PostgreSQL")
    print("   2. Test all features with the new database")
    print("   3. Set up automated backups")
    print("   4. Configure connection pooling for better performance")


if __name__ == "__main__":
    main()