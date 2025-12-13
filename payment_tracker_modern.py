import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QLineEdit, QComboBox,
    QTextEdit, QCheckBox, QTreeWidget, QTreeWidgetItem, QSplitter, QFrame,
    QMessageBox, QInputDialog, QDateEdit, QSpinBox, QDoubleSpinBox, QGroupBox,
    QFormLayout, QProgressBar, QStatusBar, QDialog, QFileDialog
)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QFont, QIcon

# Import backend functions from the original file
# Assuming payment_tracker.py is in the same directory
import payment_tracker as backend

class PaymentTrackerApp(QMainWindow):
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.user_id = 1  # Default admin user
        self.user_role = "admin"
        self.init_ui()
        self.load_initial_data()
        self.start_alert_timer()

    def init_ui(self):
        self.setWindowTitle("Payment Tracker - Modern GUI")
        self.setGeometry(100, 100, 1400, 900)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Create tabs
        self.create_dashboard_tab()
        self.create_customers_tab()
        self.create_families_tab()
        self.create_plans_tab()
        self.create_payments_tab()
        self.create_reports_tab()
        self.create_settings_tab()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Database connected - Ready to use")

    def create_dashboard_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Dashboard")

        layout = QVBoxLayout(tab)

        # Summary cards
        summary_frame = QFrame()
        summary_layout = QHBoxLayout(summary_frame)

        self.total_customers_label = QLabel("Total Customers: 0")
        self.total_families_label = QLabel("Total Families: 0")
        self.total_plans_label = QLabel("Active Plans: 0")
        self.pending_dues_label = QLabel("Pending Dues: $0.00")

        for label in [self.total_customers_label, self.total_families_label,
                      self.total_plans_label, self.pending_dues_label]:
            label.setStyleSheet("font-size: 14px; padding: 10px; border: 1px solid #ccc; border-radius: 5px;")
            summary_layout.addWidget(label)

        layout.addWidget(summary_frame)

        # Recent payments table
        recent_payments_label = QLabel("Recent Payments")
        recent_payments_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(recent_payments_label)

        self.recent_payments_table = QTableWidget()
        self.recent_payments_table.setColumnCount(5)
        self.recent_payments_table.setHorizontalHeaderLabels(["Date", "Customer/Family", "Amount", "Note", "Status"])
        layout.addWidget(self.recent_payments_table)

    def create_customers_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Customers")

        layout = QVBoxLayout(tab)

        # Search and add controls
        controls_layout = QHBoxLayout()

        self.customer_search_input = QLineEdit()
        self.customer_search_input.setPlaceholderText("Search customers...")
        controls_layout.addWidget(self.customer_search_input)

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search_customers)
        controls_layout.addWidget(search_btn)

        add_customer_btn = QPushButton("Add Customer")
        add_customer_btn.clicked.connect(self.add_customer_dialog)
        controls_layout.addWidget(add_customer_btn)

        layout.addLayout(controls_layout)

        # Customers table
        self.customers_table = QTableWidget()
        self.customers_table.setColumnCount(5)
        self.customers_table.setHorizontalHeaderLabels(["ID", "Name", "Phone", "Email", "Status"])
        layout.addWidget(self.customers_table)

        # Customer details and actions
        details_layout = QHBoxLayout()

        # Customer info
        info_group = QGroupBox("Customer Details")
        info_layout = QFormLayout(info_group)

        self.customer_name_edit = QLineEdit()
        self.customer_phone_edit = QLineEdit()
        self.customer_email_edit = QLineEdit()

        info_layout.addRow("Name:", self.customer_name_edit)
        info_layout.addRow("Phone:", self.customer_phone_edit)
        info_layout.addRow("Email:", self.customer_email_edit)

        details_layout.addWidget(info_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)

        update_btn = QPushButton("Update Customer")
        update_btn.clicked.connect(self.update_customer)
        actions_layout.addWidget(update_btn)

        deactivate_btn = QPushButton("Deactivate Customer")
        deactivate_btn.clicked.connect(self.deactivate_customer)
        actions_layout.addWidget(deactivate_btn)

        details_layout.addWidget(actions_group)

        layout.addLayout(details_layout)

        self.customers_table.itemSelectionChanged.connect(self.on_customer_selected)

    def create_families_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Families")

        layout = QVBoxLayout(tab)

        # Controls
        controls_layout = QHBoxLayout()

        add_family_btn = QPushButton("Add Family")
        add_family_btn.clicked.connect(self.add_family_dialog)
        controls_layout.addWidget(add_family_btn)

        layout.addLayout(controls_layout)

        # Families table
        self.families_table = QTableWidget()
        self.families_table.setColumnCount(3)
        self.families_table.setHorizontalHeaderLabels(["ID", "Family Name", "Status"])
        layout.addWidget(self.families_table)

        # Family members
        members_group = QGroupBox("Family Members")
        members_layout = QVBoxLayout(members_group)

        self.family_members_table = QTableWidget()
        self.family_members_table.setColumnCount(4)
        self.family_members_table.setHorizontalHeaderLabels(["ID", "Name", "Phone", "Email"])
        members_layout.addWidget(self.family_members_table)

        # Member actions
        member_actions_layout = QHBoxLayout()

        add_member_btn = QPushButton("Add Member")
        add_member_btn.clicked.connect(self.add_member_to_family)
        member_actions_layout.addWidget(add_member_btn)

        remove_member_btn = QPushButton("Remove Member")
        remove_member_btn.clicked.connect(self.remove_member_from_family)
        member_actions_layout.addWidget(remove_member_btn)

        members_layout.addLayout(member_actions_layout)

        layout.addWidget(members_group)

    def create_plans_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Plans")

        layout = QVBoxLayout(tab)

        # Plan creation
        create_group = QGroupBox("Create New Plan")
        create_layout = QFormLayout(create_group)

        self.plan_customer_combo = QComboBox()
        self.plan_name_edit = QLineEdit()
        self.plan_total_edit = QDoubleSpinBox()
        self.plan_total_edit.setMaximum(1000000)
        self.deposit_amount_edit = QDoubleSpinBox()
        self.deposit_amount_edit.setMaximum(1000000)
        self.deposit_date_edit = QDateEdit()
        self.deposit_date_edit.setDate(QDate.currentDate())
        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(["Weekly", "Biweekly", "Monthly (Same Day)"])
        self.recurring_amount_edit = QDoubleSpinBox()
        self.recurring_amount_edit.setMaximum(1000000)
        self.first_due_edit = QDateEdit()
        self.first_due_edit.setDate(QDate.currentDate())

        # Connect signals for auto-population
        self.deposit_date_edit.dateChanged.connect(self.update_first_due_date)
        self.frequency_combo.currentTextChanged.connect(self.update_first_due_date)

        create_layout.addRow("Customer:", self.plan_customer_combo)
        create_layout.addRow("Plan Name:", self.plan_name_edit)
        create_layout.addRow("Total Amount:", self.plan_total_edit)
        create_layout.addRow("Deposit Amount:", self.deposit_amount_edit)
        create_layout.addRow("Deposit Date:", self.deposit_date_edit)
        create_layout.addRow("Frequency:", self.frequency_combo)
        create_layout.addRow("Recurring Amount:", self.recurring_amount_edit)
        create_layout.addRow("First Due Date:", self.first_due_edit)

        create_btn = QPushButton("Create Plan")
        create_btn.clicked.connect(self.create_plan)
        create_layout.addRow(create_btn)

        layout.addWidget(create_group)
        # Customer selector for viewing plans
        view_group = QGroupBox("View Plans for Customer")
        view_layout = QHBoxLayout(view_group)

        self.view_plans_customer_combo = QComboBox()
        view_layout.addWidget(QLabel("Customer:"))
        view_layout.addWidget(self.view_plans_customer_combo)

        view_btn = QPushButton("View Plans")
        view_btn.clicked.connect(self.view_plans_for_customer)
        view_layout.addWidget(view_btn)

        layout.addWidget(view_group)

        # Plans table
        self.plans_table = QTableWidget()
        self.plans_table.setColumnCount(8)
        self.plans_table.setHorizontalHeaderLabels(
            ["ID", "Plan Name", "Total", "Deposit", "Deposit Date", "Frequency", "First Due", "Deposit Active"]
        )
        layout.addWidget(self.plans_table)

        # Payment schedule
        dues_group = QGroupBox("Payment Schedule")
        dues_layout = QVBoxLayout(dues_group)

        view_dues_btn = QPushButton("View Payment Schedule for Customer")
        view_dues_btn.clicked.connect(self.view_dues_for_customer)
        dues_layout.addWidget(view_dues_btn)

        self.dues_table = QTableWidget()
        self.dues_table.setColumnCount(6)
        self.dues_table.setHorizontalHeaderLabels(["Due Date", "Amount Due", "Paid Amount", "Status", "Source", "Plan ID"])
        dues_layout.addWidget(self.dues_table)

        layout.addWidget(dues_group)

    def create_payments_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Payments")

        layout = QVBoxLayout(tab)

        # Payment recording
        record_group = QGroupBox("Record Payment")
        record_layout = QFormLayout(record_group)

        self.payment_payer_type_combo = QComboBox()
        self.payment_payer_type_combo.addItems(["Customer", "Family"])
        self.payment_payer_type_combo.currentIndexChanged.connect(self.load_payment_targets)
        self.payment_target_combo = QComboBox()
        self.payment_amount_edit = QDoubleSpinBox()
        self.payment_amount_edit.setMaximum(1000000)
        self.payment_date_edit = QDateEdit()
        self.payment_date_edit.setDate(QDate.currentDate())
        self.payment_note_edit = QTextEdit()
        self.payment_note_edit.setMaximumHeight(60)

        # Load initial payment targets
        self.load_payment_targets()

        record_layout.addRow("Payer Type:", self.payment_payer_type_combo)
        record_layout.addRow("Payer:", self.payment_target_combo)
        record_layout.addRow("Amount:", self.payment_amount_edit)
        record_layout.addRow("Date:", self.payment_date_edit)
        record_layout.addRow("Note:", self.payment_note_edit)

        record_btn = QPushButton("Record Payment")
        record_btn.clicked.connect(self.record_payment)
        record_layout.addRow(record_btn)

        layout.addWidget(record_group)

        # Payment history
        history_group = QGroupBox("Payment History")
        history_layout = QVBoxLayout(history_group)

        self.payments_table = QTableWidget()
        self.payments_table.setColumnCount(7)
        self.payments_table.setHorizontalHeaderLabels(["ID", "Payer Type", "Payer", "Date", "Amount", "Note", "Status"])
        history_layout.addWidget(self.payments_table)

        # History actions
        actions_layout = QHBoxLayout()

        edit_note_btn = QPushButton("Edit Note")
        edit_note_btn.clicked.connect(self.edit_payment_note)
        actions_layout.addWidget(edit_note_btn)

        void_btn = QPushButton("Void Payment")
        void_btn.clicked.connect(self.void_payment)
        actions_layout.addWidget(void_btn)

        history_layout.addLayout(actions_layout)

        layout.addWidget(history_group)

    def create_reports_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Reports")

        layout = QVBoxLayout(tab)

        # Export section
        export_group = QGroupBox("Export Data")
        export_layout = QVBoxLayout(export_group)

        export_buttons_layout = QHBoxLayout()
        export_customers_btn = QPushButton("Export Customers to CSV")
        export_customers_btn.clicked.connect(self.export_customers_csv)
        export_buttons_layout.addWidget(export_customers_btn)

        export_payments_btn = QPushButton("Export Payments to CSV")
        export_payments_btn.clicked.connect(self.export_payments_csv)
        export_buttons_layout.addWidget(export_payments_btn)

        export_layout.addLayout(export_buttons_layout)
        layout.addWidget(export_group)

        # Import section
        import_group = QGroupBox("Import Data")
        import_layout = QVBoxLayout(import_group)

        import_buttons_layout = QHBoxLayout()
        import_customers_btn = QPushButton("Import Customers from CSV")
        import_customers_btn.clicked.connect(self.import_customers_csv)
        import_buttons_layout.addWidget(import_customers_btn)

        import_payments_btn = QPushButton("Import Payments from CSV")
        import_payments_btn.clicked.connect(self.import_payments_csv)
        import_buttons_layout.addWidget(import_payments_btn)

        import_layout.addLayout(import_buttons_layout)
        layout.addWidget(import_group)

        # Summary reports
        summary_group = QGroupBox("Summary Reports")
        summary_layout = QVBoxLayout(summary_group)

        generate_summary_btn = QPushButton("Generate Summary Report")
        generate_summary_btn.clicked.connect(self.generate_summary_report)
        summary_layout.addWidget(generate_summary_btn)

        export_summary_btn = QPushButton("Export Summary to File")
        export_summary_btn.clicked.connect(self.export_summary)
        summary_layout.addWidget(export_summary_btn)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        summary_layout.addWidget(self.summary_text)

        layout.addWidget(summary_group)

        # Charts
        charts_group = QGroupBox("Payment Trends Chart")
        charts_layout = QVBoxLayout(charts_group)

        generate_chart_btn = QPushButton("Generate Payment Trends Chart")
        generate_chart_btn.clicked.connect(self.generate_payment_trends_chart)
        charts_layout.addWidget(generate_chart_btn)

        layout.addWidget(charts_group)

    def create_settings_tab(self):
        tab = QWidget()
        self.tab_widget.addTab(tab, "Settings")

        layout = QVBoxLayout(tab)

        # Email settings
        email_group = QGroupBox("Email Settings (SMTP)")
        email_layout = QFormLayout(email_group)

        self.smtp_server_edit = QLineEdit()
        self.smtp_port_edit = QSpinBox()
        self.smtp_port_edit.setValue(587)
        self.smtp_user_edit = QLineEdit()
        self.smtp_pass_edit = QLineEdit()
        self.smtp_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)

        email_layout.addRow("SMTP Server:", self.smtp_server_edit)
        email_layout.addRow("SMTP Port:", self.smtp_port_edit)
        email_layout.addRow("SMTP User:", self.smtp_user_edit)
        email_layout.addRow("SMTP Password:", self.smtp_pass_edit)

        save_email_btn = QPushButton("Save Email Settings")
        save_email_btn.clicked.connect(self.save_email_settings)
        email_layout.addRow(save_email_btn)

        layout.addWidget(email_group)

        # SMS settings
        sms_group = QGroupBox("SMS Settings (Twilio)")
        sms_layout = QFormLayout(sms_group)

        self.twilio_sid_edit = QLineEdit()
        self.twilio_token_edit = QLineEdit()
        self.twilio_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.twilio_from_edit = QLineEdit()

        sms_layout.addRow("Twilio SID:", self.twilio_sid_edit)
        sms_layout.addRow("Twilio Token:", self.twilio_token_edit)
        sms_layout.addRow("Twilio From Number:", self.twilio_from_edit)

        save_sms_btn = QPushButton("Save SMS Settings")
        save_sms_btn.clicked.connect(self.save_sms_settings)
        sms_layout.addRow(save_sms_btn)

        layout.addWidget(sms_group)

        # Payment settings
        payment_group = QGroupBox("Payment Settings")
        payment_layout = QVBoxLayout(payment_group)

        # Stripe
        stripe_group = QGroupBox("Stripe")
        stripe_layout = QFormLayout(stripe_group)
        self.stripe_key_edit = QLineEdit()
        self.stripe_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        stripe_layout.addRow("Secret Key:", self.stripe_key_edit)
        payment_layout.addWidget(stripe_group)

        # Authorize.net
        auth_net_group = QGroupBox("Authorize.net")
        auth_net_layout = QFormLayout(auth_net_group)
        self.auth_net_api_login_edit = QLineEdit()
        self.auth_net_transaction_key_edit = QLineEdit()
        self.auth_net_transaction_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        auth_net_layout.addRow("API Login ID:", self.auth_net_api_login_edit)
        auth_net_layout.addRow("Transaction Key:", self.auth_net_transaction_key_edit)
        payment_layout.addWidget(auth_net_group)

        save_payment_btn = QPushButton("Save Payment Settings")
        save_payment_btn.clicked.connect(self.save_payment_settings)
        payment_layout.addWidget(save_payment_btn)

        layout.addWidget(payment_group)

        # Test buttons
        test_group = QGroupBox("Test Integrations")
        test_layout = QVBoxLayout(test_group)

        test_email_btn = QPushButton("Send Test Email")
        test_email_btn.clicked.connect(self.test_email)
        test_layout.addWidget(test_email_btn)

        test_sms_btn = QPushButton("Send Test SMS")
        test_sms_btn.clicked.connect(self.test_sms)
        test_layout.addWidget(test_sms_btn)

        send_reminders_btn = QPushButton("Send Due Reminders (7 days ahead)")
        send_reminders_btn.clicked.connect(self.send_reminders)
        test_layout.addWidget(send_reminders_btn)

        sync_payments_btn = QPushButton("Sync Payments from Authorize.net")
        sync_payments_btn.clicked.connect(self.sync_payments)
        test_layout.addWidget(sync_payments_btn)

        layout.addWidget(test_group)

        # Load current settings
        self.load_settings()

    def export_customers_csv(self):
        try:
            customers = backend.search_customers(self.db_path, "", include_inactive=True)
            file_path, _ = QFileDialog.getSaveFileName(self, "Save Customers CSV", "", "CSV Files (*.csv)")
            if not file_path:
                return
            import csv
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["ID", "Name", "Phone", "Email", "Status"])
                for customer in customers:
                    if len(customer) == 5:
                        cid, name, phone, email, is_active = customer
                        status = "Active" if is_active else "Inactive"
                    else:
                        cid, name, phone, email = customer
                        status = "Active"
                    writer.writerow([cid, name or "", phone or "", email or "", status])
            QMessageBox.information(self, "Success", f"Customers exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export customers: {str(e)}")

    def export_payments_csv(self):
        try:
            payments = backend.list_payments(self.db_path, include_inactive=True)
            file_path, _ = QFileDialog.getSaveFileName(self, "Save Payments CSV", "", "CSV Files (*.csv)")
            if not file_path:
                return
            import csv
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["ID", "Payer Type", "Payer", "Date", "Amount", "Note", "Status"])
                for payment in payments:
                    if len(payment) == 7:
                        pid, ptype, payer_id, pdate, amt, note, is_active = payment
                        status = "Active" if is_active else "Voided"
                    else:
                        pid, ptype, payer_id, pdate, amt, note = payment
                        status = "Active"
                    target = backend.payment_display_target(self.db_path, ptype, payer_id)
                    writer.writerow([pid, ptype, target, pdate, backend.fmt2(amt), note or "", status])
            QMessageBox.information(self, "Success", f"Payments exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export payments: {str(e)}")

    def import_customers_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Customers CSV", "", "CSV Files (*.csv)")
        if not file_path:
            return
        try:
            import csv
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                imported = 0
                for row in reader:
                    name = row.get("Name", "").strip()
                    phone = row.get("Phone", "").strip()
                    email = row.get("Email", "").strip()
                    if name:
                        backend.add_customer(self.db_path, name, phone, email)
                        imported += 1
            self.refresh_customers()
            self.refresh_dashboard()
            QMessageBox.information(self, "Success", f"Imported {imported} customers")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import customers: {str(e)}")

    def import_payments_csv(self):
        QMessageBox.information(self, "Info", "Payment import functionality coming soon - requires careful mapping")

    def generate_summary_report(self):
        try:
            # Total revenue
            payments = backend.list_payments(self.db_path, include_inactive=False)
            total_revenue = sum(float(amt) for _, _, _, _, amt, _ in payments)

            # Outstanding balances - calculate from dues
            customers = backend.search_customers(self.db_path, "", include_inactive=False)
            outstanding = 0
            total_plans = 0
            for cid, _, _, _ in customers:
                plans = backend.list_customer_plans(self.db_path, cid, include_inactive=False)
                total_plans += len(plans)
                for plan in plans:
                    pid, _, _, _, _, _, _, _, _ = plan
                    dues = backend.list_customer_dues(self.db_path, cid)
                    plan_outstanding = sum(float(amt_due) - float(paid_amt) for _, _, amt_due, paid_amt, _, _, _, _ in dues if float(amt_due) - float(paid_amt) > 0.01)
                    outstanding += plan_outstanding

            report = f"""
Summary Report
==============

Total Revenue: ${backend.fmt2(total_revenue)}
Outstanding Balances: ${backend.fmt2(outstanding)}
Total Active Customers: {len(customers)}
Total Active Plans: {total_plans}

Generated on: {backend.today_str()}
"""
            self.summary_text.setPlainText(report.strip())
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate report: {str(e)}")

    def export_summary(self):
        text = self.summary_text.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Warning", "Generate a report first")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Summary Report", "", "Text Files (*.txt)")
        if not file_path:
            return
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text)
            QMessageBox.information(self, "Success", f"Summary exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export summary: {str(e)}")

    def generate_payment_trends_chart(self):
        try:
            payments = backend.list_payments(self.db_path, include_inactive=False)
            # Group by month
            from collections import defaultdict
            monthly_totals = defaultdict(float)
            for _, _, _, pdate, amt, _ in payments:
                month = pdate[:7]  # YYYY-MM
                monthly_totals[month] += float(amt)

            if not monthly_totals:
                QMessageBox.information(self, "Info", "No payment data to chart")
                return

            months = sorted(monthly_totals.keys())
            amounts = [monthly_totals[m] for m in months]

            import matplotlib.pyplot as plt
            plt.figure(figsize=(10, 5))
            plt.bar(months, amounts)
            plt.title("Payment Trends by Month")
            plt.xlabel("Month")
            plt.ylabel("Total Amount ($)")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.show()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate chart: {str(e)}")

    def load_settings(self):
        try:
            self.smtp_server_edit.setText(backend.get_setting(self.db_path, "smtp_server", ""))
            self.smtp_port_edit.setValue(int(backend.get_setting(self.db_path, "smtp_port", "587")))
            self.smtp_user_edit.setText(backend.get_setting(self.db_path, "smtp_user", ""))
            self.smtp_pass_edit.setText(backend.get_setting(self.db_path, "smtp_pass", ""))

            self.twilio_sid_edit.setText(backend.get_setting(self.db_path, "twilio_sid", ""))
            self.twilio_token_edit.setText(backend.get_setting(self.db_path, "twilio_token", ""))
            self.twilio_from_edit.setText(backend.get_setting(self.db_path, "twilio_from", ""))

            self.stripe_key_edit.setText(backend.get_setting(self.db_path, "stripe_secret_key", ""))
            self.auth_net_api_login_edit.setText(backend.get_setting(self.db_path, "auth_net_api_login", ""))
            self.auth_net_transaction_key_edit.setText(backend.get_setting(self.db_path, "auth_net_transaction_key", ""))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load settings: {str(e)}")

    def save_email_settings(self):
        try:
            backend.set_setting(self.db_path, "smtp_server", self.smtp_server_edit.text())
            backend.set_setting(self.db_path, "smtp_port", str(self.smtp_port_edit.value()))
            backend.set_setting(self.db_path, "smtp_user", self.smtp_user_edit.text())
            backend.set_setting(self.db_path, "smtp_pass", self.smtp_pass_edit.text())
            QMessageBox.information(self, "Success", "Email settings saved")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save email settings: {str(e)}")

    def save_sms_settings(self):
        try:
            backend.set_setting(self.db_path, "twilio_sid", self.twilio_sid_edit.text())
            backend.set_setting(self.db_path, "twilio_token", self.twilio_token_edit.text())
            backend.set_setting(self.db_path, "twilio_from", self.twilio_from_edit.text())
            QMessageBox.information(self, "Success", "SMS settings saved")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save SMS settings: {str(e)}")

    def save_payment_settings(self):
        try:
            backend.set_setting(self.db_path, "stripe_secret_key", self.stripe_key_edit.text())
            backend.set_setting(self.db_path, "auth_net_api_login", self.auth_net_api_login_edit.text())
            backend.set_setting(self.db_path, "auth_net_transaction_key", self.auth_net_transaction_key_edit.text())
            QMessageBox.information(self, "Success", "Payment settings saved")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save payment settings: {str(e)}")

    def test_email(self):
        email, ok = QInputDialog.getText(self, "Test Email", "Enter test email address:")
        if ok and email:
            try:
                backend.send_email_reminder(self.db_path, email, "Test Email", "This is a test email from your Payment Tracker.")
                QMessageBox.information(self, "Success", "Test email sent")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to send test email: {str(e)}")

    def test_sms(self):
        phone, ok = QInputDialog.getText(self, "Test SMS", "Enter test phone number (with country code):")
        if ok and phone:
            try:
                backend.send_sms_reminder(self.db_path, phone, "This is a test SMS from your Payment Tracker.")
                QMessageBox.information(self, "Success", "Test SMS sent")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to send test SMS: {str(e)}")

    def send_reminders(self):
        try:
            sent = backend.send_due_reminders(self.db_path, 7)
            QMessageBox.information(self, "Success", f"Sent {sent} reminders")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send reminders: {str(e)}")

    def sync_payments(self):
        try:
            synced = backend.sync_authorize_net_payments(self.db_path, 7)
            self.refresh_dashboard()
            self.refresh_payments()
            QMessageBox.information(self, "Success", f"Synced {synced} payments from Authorize.net")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to sync payments: {str(e)}")

    def check_alerts(self):
        try:
            alerts = backend.check_for_new_payments(self.db_path)
            if alerts:
                alert_text = "\n".join(alerts)
                QMessageBox.information(self, "Payment Alerts", f"New payments detected:\n\n{alert_text}")
        except Exception as e:
            print(f"Alert check failed: {e}")

    def start_alert_timer(self):
        self.alert_timer = QTimer()
        self.alert_timer.timeout.connect(self.check_alerts)
        self.alert_timer.start(60000)  # Check every 60 seconds

    def load_initial_data(self):
        self.refresh_dashboard()
        self.refresh_customers()
        self.refresh_families()
        self.refresh_plans()
        self.refresh_payments()
        self.load_customers_for_plans()

    def refresh_dashboard(self):
        # Load summary data
        try:
            # Total customers
            customers = backend.search_customers(self.db_path, "", include_inactive=True)
            active_customers = [c for c in customers if len(c) > 4 and c[4] == 1]
            self.total_customers_label.setText(f"Total Customers: {len(active_customers)}")

            # Total families
            families = backend.list_families(self.db_path, include_inactive=True)
            active_families = [f for f in families if len(f) > 2 and f[2] == 1]
            self.total_families_label.setText(f"Total Families: {len(active_families)}")

            # Active plans
            try:
                active_plans = 0
                for cid, _, _, _ in active_customers:
                    plans = backend.list_customer_plans(self.db_path, cid, include_inactive=False)
                    active_plans += len(plans)
                self.total_plans_label.setText(f"Active Plans: {active_plans}")
            except Exception as e:
                self.total_plans_label.setText("Active Plans: Error")
                print(f"Error counting active plans: {e}")

            # Pending dues
            try:
                outstanding = 0
                for cid, _, _, _ in active_customers:
                    dues = backend.list_customer_dues(self.db_path, cid)
                    plan_outstanding = sum(float(amt_due) - float(paid_amt) for _, _, amt_due, paid_amt, _, _, _, _ in dues if float(amt_due) - float(paid_amt) > 0.01)
                    outstanding += plan_outstanding
                self.pending_dues_label.setText(f"Pending Dues: ${backend.fmt2(outstanding)}")
            except Exception as e:
                self.pending_dues_label.setText("Pending Dues: Error")
                print(f"Error calculating pending dues: {e}")

            # Recent payments
            payments = backend.list_payments(self.db_path, include_inactive=False)[:10]  # Last 10
            self.recent_payments_table.setRowCount(len(payments))
            for row, payment in enumerate(payments):
                pid, ptype, payer_id, pdate, amt, note = payment
                target = backend.payment_display_target(self.db_path, ptype, payer_id)
                self.recent_payments_table.setItem(row, 0, QTableWidgetItem(pdate))
                self.recent_payments_table.setItem(row, 1, QTableWidgetItem(target))
                self.recent_payments_table.setItem(row, 2, QTableWidgetItem(f"${backend.fmt2(amt)}"))
                self.recent_payments_table.setItem(row, 3, QTableWidgetItem(note or ""))
                self.recent_payments_table.setItem(row, 4, QTableWidgetItem("Active"))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load dashboard: {str(e)}")

    def refresh_customers(self):
        try:
            customers = backend.search_customers(self.db_path, "", include_inactive=True)
            self.customers_table.setRowCount(len(customers))
            for row, customer in enumerate(customers):
                if len(customer) == 5:  # include_inactive
                    cid, name, phone, email, is_active = customer
                    status = "Active" if is_active else "Inactive"
                else:
                    cid, name, phone, email = customer
                    status = "Active"
                self.customers_table.setItem(row, 0, QTableWidgetItem(str(cid)))
                self.customers_table.setItem(row, 1, QTableWidgetItem(name or ""))
                self.customers_table.setItem(row, 2, QTableWidgetItem(phone or ""))
                self.customers_table.setItem(row, 3, QTableWidgetItem(email or ""))
                self.customers_table.setItem(row, 4, QTableWidgetItem(status))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load customers: {str(e)}")

    def refresh_families(self):
        try:
            families = backend.list_families(self.db_path, include_inactive=True)
            self.families_table.setRowCount(len(families))
            for row, family in enumerate(families):
                if len(family) == 3:
                    fid, name, is_active = family
                    status = "Active" if is_active else "Inactive"
                else:
                    fid, name = family
                    status = "Active"
                self.families_table.setItem(row, 0, QTableWidgetItem(str(fid)))
                self.families_table.setItem(row, 1, QTableWidgetItem(name))
                self.families_table.setItem(row, 2, QTableWidgetItem(status))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load families: {str(e)}")

    def refresh_plans(self):
        # Clear the plans table - plans are viewed per customer
        self.plans_table.setRowCount(0)
        # Optionally show a message
        if hasattr(self, 'plans_table') and self.plans_table.rowCount() == 0:
            # This is just to initialize the table as empty
            pass

    def view_plans_for_customer(self):
        customer_id = self.view_plans_customer_combo.currentData()
        if not customer_id:
            QMessageBox.warning(self, "Warning", "Please select a customer")
            return
        try:
            plans = backend.list_customer_plans(self.db_path, customer_id, include_inactive=True)
            self.plans_table.setRowCount(len(plans))
            for row, plan in enumerate(plans):
                pid, pname, total, dep, depdate, freq, rec, firstdue, is_active, dep_active = plan
                self.plans_table.setItem(row, 0, QTableWidgetItem(str(pid)))
                self.plans_table.setItem(row, 1, QTableWidgetItem(pname or ""))
                self.plans_table.setItem(row, 2, QTableWidgetItem(f"${backend.fmt2(total)}"))
                self.plans_table.setItem(row, 3, QTableWidgetItem(f"${backend.fmt2(dep)}"))
                self.plans_table.setItem(row, 4, QTableWidgetItem(depdate))
                self.plans_table.setItem(row, 5, QTableWidgetItem(freq))
                self.plans_table.setItem(row, 6, QTableWidgetItem(firstdue))
                self.plans_table.setItem(row, 7, QTableWidgetItem("Yes" if dep_active else "No"))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load plans: {str(e)}")

    def view_dues_for_customer(self):
        customer_id = self.view_plans_customer_combo.currentData()
        if not customer_id:
            QMessageBox.warning(self, "Warning", "Please select a customer")
            return
        try:
            dues = backend.list_customer_dues(self.db_path, customer_id)
            self.dues_table.setRowCount(len(dues))
            for row, due in enumerate(dues):
                due_id, due_date, amt_due, paid_amt, status, paid_date, plan_id, source = due
                self.dues_table.setItem(row, 0, QTableWidgetItem(due_date))
                self.dues_table.setItem(row, 1, QTableWidgetItem(f"${backend.fmt2(amt_due)}"))
                self.dues_table.setItem(row, 2, QTableWidgetItem(f"${backend.fmt2(paid_amt)}"))
                self.dues_table.setItem(row, 3, QTableWidgetItem(status))
                self.dues_table.setItem(row, 4, QTableWidgetItem(source or ""))
                self.dues_table.setItem(row, 5, QTableWidgetItem(str(plan_id)))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load dues: {str(e)}")

    def refresh_payments(self):
        try:
            payments = backend.list_payments(self.db_path, include_inactive=True)
            self.payments_table.setRowCount(len(payments))
            for row, payment in enumerate(payments):
                if len(payment) == 7:  # include_inactive
                    pid, ptype, payer_id, pdate, amt, note, is_active = payment
                    status = "Active" if is_active else "Voided"
                else:
                    pid, ptype, payer_id, pdate, amt, note = payment
                    status = "Active"
                target = backend.payment_display_target(self.db_path, ptype, payer_id)
                self.payments_table.setItem(row, 0, QTableWidgetItem(str(pid)))
                self.payments_table.setItem(row, 1, QTableWidgetItem(ptype))
                self.payments_table.setItem(row, 2, QTableWidgetItem(target))
                self.payments_table.setItem(row, 3, QTableWidgetItem(pdate))
                self.payments_table.setItem(row, 4, QTableWidgetItem(f"${backend.fmt2(amt)}"))
                self.payments_table.setItem(row, 5, QTableWidgetItem(note or ""))
                self.payments_table.setItem(row, 6, QTableWidgetItem(status))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load payments: {str(e)}")

    def load_customers_for_plans(self):
        try:
            customers = backend.search_customers(self.db_path, "", include_inactive=False)
            self.plan_customer_combo.clear()
            self.view_plans_customer_combo.clear()
            for customer in customers:
                cid, name, phone, email = customer
                display = f"{cid} - {name}"
                self.plan_customer_combo.addItem(display, cid)
                self.view_plans_customer_combo.addItem(display, cid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load customers for plans: {str(e)}")

    # Event handlers
    def search_customers(self):
        term = self.customer_search_input.text()
        try:
            customers = backend.search_customers(self.db_path, term, include_inactive=True)
            self.customers_table.setRowCount(len(customers))
            for row, customer in enumerate(customers):
                if len(customer) == 5:
                    cid, name, phone, email, is_active = customer
                    status = "Active" if is_active else "Inactive"
                else:
                    cid, name, phone, email = customer
                    status = "Active"
                self.customers_table.setItem(row, 0, QTableWidgetItem(str(cid)))
                self.customers_table.setItem(row, 1, QTableWidgetItem(name or ""))
                self.customers_table.setItem(row, 2, QTableWidgetItem(phone or ""))
                self.customers_table.setItem(row, 3, QTableWidgetItem(email or ""))
                self.customers_table.setItem(row, 4, QTableWidgetItem(status))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Search failed: {str(e)}")

    def add_customer_dialog(self):
        name, ok = QInputDialog.getText(None, "Add Customer", "Customer Name:")
        if not ok or not name.strip():
            return
        phone, ok = QInputDialog.getText(None, "Add Customer", "Phone:")
        if not ok:
            return
        email, ok = QInputDialog.getText(None, "Add Customer", "Email:")
        if not ok:
            return
        try:
            backend.add_customer(self.db_path, name.strip(), phone.strip(), email.strip())
            self.refresh_customers()
            self.refresh_dashboard()
            QMessageBox.information(self, "Success", "Customer added successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add customer: {str(e)}")

    def update_customer(self):
        selected_rows = self.customers_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Warning", "Please select a customer to update")
            return
        row = selected_rows[0].row()
        cid = int(self.customers_table.item(row, 0).text())
        name = self.customer_name_edit.text().strip()
        phone = self.customer_phone_edit.text().strip()
        email = self.customer_email_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Warning", "Name is required")
            return
        try:
            backend.update_customer(self.db_path, cid, name, phone, email)
            self.refresh_customers()
            QMessageBox.information(self, "Success", "Customer updated")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update customer: {str(e)}")

    def on_customer_selected(self):
        selected_rows = self.customers_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        name = self.customers_table.item(row, 1).text()
        phone = self.customers_table.item(row, 2).text()
        email = self.customers_table.item(row, 3).text()
        self.customer_name_edit.setText(name)
        self.customer_phone_edit.setText(phone)
        self.customer_email_edit.setText(email)

    def deactivate_customer(self):
        if self.user_role != 'admin':
            QMessageBox.warning(self, "Access Denied", "Only admins can deactivate customers")
            return
        selected_rows = self.customers_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Warning", "Please select a customer to deactivate")
            return
        row = selected_rows[0].row()
        cid = int(self.customers_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Confirm", "Are you sure you want to deactivate this customer?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                backend.deactivate_customer(self.db_path, cid)
                self.refresh_customers()
                self.refresh_dashboard()
                QMessageBox.information(self, "Success", "Customer deactivated")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to deactivate customer: {str(e)}")

    def add_family_dialog(self):
        name, ok = QInputDialog.getText(self, "Add Family", "Family Name:")
        if not ok or not name.strip():
            return
        try:
            backend.create_family(self.db_path, name.strip())
            self.refresh_families()
            self.refresh_dashboard()
            QMessageBox.information(self, "Success", "Family added successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add family: {str(e)}")

    def add_member_to_family(self):
        # TODO: Implement
        QMessageBox.information(self, "Info", "Add member functionality coming soon")

    def remove_member_from_family(self):
        # TODO: Implement
        QMessageBox.information(self, "Info", "Remove member functionality coming soon")

    def update_first_due_date(self):
        deposit_date = self.deposit_date_edit.date()
        freq = self.frequency_combo.currentText()

        if freq == "Weekly":
            self.first_due_edit.setDate(deposit_date.addDays(7))
        elif freq == "Biweekly":
            self.first_due_edit.setDate(deposit_date.addDays(14))
        elif freq == "Monthly (Same Day)":
            self.first_due_edit.setDate(deposit_date.addMonths(1))

    def create_plan(self):
        customer_id = self.plan_customer_combo.currentData()
        if not customer_id:
            QMessageBox.warning(self, "Warning", "Please select a customer")
            return
        plan_name = self.plan_name_edit.text().strip()
        plan_total = self.plan_total_edit.value()
        deposit_amount = self.deposit_amount_edit.value()
        deposit_date = self.deposit_date_edit.date().toString("yyyy-MM-dd")
        frequency = self.frequency_combo.currentText()
        recurring_amount = self.recurring_amount_edit.value()
        first_due_date = self.first_due_edit.date().toString("yyyy-MM-dd")

        if plan_total <= 0:
            QMessageBox.warning(self, "Warning", "Plan total must be > 0")
            return
        if deposit_amount < 0 or deposit_amount > plan_total:
            QMessageBox.warning(self, "Warning", "Invalid deposit amount")
            return
        if recurring_amount <= 0:
            QMessageBox.warning(self, "Warning", "Recurring amount must be > 0")
            return

        try:
            plan_id = backend.add_plan(
                self.db_path, customer_id, plan_name, plan_total, deposit_amount,
                deposit_date, frequency, recurring_amount, first_due_date
            )
            self.refresh_dashboard()
            QMessageBox.information(self, "Success", f"Plan created with ID {plan_id}")
            # Reset form
            self.plan_name_edit.clear()
            self.plan_total_edit.setValue(0)
            self.deposit_amount_edit.setValue(0)
            self.deposit_date_edit.setDate(QDate.currentDate())
            self.frequency_combo.setCurrentIndex(0)
            self.recurring_amount_edit.setValue(0)
            self.first_due_edit.setDate(QDate.currentDate())
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create plan: {str(e)}")

    def record_payment(self):
        payer_type = self.payment_payer_type_combo.currentText()
        payer_id = self.payment_target_combo.currentData()
        if not payer_id:
            QMessageBox.warning(self, "Warning", "Please select a payer")
            return
        amount = self.payment_amount_edit.value()
        if amount <= 0:
            QMessageBox.warning(self, "Warning", "Amount must be > 0")
            return
        payment_date = self.payment_date_edit.date().toString("yyyy-MM-dd")
        note = self.payment_note_edit.toPlainText().strip()

        try:
            payment_id = backend.auto_allocate(self.db_path, payer_type, payer_id, amount, payment_date, note)
            self.refresh_dashboard()
            self.refresh_payments()
            QMessageBox.information(self, "Success", f"Payment recorded with ID {payment_id} (auto-allocated)")
            # Reset form
            self.payment_amount_edit.setValue(0)
            self.payment_date_edit.setDate(QDate.currentDate())
            self.payment_note_edit.clear()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to record payment: {str(e)}")

    def edit_payment_note(self):
        selected_rows = self.payments_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Warning", "Please select a payment")
            return
        row = selected_rows[0].row()
        pid = int(self.payments_table.item(row, 0).text())
        current_note = self.payments_table.item(row, 5).text() if self.payments_table.item(row, 5) else ""

        note, ok = QInputDialog.getMultiLineText(self, "Edit Payment Note", "Note:", current_note)
        if ok:
            try:
                backend.update_payment_note(self.db_path, pid, note)
                self.refresh_payments()
                QMessageBox.information(self, "Success", "Note updated")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to update note: {str(e)}")

    def void_payment(self):
        if self.user_role != 'admin':
            QMessageBox.warning(self, "Access Denied", "Only admins can void payments")
            return
        selected_rows = self.payments_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Warning", "Please select a payment")
            return
        row = selected_rows[0].row()
        pid = int(self.payments_table.item(row, 0).text())
        reply = QMessageBox.question(self, "Confirm", "Void this payment? This will reverse allocations.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                backend.void_payment(self.db_path, pid)
                self.refresh_dashboard()
                self.refresh_payments()
                QMessageBox.information(self, "Success", "Payment voided")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to void payment: {str(e)}")

    def load_payment_targets(self):
        payer_type = self.payment_payer_type_combo.currentText()
        self.payment_target_combo.clear()
        try:
            if payer_type == "Customer":
                customers = backend.search_customers(self.db_path, "", include_inactive=False)
                for cid, name, phone, email in customers:
                    self.payment_target_combo.addItem(f"{cid} - {name}", cid)
            elif payer_type == "Family":
                families = backend.list_families(self.db_path, include_inactive=False)
                for fid, fname in families:
                    self.payment_target_combo.addItem(f"{fid} - {fname}", fid)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load payment targets: {str(e)}")


def main():
    app = QApplication(sys.argv)

    # Initialize database directly (skip authentication for now)
    db_path = "payment_tracker.db"  # Default database file
    backend.init_db(db_path)

    # Skip login for now - use default admin user
    window = PaymentTrackerApp(db_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()