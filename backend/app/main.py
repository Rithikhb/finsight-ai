from datetime import date
from decimal import Decimal
from collections import defaultdict
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .models import (
    User, Account, Statement, Transaction, Category,
    RecurringPayment, AnomalyAlert, Budget, FinancialSnapshot
)
from .schemas import (
    UserCreate, UserLogin, UserOut, TokenOut, AccountCreate, AccountOut,
    UploadPreviewResponse, ConfirmImportRequest, TransactionUpdate,
    BudgetUpsert, TotalBudgetUpdate, RecurringStatusUpdate,
    AnomalyActionUpdate, AssistantQuery
)
from .security import (
    hash_password, verify_password, create_access_token,
    get_current_user, check_rate_limit
)
from .services.parser import parse_and_validate_statement
from .services.intelligence import (
    rebuild_recurring_payments, rebuild_anomaly_alerts,
    compute_financial_health_score, answer_grounded_financial_query,
    ESSENTIAL_CATEGORIES
)
from .services.demo_seeder import seed_synthetic_demo_data
from .services.reports import generate_csv_report, generate_excel_report, generate_pdf_report

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="FinSight AI — Bank Statement Intelligence & Financial Health API",
    version="1.0.0",
    description="Privacy-first bank statement parser, hybrid ML categorizer, recurring detector, explainable anomaly reviewer, and transparent financial health engine."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 1. AUTHENTICATION & PROFILE ====================

@app.post("/api/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, limit=15, window_sec=60)
    existing = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    user = User(
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        password_hash=hash_password(payload.password),
        currency=payload.currency.upper()
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create a default Primary Savings account
    default_acc = Account(
        user_id=user.id,
        display_name="Primary Bank Account",
        account_type="Savings",
        currency=user.currency,
        masked_identifier="XXXX-0001",
        is_demo=False
    )
    db.add(default_acc)
    db.commit()

    token = create_access_token(user.id, user.email)
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.post("/api/auth/login", response_model=TokenOut)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, limit=20, window_sec=60)
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_access_token(user.id, user.email)
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/api/auth/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ==================== 2. ACCOUNTS & DEMO MODE ====================

@app.get("/api/accounts", response_model=List[AccountOut])
def list_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Account).filter(Account.user_id == current_user.id).order_by(Account.id.asc()).all()


@app.post("/api/accounts", response_model=AccountOut)
def create_account(payload: AccountCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = Account(
        user_id=current_user.id,
        display_name=payload.display_name.strip(),
        account_type=payload.account_type,
        currency=payload.currency,
        masked_identifier=payload.masked_identifier,
        is_demo=False
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@app.post("/api/demo/load")
def load_demo_mode(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stats = seed_synthetic_demo_data(current_user, db)
    return {
        "message": "Synthetic demonstration dataset loaded and clearly labeled.",
        "stats": stats
    }


# ==================== 3. UPLOAD, PREVIEW & CONFIRM IMPORT ====================

@app.post("/api/statements/upload-preview", response_model=UploadPreviewResponse)
async def upload_statement_preview(
    request: Request,
    account_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    check_rate_limit(request, limit=15, window_sec=60)
    account = db.query(Account).filter(Account.id == account_id, Account.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Selected account not found or unauthorized.")

    raw_bytes = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(raw_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB maximum size.")

    safe_filename = (file.filename or "statement.csv").replace("..", "").replace("/", "_").replace("\\", "_")
    try:
        preview = parse_and_validate_statement(
            file_bytes=raw_bytes,
            filename=safe_filename,
            user_id=current_user.id,
            account_id=account.id,
            db=db
        )
        return preview
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse statement file. Ensure the file is not corrupted or password-protected.")


@app.post("/api/statements/confirm-import")
def confirm_statement_import(
    payload: ConfirmImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    account = db.query(Account).filter(Account.id == payload.account_id, Account.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    selected_rows = [r for r in payload.rows if r.include_in_import]
    if not selected_rows:
        raise HTTPException(status_code=400, detail="No rows selected for import.")

    parsed_dates = []
    for r in selected_rows:
        if not r.txn_date:
            raise HTTPException(status_code=400, detail=f"Row #{r.temp_id} has an invalid date and must be corrected before import.")
        try:
            parsed_dates.append(date.fromisoformat(r.txn_date))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Row #{r.temp_id} date '{r.txn_date}' must be YYYY-MM-DD.")

    stmt = Statement(
        user_id=current_user.id,
        account_id=account.id,
        original_filename=payload.filename,
        processing_status="IMPORTED",
        period_start=min(parsed_dates),
        period_end=max(parsed_dates),
        imported_count=len(selected_rows),
        reconciliation_status=payload.reconciliation_status,
        reconciliation_details=payload.reconciliation_details,
        is_synthetic=False
    )
    db.add(stmt)
    db.commit()
    db.refresh(stmt)

    for r, dt in zip(selected_rows, parsed_dates):
        deb = Decimal(str(round(r.debit, 2)))
        cred = Decimal(str(round(r.credit, 2)))
        signed = cred - deb
        txn = Transaction(
            user_id=current_user.id,
            account_id=account.id,
            statement_id=stmt.id,
            txn_date=dt,
            description=r.description,
            merchant=r.merchant,
            debit=deb,
            credit=cred,
            signed_amount=signed,
            currency=account.currency,
            balance=Decimal(str(round(r.balance, 2))) if r.balance is not None else None,
            category=r.category,
            txn_type=r.txn_type,
            extraction_confidence=Decimal(str(round(r.extraction_confidence, 2))),
            categorization_confidence=Decimal(str(round(r.categorization_confidence, 2))),
            classification_source=r.classification_source,
            is_synthetic=False
        )
        db.add(txn)

    db.commit()
    recs = rebuild_recurring_payments(current_user.id, db)
    alerts = rebuild_anomaly_alerts(current_user.id, db)

    return {
        "statement_id": stmt.id,
        "imported_count": len(selected_rows),
        "recurring_detected": len(recs),
        "anomalies_flagged": len(alerts),
        "reconciliation_status": stmt.reconciliation_status
    }


@app.get("/api/statements")
def list_statements(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmts = db.query(Statement).filter(Statement.user_id == current_user.id).order_by(Statement.uploaded_at.desc()).all()
    return [{
        "id": s.id,
        "account_id": s.account_id,
        "original_filename": s.original_filename,
        "period_start": s.period_start.isoformat() if s.period_start else None,
        "period_end": s.period_end.isoformat() if s.period_end else None,
        "imported_count": s.imported_count,
        "reconciliation_status": s.reconciliation_status,
        "reconciliation_details": s.reconciliation_details,
        "is_synthetic": s.is_synthetic,
        "uploaded_at": s.uploaded_at.isoformat()
    } for s in stmts]


@app.delete("/api/statements/{statement_id}")
def delete_statement(statement_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = db.query(Statement).filter(Statement.id == statement_id, Statement.user_id == current_user.id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found.")
    db.delete(stmt)
    db.commit()
    rebuild_recurring_payments(current_user.id, db)
    rebuild_anomaly_alerts(current_user.id, db)
    return {"message": "Statement and associated transactions permanently deleted."}


# ==================== 4. TRANSACTIONS & USER CORRECTIONS ====================

@app.get("/api/transactions")
def list_transactions(
    account_id: Optional[int] = None,
    category: Optional[str] = None,
    merchant: Optional[str] = None,
    txn_type: Optional[str] = None,
    month: Optional[str] = None,
    unusual_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(Transaction).filter(Transaction.user_id == current_user.id)
    if account_id:
        q = q.filter(Transaction.account_id == account_id)
    if category:
        q = q.filter(Transaction.category == category)
    if merchant:
        q = q.filter(Transaction.merchant.ilike(f"%{merchant}%"))
    if txn_type:
        q = q.filter(Transaction.txn_type == txn_type)
    if unusual_only:
        q = q.filter(Transaction.is_unusual == True)

    items = q.order_by(Transaction.txn_date.desc(), Transaction.id.desc()).all()
    if month:
        items = [t for t in items if t.txn_date.strftime("%Y-%m") == month]

    return [{
        "id": t.id,
        "account_id": t.account_id,
        "txn_date": t.txn_date.isoformat(),
        "description": t.description,
        "merchant": t.merchant,
        "debit": float(t.debit),
        "credit": float(t.credit),
        "signed_amount": float(t.signed_amount),
        "balance": float(t.balance) if t.balance is not None else None,
        "currency": t.currency,
        "category": t.category,
        "txn_type": t.txn_type,
        "categorization_confidence": float(t.categorization_confidence),
        "classification_source": t.classification_source,
        "is_unusual": t.is_unusual,
        "review_status": t.review_status,
        "exclude_from_analytics": t.exclude_from_analytics,
        "is_synthetic": t.is_synthetic
    } for t in items]


@app.patch("/api/transactions/{txn_id}")
def update_transaction(
    txn_id: int,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    txn = db.query(Transaction).filter(Transaction.id == txn_id, Transaction.user_id == current_user.id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    if payload.merchant is not None:
        txn.merchant = payload.merchant.strip()
    if payload.category is not None:
        txn.category = payload.category
        txn.categorization_confidence = Decimal("1.00")
        txn.classification_source = "USER_VERIFIED"
        if payload.category == "Investments and Transfers":
            txn.txn_type = "TRANSFER"
        elif payload.category == "Refunds and Reimbursements":
            txn.txn_type = "REFUND"
    if payload.txn_type is not None:
        txn.txn_type = payload.txn_type
    if payload.review_status is not None:
        txn.review_status = payload.review_status
    if payload.exclude_from_analytics is not None:
        txn.exclude_from_analytics = payload.exclude_from_analytics

    # Apply rule to similar transactions and store custom rule if requested
    if payload.apply_rule_to_similar and payload.category:
        similar = db.query(Transaction).filter(
            Transaction.user_id == current_user.id,
            Transaction.merchant.ilike(txn.merchant)
        ).all()
        for s in similar:
            s.category = payload.category
            s.categorization_confidence = Decimal("1.00")
            s.classification_source = "USER_RULE"
        db.add(Category(
            user_id=current_user.id,
            name=payload.category,
            keyword_pattern=txn.merchant
        ))

    db.commit()
    rebuild_recurring_payments(current_user.id, db)
    rebuild_anomaly_alerts(current_user.id, db)
    return {"message": "Transaction updated and analytics recalculated."}


# ==================== 5. DASHBOARD OVERVIEW & ANALYTICS ====================

@app.get("/api/analytics/overview")
def get_dashboard_overview(
    account_id: Optional[int] = None,
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.exclude_from_analytics == False
    )
    if account_id:
        q = q.filter(Transaction.account_id == account_id)

    all_txns = q.order_by(Transaction.txn_date.asc()).all()
    available_months = sorted({t.txn_date.strftime("%Y-%m") for t in all_txns})
    txns = [t for t in all_txns if t.txn_date.strftime("%Y-%m") == month] if month else all_txns

    total_income = sum(float(t.credit) for t in txns if t.txn_type == "INCOME")
    raw_expenses = sum(float(t.debit) for t in txns if t.txn_type == "EXPENSE")
    total_refunds = sum(float(t.credit) for t in txns if t.txn_type == "REFUND")
    total_transfers = sum(abs(float(t.signed_amount)) for t in txns if t.txn_type == "TRANSFER")
    net_expenses = max(0.0, raw_expenses - total_refunds)
    net_cash_flow = total_income - net_expenses
    savings_rate = ((total_income - net_expenses) / total_income * 100.0) if total_income > 0 else 0.0

    # Days span
    if txns:
        span_days = max(1, (txns[-1].txn_date - txns[0].txn_date).days + 1)
    else:
        span_days = 1
    avg_daily_spend = net_expenses / span_days

    # Category Distribution
    cat_totals: Dict[str, float] = defaultdict(float)
    merchant_totals: Dict[str, float] = defaultdict(float)
    essential_spend = 0.0
    discretionary_spend = 0.0
    weekday_spend = 0.0
    weekend_spend = 0.0
    daily_map: Dict[str, float] = defaultdict(float)

    for t in txns:
        if t.txn_type == "EXPENSE":
            amt = float(t.debit)
            cat_totals[t.category] += amt
            merchant_totals[t.merchant] += amt
            daily_map[t.txn_date.isoformat()] += amt
            if t.category in ESSENTIAL_CATEGORIES:
                essential_spend += amt
            else:
                discretionary_spend += amt
            if t.txn_date.weekday() >= 5:
                weekend_spend += amt
            else:
                weekday_spend += amt

    category_distribution = [
        {
            "category": k,
            "amount": round(v, 2),
            "percentage": round((v / raw_expenses * 100.0), 1) if raw_expenses > 0 else 0.0
        }
        for k, v in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    # Monthly trend across all available months
    monthly_map: Dict[str, Dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expenses": 0.0})
    for t in all_txns:
        ym = t.txn_date.strftime("%Y-%m")
        if t.txn_type == "INCOME":
            monthly_map[ym]["income"] += float(t.credit)
        elif t.txn_type == "EXPENSE":
            monthly_map[ym]["expenses"] += float(t.debit)
        elif t.txn_type == "REFUND":
            monthly_map[ym]["expenses"] = max(0.0, monthly_map[ym]["expenses"] - float(t.credit))

    monthly_trends = [
        {
            "month": ym,
            "income": round(monthly_map[ym]["income"], 2),
            "expenses": round(monthly_map[ym]["expenses"], 2),
            "net_cash_flow": round(monthly_map[ym]["income"] - monthly_map[ym]["expenses"], 2)
        }
        for ym in sorted(monthly_map.keys())
    ]

    top_merchants = [
        {"merchant": m, "amount": round(v, 2)}
        for m, v in sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:8]
    ]

    daily_spending = [
        {"date": d, "amount": round(v, 2)}
        for d, v in sorted(daily_map.items())
    ]

    recurring_items = db.query(RecurringPayment).filter(RecurringPayment.user_id == current_user.id).all()
    recurring_monthly_sum = sum(
        float(r.monthly_equivalent) for r in recurring_items if r.category not in {"Salary and Income", "Freelance or Business Income"}
    )
    unusual_pending_count = db.query(AnomalyAlert).filter(
        AnomalyAlert.user_id == current_user.id,
        AnomalyAlert.review_status == "NEEDS_REVIEW"
    ).count()

    return {
        "available_months": available_months,
        "selected_month": month or "ALL",
        "summary_cards": {
            "total_income": round(total_income, 2),
            "total_expenses": round(net_expenses, 2),
            "total_refunds": round(total_refunds, 2),
            "total_transfers_excluded": round(total_transfers, 2),
            "net_cash_flow": round(net_cash_flow, 2),
            "savings_rate": round(savings_rate, 1),
            "avg_daily_spending": round(avg_daily_spend, 2),
            "recurring_monthly_payments": round(recurring_monthly_sum, 2),
            "transaction_count": len(txns),
            "unusual_pending_count": unusual_pending_count
        },
        "category_distribution": category_distribution,
        "monthly_trends": monthly_trends,
        "top_merchants": top_merchants,
        "daily_spending": daily_spending,
        "essential_vs_discretionary": {
            "essential": round(essential_spend, 2),
            "discretionary": round(discretionary_spend, 2)
        },
        "weekday_vs_weekend": {
            "weekday": round(weekday_spend, 2),
            "weekend": round(weekend_spend, 2)
        }
    }


# ==================== 6. RECURRING, ANOMALIES, HEALTH & BUDGETS ====================

@app.get("/api/recurring")
def get_recurring_payments(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(RecurringPayment).filter(RecurringPayment.user_id == current_user.id).order_by(
        RecurringPayment.monthly_equivalent.desc()
    ).all()
    return [{
        "id": r.id,
        "merchant": r.merchant,
        "category": r.category,
        "typical_amount": float(r.typical_amount),
        "monthly_equivalent": float(r.monthly_equivalent),
        "frequency": r.frequency,
        "occurrences": r.occurrences,
        "last_observed_date": r.last_observed_date.isoformat(),
        "next_expected_date": r.next_expected_date.isoformat(),
        "confidence": float(r.confidence),
        "has_price_increase": r.has_price_increase,
        "price_change_note": r.price_change_note,
        "review_status": r.review_status
    } for r in items]


@app.patch("/api/recurring/{item_id}")
def update_recurring_status(
    item_id: int,
    payload: RecurringStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rec = db.query(RecurringPayment).filter(RecurringPayment.id == item_id, RecurringPayment.user_id == current_user.id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recurring item not found.")
    rec.review_status = payload.review_status
    db.commit()
    return {"message": "Recurring payment status updated."}


@app.get("/api/anomalies")
def get_anomaly_alerts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = db.query(AnomalyAlert).filter(AnomalyAlert.user_id == current_user.id).order_by(AnomalyAlert.id.desc()).all()
    result = []
    for a in alerts:
        t = a.transaction
        result.append({
            "id": a.id,
            "transaction_id": a.transaction_id,
            "txn_date": t.txn_date.isoformat() if t else None,
            "merchant": t.merchant if t else "Unknown",
            "description": t.description if t else "",
            "amount": abs(float(t.signed_amount)) if t else 0.0,
            "category": t.category if t else "Other",
            "detection_method": a.detection_method,
            "severity": a.severity,
            "relative_deviation": float(a.relative_deviation) if a.relative_deviation else None,
            "explanation": a.explanation,
            "review_status": a.review_status
        })
    return result


@app.patch("/api/anomalies/{alert_id}")
def review_anomaly_alert(
    alert_id: int,
    payload: AnomalyActionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    alert = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id, AnomalyAlert.user_id == current_user.id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert.review_status = payload.review_status
    if alert.transaction:
        alert.transaction.review_status = payload.review_status
        if payload.corrected_category:
            alert.transaction.category = payload.corrected_category
            alert.transaction.classification_source = "USER_VERIFIED"
    db.commit()
    return {"message": "Alert review status updated."}


@app.get("/api/financial-health")
def get_financial_health(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = compute_financial_health_score(current_user.id, db)
    if res["overall_score"] is not None:
        snap = FinancialSnapshot(
            user_id=current_user.id,
            reporting_period=res["data_period"],
            overall_score=res["overall_score"],
            policy_applied=res["policy_applied"],
            components_json=res["components"]
        )
        db.add(snap)
        db.commit()
    return res


@app.get("/api/budgets")
def get_budgets_status(
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    txns = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.exclude_from_analytics == False
    ).order_by(Transaction.txn_date.asc()).all()

    months = sorted({t.txn_date.strftime("%Y-%m") for t in txns})
    active_month = month or (months[-1] if months else date.today().strftime("%Y-%m"))

    cat_spend: Dict[str, float] = defaultdict(float)
    for t in txns:
        if t.txn_date.strftime("%Y-%m") == active_month:
            if t.txn_type == "EXPENSE":
                cat_spend[t.category] += float(t.debit)
            elif t.txn_type == "REFUND":
                cat_spend[t.category] = max(0.0, cat_spend[t.category] - float(t.credit))

    budgets = db.query(Budget).filter(Budget.user_id == current_user.id).all()
    budget_rows = []
    for b in budgets:
        target = float(b.target_amount)
        actual = round(cat_spend.get(b.category, 0.0), 2)
        remaining = round(target - actual, 2)
        utilization = round((actual / target * 100.0), 1) if target > 0 else None
        status_label = "UNDEFINED" if target <= 0 else (
            "OVER_BUDGET" if utilization > 100 else (
                "THRESHOLD_ALERT" if utilization >= b.alert_threshold_pct else "ON_TRACK"
            )
        )
        budget_rows.append({
            "id": b.id,
            "category": b.category,
            "target_amount": target,
            "actual_spending": actual,
            "remaining_budget": remaining,
            "utilization_pct": utilization,
            "alert_threshold_pct": b.alert_threshold_pct,
            "status": status_label
        })

    total_actual = round(sum(cat_spend.values()), 2)
    total_target = float(current_user.monthly_total_budget or 0.0)

    return {
        "month": active_month,
        "available_months": months,
        "monthly_total_budget": total_target,
        "monthly_total_actual": total_actual,
        "monthly_total_remaining": round(total_target - total_actual, 2) if total_target > 0 else None,
        "monthly_total_utilization_pct": round(total_actual / total_target * 100.0, 1) if total_target > 0 else None,
        "category_budgets": budget_rows,
        "accounting_policy": "Eligible spending includes verified EXPENSE debits minus REFUND credits in the same period. Internal transfers and excluded transactions are omitted."
    }


@app.post("/api/budgets")
def upsert_category_budget(
    payload: BudgetUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing = db.query(Budget).filter(
        Budget.user_id == current_user.id,
        Budget.category == payload.category
    ).first()
    if existing:
        existing.target_amount = Decimal(str(round(payload.target_amount, 2)))
        existing.alert_threshold_pct = payload.alert_threshold_pct
    else:
        db.add(Budget(
            user_id=current_user.id,
            category=payload.category,
            target_amount=Decimal(str(round(payload.target_amount, 2))),
            alert_threshold_pct=payload.alert_threshold_pct
        ))
    db.commit()
    return {"message": f"Budget for {payload.category} saved."}


@app.put("/api/budgets/total")
def update_total_budget(
    payload: TotalBudgetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_user.monthly_total_budget = Decimal(str(round(payload.monthly_total_budget, 2)))
    db.commit()
    return {"message": "Monthly total spending limit updated."}


# ==================== 7. AI ASSISTANT, REPORTS & PRIVACY DELETION ====================

@app.post("/api/assistant/query")
def query_assistant(
    payload: AssistantQuery,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return answer_grounded_financial_query(
        question=payload.question,
        user=current_user,
        db=db,
        use_local_llm=payload.use_local_llm
    )


@app.get("/api/reports/export")
def export_financial_report(
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    txns = db.query(Transaction).filter(Transaction.user_id == current_user.id).order_by(Transaction.txn_date.desc()).all()
    if month:
        txns = [t for t in txns if t.txn_date.strftime("%Y-%m") == month]

    total_inc = sum(float(t.credit) for t in txns if t.txn_type == "INCOME")
    raw_exp = sum(float(t.debit) for t in txns if t.txn_type == "EXPENSE")
    ref = sum(float(t.credit) for t in txns if t.txn_type == "REFUND")
    net_exp = max(0.0, raw_exp - ref)
    health = compute_financial_health_score(current_user.id, db)

    summary = {
        "period": month or "All Imported History",
        "total_income": round(total_inc, 2),
        "total_expenses": round(net_exp, 2),
        "net_cash_flow": round(total_inc - net_exp, 2),
        "savings_rate": round(((total_inc - net_exp) / total_inc * 100.0), 1) if total_inc > 0 else 0.0,
        "health_score": health.get("overall_score", "N/A")
    }

    if format == "csv":
        data = generate_csv_report(txns)
        return Response(
            content=data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=finsight_transactions.csv"}
        )
    elif format == "xlsx":
        data = generate_excel_report(txns, summary)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=finsight_analysis.xlsx"}
        )
    else:
        data = generate_pdf_report(current_user, txns, summary, health)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=finsight_financial_report.pdf"}
        )


@app.delete("/api/privacy/purge-data")
def purge_all_financial_data(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(AnomalyAlert).filter(AnomalyAlert.user_id == current_user.id).delete()
    db.query(RecurringPayment).filter(RecurringPayment.user_id == current_user.id).delete()
    db.query(Transaction).filter(Transaction.user_id == current_user.id).delete()
    db.query(Statement).filter(Statement.user_id == current_user.id).delete()
    db.query(FinancialSnapshot).filter(FinancialSnapshot.user_id == current_user.id).delete()
    db.commit()
    return {"message": "All uploaded statements, transactions, and derived analytics have been permanently purged."}


@app.delete("/api/privacy/delete-account")
def delete_entire_user_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(current_user)
    db.commit()
    return {"message": "Your user account and all associated records have been permanently deleted."}