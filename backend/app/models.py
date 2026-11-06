from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, DateTime, Date, Numeric, Boolean,
    ForeignKey, Index, Text, JSON
)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    currency = Column(String(10), default="INR", nullable=False)
    locale = Column(String(20), default="en-IN", nullable=False)
    monthly_total_budget = Column(Numeric(14, 2), default=Decimal("0.00"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    statements = relationship("Statement", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan")
    recurring_items = relationship("RecurringPayment", back_populates="user", cascade="all, delete-orphan")
    anomaly_alerts = relationship("AnomalyAlert", back_populates="user", cascade="all, delete-orphan")
    snapshots = relationship("FinancialSnapshot", back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String(120), nullable=False)
    account_type = Column(String(50), default="Savings", nullable=False)  # Savings, Checking, Credit Card
    currency = Column(String(10), default="INR", nullable=False)
    masked_identifier = Column(String(32), nullable=True)  # e.g. XXXX-4821
    is_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="accounts")
    statements = relationship("Statement", back_populates="account", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="account", cascade="all, delete-orphan")


class Statement(Base):
    __tablename__ = "statements"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    processing_status = Column(String(50), default="PROCESSED", nullable=False)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    imported_count = Column(Integer, default=0, nullable=False)
    reconciliation_status = Column(String(64), default="UNVERIFIABLE", nullable=False)
    reconciliation_details = Column(Text, nullable=True)
    is_synthetic = Column(Boolean, default=False, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="statements")
    account = relationship("Account", back_populates="statements")
    transactions = relationship("Transaction", back_populates="statement", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id", ondelete="CASCADE"), nullable=True, index=True)

    txn_date = Column(Date, nullable=False, index=True)
    description = Column(String(500), nullable=False)
    merchant = Column(String(200), nullable=False, index=True)
    debit = Column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    credit = Column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    signed_amount = Column(Numeric(14, 2), nullable=False)  # Positive for credit, negative for debit
    currency = Column(String(10), default="INR", nullable=False)
    balance = Column(Numeric(14, 2), nullable=True)

    category = Column(String(100), default="Other", nullable=False, index=True)
    subcategory = Column(String(100), nullable=True)
    txn_type = Column(String(50), default="EXPENSE", nullable=False)  # EXPENSE, INCOME, TRANSFER, REFUND

    extraction_confidence = Column(Numeric(4, 2), default=Decimal("1.00"), nullable=False)
    categorization_confidence = Column(Numeric(4, 2), default=Decimal("0.80"), nullable=False)
    classification_source = Column(String(50), default="RULE", nullable=False)  # USER, RULE, ML, FALLBACK

    is_unusual = Column(Boolean, default=False, nullable=False)
    review_status = Column(String(50), default="OK", nullable=False)  # OK, NEEDS_REVIEW, REVIEWED, EXPECTED, INVESTIGATE
    exclude_from_analytics = Column(Boolean, default=False, nullable=False)
    is_synthetic = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="transactions")
    account = relationship("Account", back_populates="transactions")
    statement = relationship("Statement", back_populates="transactions")
    anomaly_alerts = relationship("AnomalyAlert", back_populates="transaction", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_user_date_cat", "user_id", "txn_date", "category"),
    )


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    parent_category = Column(String(100), nullable=True)
    is_essential = Column(Boolean, default=False, nullable=False)
    keyword_pattern = Column(String(500), nullable=True)  # Pipe-separated regex/keywords

    user = relationship("User", back_populates="categories")


class RecurringPayment(Base):
    __tablename__ = "recurring_payments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    typical_amount = Column(Numeric(14, 2), nullable=False)
    monthly_equivalent = Column(Numeric(14, 2), nullable=False)
    frequency = Column(String(50), nullable=False)  # WEEKLY, MONTHLY, QUARTERLY, ANNUAL
    occurrences = Column(Integer, nullable=False)
    last_observed_date = Column(Date, nullable=False)
    next_expected_date = Column(Date, nullable=False)
    confidence = Column(Numeric(4, 2), nullable=False)
    has_price_increase = Column(Boolean, default=False, nullable=False)
    price_change_note = Column(String(255), nullable=True)
    review_status = Column(String(50), default="UNREVIEWED", nullable=False)  # UNREVIEWED, USEFUL, UNWANTED, INCORRECT

    user = relationship("User", back_populates="recurring_items")


class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    detection_method = Column(String(100), nullable=False)  # MAD_ZSCORE, ISOLATION_FOREST, VELOCITY_SPIKE, PRICE_HIKE
    severity = Column(String(30), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH
    relative_deviation = Column(Numeric(8, 2), nullable=True)
    explanation = Column(Text, nullable=False)
    review_status = Column(String(50), default="NEEDS_REVIEW", nullable=False)  # NEEDS_REVIEW, REVIEWED, EXPECTED, INVESTIGATE, DISMISSED
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="anomaly_alerts")
    transaction = relationship("Transaction", back_populates="anomaly_alerts")


class Budget(Base):
    __tablename__ = "budgets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(100), nullable=False)
    period = Column(String(20), default="MONTHLY", nullable=False)
    target_amount = Column(Numeric(14, 2), nullable=False)
    alert_threshold_pct = Column(Integer, default=85, nullable=False)

    user = relationship("User", back_populates="budgets")


class FinancialSnapshot(Base):
    __tablename__ = "financial_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reporting_period = Column(String(50), nullable=False)
    overall_score = Column(Integer, nullable=True)
    policy_applied = Column(String(100), nullable=False)
    components_json = Column(JSON, nullable=False)
    calculation_version = Column(String(20), default="v1.0", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="snapshots")