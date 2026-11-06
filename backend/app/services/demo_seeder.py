from datetime import date
from decimal import Decimal
from typing import Dict
from sqlalchemy.orm import Session
from ..models import User, Account, Statement, Transaction, Budget
from .intelligence import rebuild_recurring_payments, rebuild_anomaly_alerts


def seed_synthetic_demo_data(user: User, db: Session) -> Dict[str, int]:
    """
    Populates 3 months of clearly labelled synthetic transactions covering:
    Salary, Rent, EMI, Subscriptions (with a silent price hike on Netflix),
    Groceries, Food delivery, Utilities, Self-Transfer, Refund, and 2 Unusual Spikes.
    """
    # Remove any prior demo account for idempotency
    db.query(Account).filter(Account.user_id == user.id, Account.is_demo == True).delete()
    db.commit()

    demo_acc = Account(
        user_id=user.id,
        display_name="SYNTHETIC DEMO — HDFC Savings XXXX-9012",
        account_type="Savings",
        currency=user.currency,
        masked_identifier="XXXX-9012",
        is_demo=True
    )
    db.add(demo_acc)
    db.commit()
    db.refresh(demo_acc)

    demo_stmt = Statement(
        user_id=user.id,
        account_id=demo_acc.id,
        original_filename="SYNTHETIC_DEMO_3M_STATEMENT.csv",
        processing_status="PROCESSED",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 10, 26),
        reconciliation_status="VERIFIED",
        reconciliation_details="Synthetic demonstration ledger mathematically reconciled across all rows.",
        is_synthetic=True
    )
    db.add(demo_stmt)
    db.commit()
    db.refresh(demo_stmt)

    # Format: (Date, Description, Merchant, Debit, Credit, Category, Type)
    raw_records = [
        # --- AUGUST 2026 ---
        (date(2026, 8, 1), "NEFT CR-TECHCORP INDIA SALARY AUG", "Techcorp India", 0, 85000, "Salary and Income", "INCOME"),
        (date(2026, 8, 3), "UPI/NOBROKER HOUSE RENT AUG", "Nobroker Rent", 18000, 0, "Housing and Rent", "EXPENSE"),
        (date(2026, 8, 5), "ACH DR-HDFC AUTO LOAN EMI", "Hdfc Loan Emi", 11500, 0, "EMI and Loan Payments", "EXPENSE"),
        (date(2026, 8, 7), "UPI/BESCOM ELECTRICITY BILL", "Bescom Electricity", 1420, 0, "Utilities", 	"EXPENSE"),
        (date(2026, 8, 8), "UPI/JIOFIBER BROADBAND PLAN", "Jiofiber Broadband", 999, 0, "Utilities", "EXPENSE"),
        (date(2026, 8, 10), "POS NETFLIX SUBSCRIPTION MUMBAI", "Netflix", 499, 0, "Entertainment", "EXPENSE"),
        (date(2026, 8, 11), "POS SPOTIFY INDIA PREMIUM", "Spotify", 119, 0, "Entertainment", "EXPENSE"),
        (date(2026, 8, 12), "UPI/BLINKIT GROCERIES", "Blinkit", 1650, 0, "Groceries", "EXPENSE"),
        (date(2026, 8, 15), "UPI/SWIGGY ORDER BANGALORE", "Swiggy", 620, 0, "Food and Dining", "EXPENSE"),
        (date(2026, 8, 18), "UPI/INDIAN OIL PETROL PUMP", "Indian Oil", 1800, 0, "Transportation", "EXPENSE"),
        (date(2026, 8, 21), "UPI/AMAZON INDIA SHOPPING", "Amazon", 2100, 0, "Shopping", "EXPENSE"),
        (date(2026, 8, 24), "UPI/DMART SUPERMARKET", "Dmart", 3200, 0, "Groceries", "EXPENSE"),
        (date(2026, 8, 26), "NEFT TO SELF ZERODHA BROKING", "Zerodha Transfer", 10000, 0, "Investments and Transfers", "TRANSFER"),

        # --- SEPTEMBER 2026 ---
        (date(2026, 9, 1), "NEFT CR-TECHCORP INDIA SALARY SEP", "Techcorp India", 0, 85000, "Salary and Income", "INCOME"),
        (date(2026, 9, 3), "UPI/NOBROKER HOUSE RENT SEP", "Nobroker Rent", 18000, 0, "Housing and Rent", "EXPENSE"),
        (date(2026, 9, 5), "ACH DR-HDFC AUTO LOAN EMI", "Hdfc Loan Emi", 11500, 0, "EMI and Loan Payments", "EXPENSE"),
        (date(2026, 9, 7), "UPI/BESCOM ELECTRICITY BILL", "Bescom Electricity", 1490, 0, "Utilities", "EXPENSE"),
        (date(2026, 9, 8), "UPI/JIOFIBER BROADBAND PLAN", "Jiofiber Broadband", 999, 0, "Utilities", "EXPENSE"),
        (date(2026, 9, 10), "POS NETFLIX SUBSCRIPTION MUMBAI", "Netflix", 499, 0, "Entertainment", "EXPENSE"),
        (date(2026, 9, 11), "POS SPOTIFY INDIA PREMIUM", "Spotify", 119, 0, "Entertainment", "EXPENSE"),
        (date(2026, 9, 13), "UPI/ZEPTO GROCERY INSTANT", "Zepto", 1900, 0, "Groceries", "EXPENSE"),
        (date(2026, 9, 15), "UPI/ZOMATO FOOD DELIVERY", "Zomato", 780, 0, "Food and Dining", "EXPENSE"),
        (date(2026, 9, 17), "UPI/UBER INDIA TRIP", "Uber", 950, 0, "Transportation", "EXPENSE"),
        (date(2026, 9, 19), "UPI/MYNTRA FASHION ORDER", "Myntra", 2450, 0, "Shopping", "EXPENSE"),
        (date(2026, 9, 21), "UPI/REFUND MYNTRA RETURN ORDER", "Myntra Refund", 0, 850, "Refunds and Reimbursements", "REFUND"),
        (date(2026, 9, 25), "UPI/DMART SUPERMARKET", "Dmart", 2950, 0, "Groceries", "EXPENSE"),
        (date(2026, 9, 28), "UPI/APOLLO PHARMACY HEALTH", "Apollo Pharmacy", 1120, 0, "Healthcare", "EXPENSE"),

        # --- OCTOBER 2026 (Includes Price Hike, Dining Creep, & 2 Unusual Transactions for Review) ---
        (date(2026, 10, 1), "NEFT CR-TECHCORP INDIA SALARY OCT", "Techcorp India", 0, 85000, "Salary and Income", "INCOME"),
        (date(2026, 10, 3), "UPI/NOBROKER HOUSE RENT OCT", "Nobroker Rent", 18000, 0, "Housing and Rent", "EXPENSE"),
        (date(2026, 10, 5), "ACH DR-HDFC AUTO LOAN EMI", "Hdfc Loan Emi", 11500, 0, "EMI and Loan Payments", "EXPENSE"),
        (date(2026, 10, 7), "UPI/BESCOM ELECTRICITY BILL", "Bescom Electricity", 1560, 0, "Utilities", "EXPENSE"),
        (date(2026, 10, 8), "UPI/JIOFIBER BROADBAND PLAN", "Jiofiber Broadband", 999, 0, "Utilities", "EXPENSE"),
        # Price hike on Netflix (499 -> 649)
        (date(2026, 10, 10), "POS NETFLIX SUBSCRIPTION UPGRADE", "Netflix", 649, 0, "Entertainment", "EXPENSE"),
        (date(2026, 10, 11), "POS SPOTIFY INDIA PREMIUM", "Spotify", 119, 0, "Entertainment", "EXPENSE"),
        (date(2026, 10, 12), "UPI/BLINKIT GROCERIES", "Blinkit", 2100, 0, "Groceries", "EXPENSE"),
        (date(2026, 10, 14), "UPI/SWIGGY PARTY ORDER", "Swiggy", 1450, 0, "Food and Dining", "EXPENSE"),
        (date(2026, 10, 16), "UPI/ZOMATO DINNER ORDER", "Zomato", 1320, 0, "Food and Dining", "EXPENSE"),
        (date(2026, 10, 18), "UPI/INDIAN OIL FUEL", "Indian Oil", 2150, 0, "Transportation", "EXPENSE"),
        # Unusual Alert #1: Large Category Outlier in Shopping (18,900 vs ~2,200 median)
        (date(2026, 10, 20), "POS CROMA ELECTRONICS MEGA STORE", "Croma Electronics", 18900, 0, "Shopping", "EXPENSE"),
        # Unusual Alert #2: Same-day duplicate velocity charge at Swiggy
        (date(2026, 10, 22), "UPI/SWIGGY INSTANT ORDER", "Swiggy", 890, 0, "Food and Dining", "EXPENSE"),
        (date(2026, 10, 22), "UPI/SWIGGY INSTANT ORDER", "Swiggy", 890, 0, "Food and Dining", "EXPENSE"),
        (date(2026, 10, 25), "UPI/DMART SUPERMARKET", "Dmart", 3100, 0, "Groceries", "EXPENSE"),
    ]

    running_bal = Decimal("42000.00")
    for dt, desc, merch, deb, cred, cat, t_type in raw_records:
        d_dec = Decimal(str(deb)).quantize(Decimal("0.01"))
        c_dec = Decimal(str(cred)).quantize(Decimal("0.01"))
        signed = c_dec - d_dec
        running_bal = running_bal + signed
        txn = Transaction(
            user_id=user.id,
            account_id=demo_acc.id,
            statement_id=demo_stmt.id,
            txn_date=dt,
            description=f"[SYNTHETIC DEMO] {desc}",
            merchant=merch,
            debit=d_dec,
            credit=c_dec,
            signed_amount=signed,
            currency=user.currency,
            balance=running_bal,
            category=cat,
            txn_type=t_type,
            extraction_confidence=Decimal("1.00"),
            categorization_confidence=Decimal("0.95"),
            classification_source="DEMO_SEED",
            is_synthetic=True
        )
        db.add(txn)

    demo_stmt.imported_count = len(raw_records)

    # Seed sensible default budgets if user has none
    existing_budgets = db.query(Budget).filter(Budget.user_id == user.id).count()
    if existing_budgets == 0:
        default_budgets = [
            ("Food and Dining", 3000),
            ("Groceries", 6000),
            ("Shopping", 5000),
            ("Transportation", 3500),
            ("Utilities", 3000),
            ("Entertainment", 1200),
        ]
        for b_cat, b_amt in default_budgets:
            db.add(Budget(user_id=user.id, category=b_cat, target_amount=Decimal(str(b_amt)), alert_threshold_pct=85))
        user.monthly_total_budget = Decimal("55000.00")

    db.commit()
    recs = rebuild_recurring_payments(user.id, db)
    alerts = rebuild_anomaly_alerts(user.id, db)

    return {
        "transactions_seeded": len(raw_records),
        "recurring_detected": len(recs),
        "anomalies_flagged": len(alerts),
        "account_id": demo_acc.id
    }