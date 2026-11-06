import re
from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session
import httpx

from ..models import Transaction, Category, RecurringPayment, AnomalyAlert, Budget, User
from ..config import settings

ESSENTIAL_CATEGORIES = {
    "Groceries", "Housing and Rent", "Utilities", "Healthcare",
    "Education", "Insurance", "EMI and Loan Payments", "Transportation"
}

DEFAULT_RULES = [
    ("Salary and Income", "INCOME", r"salary|payroll|stipend|neft cr.*corp|dividend|interest credit"),
    ("Freelance or Business Income", "INCOME", r"upwork|fiverr|freelance|consulting fee|client invoice|razorpay settlement"),
    ("Refunds and Reimbursements", "REFUND", r"refund|reversal|cashback|reimbursement|chargeback|rev-"),
    ("Investments and Transfers", "TRANSFER", r"self transfer|neft to self|zerodha|groww|kuvera|sip|mutual fund|cc bill pymt|credit card payment|internal transfer"),
    ("Housing and Rent", "EXPENSE", r"house rent|landlord|nobroker|maintenance charge|society due|apartment rent"),
    ("EMI and Loan Payments", "EXPENSE", r"emi|loan repay|bajaj finance|hdfc loan|home loan|auto loan|equated monthly"),
    ("Groceries", "EXPENSE", r"blinkit|zepto|bigbasket|instamart|dmart|reliance smart|supermarket|grocery|more retail"),
    ("Food and Dining", "EXPENSE", r"swiggy|zomato|starbucks|mcdonald|dominos|kfc|restaurant|cafe|dining|bistro|haldiram"),
    ("Transportation", "EXPENSE", r"uber|ola|rapido|namma yatri|irctc|metro|indian oil|hpcl|bpcl|petrol|fuel|fastag|shell"),
    ("Utilities", "EXPENSE", r"bescom|electricity|water bill|indane|bharatgas|jiofiber|airtel|act fibernet|vi postpaid|broadband|recharge"),
    ("Entertainment", "EXPENSE", r"netflix|spotify|prime video|hotstar|youtube premium|bookmyshow|pvr|inox|steam|playstation"),
    ("Shopping", "EXPENSE", r"amazon|flipkart|myntra|ajio|nykaa|decathlon|ikea|zara|croma|reliance digital"),
    ("Healthcare", "EXPENSE", r"apollo|pharmeasy|1mg|netmeds|hospital|clinic|diagnostic|dental|medical|pharmacy"),
    ("Education", "EXPENSE", r"coursera|udemy|college fee|tuition|university|infosys springboard|books|exam fee"),
    ("Insurance", "EXPENSE", r"lic|hdfc ergo|icici lombard|star health|policybazaar|term plan|insurance premium"),
    ("Travel", "EXPENSE", r"makemytrip|goibibo|indigo|air india|booking\.com|airbnb|oyo|ksrtc|redbus|hotel"),
    ("Bank Charges", "EXPENSE", r"sms charge|min bal|annual fee|late fee|penal charge|atm fee|convenience fee|gst on fee"),
]


def extract_clean_merchant(description: str) -> str:
    s = description.strip()
    # Clean common Indian UPI / NEFT prefixes: e.g., UPI/SWIGGY/9823421/Pay -> SWIGGY
    upi_match = re.search(r"(?:UPI|IMPS|NEFT|POS|ACH)[/-](?:CR[/-]|DR[/-])?([A-Za-z0-9\s.&'-]{3,28})", s, re.IGNORECASE)
    if upi_match:
        candidate = upi_match.group(1).strip()
        if not candidate.isdigit():
            return candidate.title()
    cleaned = re.sub(r"[^A-Za-z0-9\s&'-]", " ", s)
    cleaned = re.sub(r"\b\d{4,}\b", "", cleaned)
    tokens = [w for w in cleaned.split() if w.upper() not in {"UPI", "POS", "NEFT", "IMPS", "ACH", "DR", "CR", "REF", "TXN", "IN"}]
    return " ".join(tokens[:3]).title() if tokens else "Unknown Merchant"


def categorize_single_transaction(
    description: str,
    merchant: str,
    signed_amount: float,
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    text_blob = f"{merchant} {description}".lower()

    # Layer 1: Previously corrected user transactions or custom user rules
    user_rules = db.query(Category).filter(Category.user_id == user_id, Category.keyword_pattern.isnot(None)).all()
    for ur in user_rules:
        if ur.keyword_pattern and re.search(ur.keyword_pattern.lower(), text_blob):
            txn_type = "INCOME" if signed_amount > 0 else "EXPENSE"
            if ur.name == "Investments and Transfers":
                txn_type = "TRANSFER"
            elif ur.name == "Refunds and Reimbursements":
                txn_type = "REFUND"
            return {"category": ur.name, "txn_type": txn_type, "confidence": 0.98, "source": "USER_RULE"}

    # Layer 2: Deterministic Keyword & Regex Rules
    for cat_name, default_type, pattern in DEFAULT_RULES:
        if re.search(pattern, text_blob, re.IGNORECASE):
            if cat_name == "Refunds and Reimbursements" and signed_amount > 0:
                return {"category": cat_name, "txn_type": "REFUND", "confidence": 0.92, "source": "RULE"}
            if cat_name == "Investments and Transfers":
                return {"category": cat_name, "txn_type": "TRANSFER", "confidence": 0.90, "source": "RULE"}
            if signed_amount > 0 and default_type == "INCOME":
                return {"category": cat_name, "txn_type": "INCOME", "confidence": 0.94, "source": "RULE"}
            if signed_amount < 0 and default_type == "EXPENSE":
                return {"category": cat_name, "txn_type": "EXPENSE", "confidence": 0.91, "source": "RULE"}

    # Layer 3: Optional Scikit-Learn Classifier trained on User's confirmed history
    history = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.category != "Other",
        Transaction.categorization_confidence >= Decimal("0.80")
    ).limit(500).all()

    if len(history) >= 15:
        corpus = [f"{h.merchant} {h.description}".lower() for h in history]
        labels = [h.category for h in history]
        if len(set(labels)) >= 3:
            try:
                vec = TfidfVectorizer(ngram_range=(1, 2), max_features=400)
                X = vec.fit_transform(corpus)
                clf = LogisticRegression(max_iter=200)
                clf.fit(X, labels)
                probs = clf.predict_proba(vec.transform([text_blob]))[0]
                best_idx = int(np.argmax(probs))
                best_prob = float(probs[best_idx])
                pred_cat = clf.classes_[best_idx]
                if best_prob >= 0.55:
                    t_type = "INCOME" if signed_amount > 0 else "EXPENSE"
                    return {
                        "category": str(pred_cat),
                        "txn_type": t_type,
                        "confidence": round(best_prob, 2),
                        "source": "ML_TFIDF"
                    }
            except Exception:
                pass

    # Layer 4: Conservative Uncertain Fallback
    fallback_cat = "Salary and Income" if signed_amount > 0 else "Other"
    fallback_type = "INCOME" if signed_amount > 0 else "EXPENSE"
    return {
        "category": fallback_cat,
        "txn_type": fallback_type,
        "confidence": 0.45,
        "source": "FALLBACK_UNCERTAIN"
    }


def rebuild_recurring_payments(user_id: int, db: Session) -> List[RecurringPayment]:
    """
    Detects weekly, monthly, quarterly, and annual recurring expenses/income,
    plus silent price hikes. Requires >= 2 occurrences (never labels a single payment as a subscription).
    """
    existing_status = {
        r.merchant.lower(): r.review_status
        for r in db.query(RecurringPayment).filter(RecurringPayment.user_id == user_id).all()
    }
    db.query(RecurringPayment).filter(RecurringPayment.user_id == user_id).delete()

    txns = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.exclude_from_analytics == False,
        Transaction.txn_type.in_(["EXPENSE", "INCOME"])
    ).order_by(Transaction.txn_date.asc()).all()

    by_merchant: Dict[str, List[Transaction]] = defaultdict(list)
    for t in txns:
        by_merchant[t.merchant.strip()].append(t)

    detected: List[RecurringPayment] = []

    for merchant, items in by_merchant.items():
        if len(items) < 2:
            continue
        # Collapse same-day transactions for interval calculation
        dates = [i.txn_date for i in items]
        amounts = [float(abs(i.signed_amount)) for i in items]
        intervals = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates)) if (dates[i] - dates[i - 1]).days > 0]
        if not intervals:
            continue

        med_interval = float(np.median(intervals))
        mean_amt = float(np.mean(amounts))
        std_amt = float(np.std(amounts))
        cv_amt = std_amt / mean_amt if mean_amt > 0 else 1.0

        # Require reasonable amount consistency (CV <= 0.35)
        if cv_amt > 0.35:
            continue

        freq = None
        monthly_mult = 1.0
        expected_delta = 30
        if 5 <= med_interval <= 9 and len(items) >= 3:
            freq = "WEEKLY"
            monthly_mult = 4.33
            expected_delta = 7
        elif 25 <= med_interval <= 36:
            freq = "MONTHLY"
            monthly_mult = 1.0
            expected_delta = 30
        elif 80 <= med_interval <= 100:
            freq = "QUARTERLY"
            monthly_mult = 1.0 / 3.0
            expected_delta = 91
        elif 350 <= med_interval <= 380:
            freq = "ANNUAL"
            monthly_mult = 1.0 / 12.0
            expected_delta = 365

        if not freq:
            continue

        latest_amt = amounts[-1]
        prev_median = float(np.median(amounts[:-1]))
        has_hike = False
        hike_note = None
        if prev_median > 0 and latest_amt > prev_median * 1.05:
            pct_increase = ((latest_amt - prev_median) / prev_median) * 100
            has_hike = True
            hike_note = f"Latest charge ({latest_amt:,.2f}) increased by {pct_increase:.1f}% vs prior median ({prev_median:,.2f})."

        conf = min(0.98, round(0.65 + min(len(items), 6) * 0.05 - (cv_amt * 0.2), 2))
        last_dt = dates[-1]
        next_dt = last_dt + timedelta(days=expected_delta)

        rec = RecurringPayment(
            user_id=user_id,
            merchant=merchant,
            category=items[-1].category,
            typical_amount=Decimal(str(round(latest_amt, 2))),
            monthly_equivalent=Decimal(str(round(latest_amt * monthly_mult, 2))),
            frequency=freq,
            occurrences=len(items),
            last_observed_date=last_dt,
            next_expected_date=next_dt,
            confidence=Decimal(str(conf)),
            has_price_increase=has_hike,
            price_change_note=hike_note,
            review_status=existing_status.get(merchant.lower(), "UNREVIEWED")
        )
        db.add(rec)
        detected.append(rec)

    db.commit()
    return detected


def rebuild_anomaly_alerts(user_id: int, db: Session) -> List[AnomalyAlert]:
    """
    Explainable unusual-activity detector using:
    1. Category Median Absolute Deviation (MAD) / Robust Ratio
    2. Rapid Duplicate / Velocity Spike check
    3. Scikit-Learn IsolationForest on multi-feature matrix (when N >= 20)
    Uses strictly cautious language ("Review recommended") and preserves prior user review status.
    """
    existing_reviews = {
        a.transaction_id: a.review_status
        for a in db.query(AnomalyAlert).filter(AnomalyAlert.user_id == user_id).all()
    }
    db.query(AnomalyAlert).filter(AnomalyAlert.user_id == user_id).delete()

    txns = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.exclude_from_analytics == False,
        Transaction.txn_type == "EXPENSE"
    ).order_by(Transaction.txn_date.asc()).all()

    if len(txns) < 5:
        db.commit()
        return []

    by_cat: Dict[str, List[Transaction]] = defaultdict(list)
    for t in txns:
        t.is_unusual = False
        by_cat[t.category].append(t)

    alerts_by_txn: Dict[int, AnomalyAlert] = {}

    # 1. Category-level Robust Ratio & MAD Check
    for cat, items in by_cat.items():
        if cat in {"Housing and Rent", "EMI and Loan Payments"} or len(items) < 3:
            continue
        amts = np.array([float(abs(i.signed_amount)) for i in items])
        median_amt = float(np.median(amts))
        mad = float(np.median(np.abs(amts - median_amt)))
        for item in items:
            val = float(abs(item.signed_amount))
            ratio = val / median_amt if median_amt > 0 else 1.0
            mod_z = (0.6745 * abs(val - median_amt) / mad) if mad > 0 else 0.0

            if val >= 1500 and ratio >= 2.6 and (mod_z >= 3.2 or ratio >= 3.0):
                severity = "HIGH" if ratio >= 4.0 else "MEDIUM"
                alerts_by_txn[item.id] = AnomalyAlert(
                    user_id=user_id,
                    transaction_id=item.id,
                    detection_method="ROBUST_MAD_RATIO",
                    severity=severity,
                    relative_deviation=Decimal(str(round(ratio, 2))),
                    explanation=(
                        f"Review recommended: This {cat} expense of {val:,.2f} is {ratio:.1f}x larger "
                        f"than your historical category median of {median_amt:,.2f} across {len(items)} transactions."
                    ),
                    review_status=existing_reviews.get(item.id, "NEEDS_REVIEW")
                )

    # 2. Rapid Same-Merchant Velocity Check (same merchant charged twice within 24 hours for same amount)
    for i in range(1, len(txns)):
        prev_t, curr_t = txns[i - 1], txns[i]
        days_diff = abs((curr_t.txn_date - prev_t.txn_date).days)
        if (
            curr_t.merchant == prev_t.merchant
            and days_diff <= 1
            and abs(float(curr_t.signed_amount) - float(prev_t.signed_amount)) < 1.0
            and abs(float(curr_t.signed_amount)) >= 500
            and curr_t.id not in alerts_by_txn
        ):
            amt = abs(float(curr_t.signed_amount))
            alerts_by_txn[curr_t.id] = AnomalyAlert(
                user_id=user_id,
                transaction_id=curr_t.id,
                detection_method="VELOCITY_REPEAT_CHECK",
                severity="MEDIUM",
                relative_deviation=Decimal("2.00"),
                explanation=(
                    f"Unusual activity detected: Two identical charges of {amt:,.2f} at '{curr_t.merchant}' "
                    f"occurred within {days_diff} day(s). Review recommended to confirm this was not an accidental double charge."
                ),
                review_status=existing_reviews.get(curr_t.id, "NEEDS_REVIEW")
            )

    # 3. Scikit-Learn IsolationForest for Global Multi-Dimensional Outliers (when N >= 20)
    if len(txns) >= 20:
        overall_median = float(np.median([abs(float(t.signed_amount)) for t in txns]))
        features = []
        for t in txns:
            amt = abs(float(t.signed_amount))
            day_of_month = t.txn_date.day
            is_weekend = 1.0 if t.txn_date.weekday() >= 5 else 0.0
            features.append([ np.log1p(amt), day_of_month / 31.0, is_weekend ])
        X = np.array(features)
        iso = IsolationForest(contamination=0.06, random_state=42)
        preds = iso.fit_predict(X)
        for t, pred in zip(txns, preds):
            amt = abs(float(t.signed_amount))
            if pred == -1 and amt > overall_median * 3.5 and t.id not in alerts_by_txn:
                if t.category not in {"Housing and Rent", "EMI and Loan Payments"}:
                    ratio = amt / overall_median if overall_median > 0 else 1.0
                    alerts_by_txn[t.id] = AnomalyAlert(
                        user_id=user_id,
                        transaction_id=t.id,
                        detection_method="ISOLATION_FOREST_ML",
                        severity="MEDIUM",
                        relative_deviation=Decimal(str(round(ratio, 2))),
                        explanation=(
                            f"Review recommended: Multivariate Isolation Forest flagged this transaction ({amt:,.2f}) "
                            f"as {ratio:.1f}x above your account-wide median spend ({overall_median:,.2f})."
                        ),
                        review_status=existing_reviews.get(t.id, "NEEDS_REVIEW")
                    )

    created_alerts = []
    for t_id, alert in alerts_by_txn.items():
        db.add(alert)
        txn_obj = db.query(Transaction).filter(Transaction.id == t_id).first()
        if txn_obj:
            txn_obj.is_unusual = True
            txn_obj.review_status = alert.review_status
        created_alerts.append(alert)

    db.commit()
    return created_alerts


def compute_financial_health_score(user_id: int, db: Session) -> Dict[str, Any]:
    """
    Transparent 0-100 educational Financial Health Indicator.
    Weights:
      1. Savings Rate (30%)
      2. Cash Flow Stability (25%)
      3. Spending Control (20%)
      4. Recurring Expense Burden (15%)
      5. Expense Diversification & Stability (10%)
    Implements explicit Missing-Data Weight Renormalization Policy.
    """
    txns = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.exclude_from_analytics == False
    ).order_by(Transaction.txn_date.asc()).all()

    if not txns:
        return {
            "overall_score": None,
            "status": "UNAVAILABLE",
            "policy_applied": "INSUFFICIENT_DATA_POLICY: Score unavailable until at least one statement with transactions is imported.",
            "data_period": "No data",
            "components": [],
            "positive_indicators": [],
            "areas_for_attention": ["Upload a bank statement or load the synthetic demo dataset to compute your Financial Health Score."],
            "improvement_suggestions": []
        }

    # Aggregate Income, Expenses, Refunds (excluding Transfers)
    total_income = sum(float(t.credit) for t in txns if t.txn_type == "INCOME")
    raw_expenses = sum(float(t.debit) for t in txns if t.txn_type == "EXPENSE")
    total_refunds = sum(float(t.credit) for t in txns if t.txn_type == "REFUND")
    net_expenses = max(0.0, raw_expenses - total_refunds)

    monthly_map: Dict[str, Dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for t in txns:
        ym = t.txn_date.strftime("%Y-%m")
        if t.txn_type == "INCOME":
            monthly_map[ym]["income"] += float(t.credit)
        elif t.txn_type == "EXPENSE":
            monthly_map[ym]["expense"] += float(t.debit)
        elif t.txn_type == "REFUND":
            monthly_map[ym]["expense"] = max(0.0, monthly_map[ym]["expense"] - float(t.credit))

    months_sorted = sorted(monthly_map.keys())
    num_months = len(months_sorted)
    period_label = f"{txns[0].txn_date.isoformat()} to {txns[-1].txn_date.isoformat()} ({num_months} month(s))"

    components = []
    positives = []
    attentions = []
    suggestions = []

    # --- Component 1: Savings Rate (Weight 0.30) ---
    # Scoring curve: 25%+ savings rate = 100 pts; 0% = 30 pts; negative scales down to 0
    if total_income > 0:
        savings_rate_pct = ((total_income - net_expenses) / total_income) * 100.0
        if savings_rate_pct >= 25.0:
            c1_score = 100.0
        elif savings_rate_pct >= 0.0:
            c1_score = 30.0 + (savings_rate_pct / 25.0) * 70.0
        else:
            c1_score = max(0.0, 30.0 + savings_rate_pct)
        c1_score = round(min(100.0, max(0.0, c1_score)), 1)
        components.append({
            "key": "savings_rate",
            "name": "Savings Rate",
            "weight": 0.30,
            "available": True,
            "raw_metric": f"{savings_rate_pct:.1f}%",
            "normalized_score": c1_score,
            "formula": "Savings Rate = (Observed Income - Net Expenses) / Observed Income × 100 (Target >= 25% for 100/100)",
            "explanation": f"Saved {total_income - net_expenses:,.2f} out of {total_income:,.2f} total observed income."
        })
        if savings_rate_pct >= 20.0:
            positives.append(f"Strong savings rate of {savings_rate_pct:.1f}% across the observed period.")
        else:
            attentions.append(f"Savings rate is {savings_rate_pct:.1f}% (below the 20% healthy benchmark).")
    else:
        components.append({
            "key": "savings_rate",
            "name": "Savings Rate",
            "weight": 0.30,
            "available": False,
            "raw_metric": "Unavailable (Zero Income)",
            "normalized_score": None,
            "formula": "Savings Rate = (Income - Expenses) / Income × 100",
            "explanation": "No income credits were observed in this period. Component excluded rather than inventing income."
        })
        attentions.append("No salary or income deposits detected; Savings Rate and Recurring Burden could not be scored.")

    # --- Component 2: Cash Flow Stability (Weight 0.25) ---
    if num_months >= 2:
        pos_months = sum(1 for m in months_sorted if (monthly_map[m]["income"] - monthly_map[m]["expense"]) >= 0)
        stability_ratio = (pos_months / num_months) * 100.0
        components.append({
            "key": "cash_flow_stability",
            "name": "Cash Flow Stability",
            "weight": 0.25,
            "available": True,
            "raw_metric": f"{pos_months}/{num_months} positive months ({stability_ratio:.0f}%)",
            "normalized_score": round(stability_ratio, 1),
            "formula": "Cash Flow Stability = (Months with Income >= Expenses) / Total Eligible Months × 100",
            "explanation": f"{pos_months} of {num_months} observed months maintained non-negative net cash flow."
        })
        if stability_ratio == 100.0:
            positives.append(f"Positive net cash flow maintained in all {num_months} observed months.")
    else:
        # Single month fallback
        only_m = months_sorted[0]
        net_m = monthly_map[only_m]["income"] - monthly_map[only_m]["expense"]
        c2_score = 85.0 if net_m >= 0 else 25.0
        components.append({
            "key": "cash_flow_stability",
            "name": "Cash Flow Stability",
            "weight": 0.25,
            "available": True,
            "raw_metric": "1 month observed (Limited History)",
            "normalized_score": c2_score,
            "formula": "Proportion of historical months with Net Cash Flow >= 0 (Minimum 2 months recommended)",
            "explanation": "Single month available; score reflects current period cash flow sign with limited-history cap."
        })

    # --- Component 3: Spending Control / Budget Adherence (Weight 0.20) ---
    budgets = db.query(Budget).filter(Budget.user_id == user_id).all()
    latest_month = months_sorted[-1]
    latest_cat_spend: Dict[str, float] = defaultdict(float)
    for t in txns:
        if t.txn_date.strftime("%Y-%m") == latest_month and t.txn_type == "EXPENSE":
            latest_cat_spend[t.category] += float(t.debit)

    if budgets:
        adherence_scores = []
        over_budget_cats = []
        for b in budgets:
            target = float(b.target_amount)
            if target <= 0:
                continue
            actual = latest_cat_spend.get(b.category, 0.0)
            util = (actual / target) * 100.0
            if util <= 100.0:
                adherence_scores.append(100.0 - max(0.0, (util - 85.0) * 0.5))
            else:
                over_pct = util - 100.0
                adherence_scores.append(max(0.0, 90.0 - over_pct * 1.8))
                over_budget_cats.append((b.category, actual, target))

        if adherence_scores:
            c3_score = round(float(np.mean(adherence_scores)), 1)
            components.append({
                "key": "spending_control",
                "name": "Spending Control (Budget Adherence)",
                "weight": 0.20,
                "available": True,
                "raw_metric": f"{len(budgets) - len(over_budget_cats)}/{len(budgets)} categories within budget",
                "normalized_score": c3_score,
                "formula": "Mean category budget adherence score in latest month (100% if Spend <= Target; penalized proportionally on overrun)",
                "explanation": f"Evaluated across {len(adherence_scores)} configured category budgets for {latest_month}."
            })
            for cat_n, act_v, tgt_v in over_budget_cats:
                diff = act_v - tgt_v
                attentions.append(f"{cat_n} exceeded its monthly budget of {tgt_v:,.0f} by {diff:,.0f} in {latest_month}.")
                suggestions.append(
                    f"Reducing {cat_n} spending by {diff:,.0f}/month to match your {tgt_v:,.0f} target would directly improve your Spending Control score."
                )
        else:
            components.append({
                "key": "spending_control",
                "name": "Spending Control (Budget Adherence)",
                "weight": 0.20,
                "available": False,
                "raw_metric": "No positive budgets set",
                "normalized_score": None,
                "formula": "Budget Utilization = Eligible Spending / Target Budget × 100",
                "explanation": "Zero-value budgets configured; excluded without penalty."
            })
    else:
        components.append({
            "key": "spending_control",
            "name": "Spending Control (Budget Adherence)",
            "weight": 0.20,
            "available": False,
            "raw_metric": "No budgets configured",
            "normalized_score": None,
            "formula": "Budget Utilization = Eligible Spending / Target Budget × 100",
            "explanation": "You have not configured category budgets yet. Per fairness policy, this component is excluded rather than penalizing you."
        })

    # --- Component 4: Recurring Expense Burden (Weight 0.15) ---
    recurring_items = db.query(RecurringPayment).filter(RecurringPayment.user_id == user_id).all()
    monthly_recurring_total = sum(
        float(r.monthly_equivalent) for r in recurring_items if r.category not in {"Salary and Income", "Freelance or Business Income"}
    )
    avg_monthly_income = (total_income / num_months) if (num_months > 0 and total_income > 0) else 0.0

    if avg_monthly_income > 0:
        burden_pct = (monthly_recurring_total / avg_monthly_income) * 100.0
        # <= 30% fixed burden = 100 pts; 70%+ = 10 pts
        if burden_pct <= 30.0:
            c4_score = 100.0
        elif burden_pct >= 75.0:
            c4_score = 10.0
        else:
            c4_score = 100.0 - ((burden_pct - 30.0) / 45.0) * 90.0
        c4_score = round(max(0.0, min(100.0, c4_score)), 1)
        components.append({
            "key": "recurring_burden",
            "name": "Recurring Expense Burden",
            "weight": 0.15,
            "available": True,
            "raw_metric": f"{burden_pct:.1f}% of monthly income",
            "normalized_score": c4_score,
            "formula": "Recurring Burden = Estimated Monthly Fixed/Recurring Outflows / Average Monthly Income × 100",
            "explanation": f"Estimated recurring commitments of {monthly_recurring_total:,.0f}/month vs {avg_monthly_income:,.0f}/month average income (cash-flow indicator only)."
        })
        if burden_pct <= 35.0:
            positives.append(f"Fixed recurring obligations consume a manageable {burden_pct:.1f}% of monthly income.")
        else:
            attentions.append(f"Recurring commitments represent {burden_pct:.1f}% of average monthly income.")
    else:
        components.append({
            "key": "recurring_burden",
            "name": "Recurring Expense Burden",
            "weight": 0.15,
            "available": False,
            "raw_metric": "Unavailable (Zero Income)",
            "normalized_score": None,
            "formula": "Recurring Burden = Monthly Recurring Expenses / Monthly Income × 100",
            "explanation": "Cannot compute recurring-to-income ratio without observed income."
        })

    # --- Component 5: Expense Diversification & Volatility (Weight 0.10) ---
    monthly_expenses_list = [monthly_map[m]["expense"] for m in months_sorted if monthly_map[m]["expense"] > 0]
    if len(monthly_expenses_list) >= 2:
        mean_exp = float(np.mean(monthly_expenses_list))
        std_exp = float(np.std(monthly_expenses_list))
        cv_exp = (std_exp / mean_exp) if mean_exp > 0 else 0.0
        # CV <= 0.15 -> 100 pts; CV >= 0.65 -> 20 pts
        c5_score = round(max(15.0, min(100.0, 100.0 - max(0.0, cv_exp - 0.12) * 150.0)), 1)
        components.append({
            "key": "expense_stability",
            "name": "Expense Diversification & Volatility",
            "weight": 0.10,
            "available": True,
            "raw_metric": f"CV = {cv_exp:.2f} ({len(monthly_expenses_list)} months)",
            "normalized_score": c5_score,
            "formula": "Coefficient of Variation (CV) = StdDev(Monthly Expenses) / Mean(Monthly Expenses)",
            "explanation": f"Month-to-month spending variation is {cv_exp * 100:.1f}% around an average monthly spend of {mean_exp:,.0f}."
        })
    else:
        components.append({
            "key": "expense_stability",
            "name": "Expense Diversification & Volatility",
            "weight": 0.10,
            "available": False,
            "raw_metric": "Requires >= 2 months of data",
            "normalized_score": None,
            "formula": "Coefficient of Variation (CV) = StdDev(Monthly Expenses) / Mean(Monthly Expenses)",
            "explanation": "Only 1 month of spending history is available; multi-month volatility cannot be measured yet."
        })

    # Calculate Overall Score using Renormalized Weights Policy
    avail_comps = [c for c in components if c["available"] and c["normalized_score"] is not None]
    avail_weight_sum = sum(c["weight"] for c in avail_comps)

    if avail_weight_sum == 0:
        overall_score = None
        policy_msg = "UNAVAILABLE_POLICY: Insufficient valid components to compute a reliable score."
    elif avail_weight_sum < 0.999:
        raw_weighted = sum(c["normalized_score"] * (c["weight"] / avail_weight_sum) for c in avail_comps)
        overall_score = int(round(min(100.0, max(0.0, raw_weighted))))
        policy_msg = (
            f"RENORMALIZED_WEIGHTS_POLICY: Score computed across {len(avail_comps)}/5 available components "
            f"(representing {avail_weight_sum * 100:.0f}% of base weights, proportionally renormalized to 100%)."
        )
    else:
        raw_weighted = sum(c["normalized_score"] * c["weight"] for c in avail_comps)
        overall_score = int(round(min(100.0, max(0.0, raw_weighted))))
        policy_msg = (
            "FULL_5_PILLAR_FORMULA: Overall Score = (Savings×0.30) + (CashFlow×0.25) + "
            "(SpendingControl×0.20) + (RecurringBurden×0.15) + (ExpenseStability×0.10)."
        )

    # Generate evidence-based month-over-month category suggestions
    if len(months_sorted) >= 2:
        prev_m, curr_m = months_sorted[-2], months_sorted[-1]
        prev_cats: Dict[str, float] = defaultdict(float)
        curr_cats: Dict[str, float] = defaultdict(float)
        for t in txns:
            ym = t.txn_date.strftime("%Y-%m")
            if t.txn_type == "EXPENSE":
                if ym == prev_m:
                    prev_cats[t.category] += float(t.debit)
                elif ym == curr_m:
                    curr_cats[t.category] += float(t.debit)
        for cat_k, curr_v in sorted(curr_cats.items(), key=lambda x: x[1], reverse=True):
            prev_v = prev_cats.get(cat_k, 0.0)
            if prev_v >= 500 and curr_v > prev_v * 1.12:
                pct_inc = ((curr_v - prev_v) / prev_v) * 100.0
                delta = curr_v - prev_v
                suggestions.append(
                    f"{cat_k} expenses increased by {pct_inc:.1f}% in {curr_m} ({curr_v:,.0f} vs {prev_v:,.0f} in {prev_m}). "
                    f"Trimming this category back to prior levels could free up {delta:,.0f}/month if spending decreases by that amount."
                )

    return {
        "overall_score": overall_score,
        "status": "COMPLETE" if avail_weight_sum >= 0.999 else "PARTIAL_RENORMALIZED",
        "policy_applied": policy_msg,
        "data_period": period_label,
        "components": components,
        "positive_indicators": positives,
        "areas_for_attention": attentions,
        "improvement_suggestions": suggestions[:5]
    }


def answer_grounded_financial_query(
    question: str,
    user: User,
    db: Session,
    use_local_llm: bool = False
) -> Dict[str, Any]:
    """
    Answers user questions strictly using deterministic SQL/Pandas calculations over the authenticated
    user's data. Never invents transactions or exposes another user's records.
    """
    q = question.lower().strip()
    txns = db.query(Transaction).filter(
        Transaction.user_id == user.id,
        Transaction.exclude_from_analytics == False
    ).order_by(Transaction.txn_date.asc()).all()

    if not txns:
        return {
            "answer": "You currently have no imported transactions in your account. Please upload a bank statement or click 'Load Synthetic Demo Data' to start analyzing your finances.",
            "grounding_facts": [],
            "engine_used": "DETERMINISTIC_GROUNDING_ENGINE",
            "period_referenced": "None"
        }

    period_str = f"{txns[0].txn_date.isoformat()} to {txns[-1].txn_date.isoformat()}"
    total_inc = sum(float(t.credit) for t in txns if t.txn_type == "INCOME")
    total_exp = sum(float(t.debit) for t in txns if t.txn_type == "EXPENSE")
    total_ref = sum(float(t.credit) for t in txns if t.txn_type == "REFUND")
    net_exp = max(0.0, total_exp - total_ref)
    net_cf = total_inc - net_exp
    savings_rate = ((total_inc - net_exp) / total_inc * 100.0) if total_inc > 0 else 0.0

    by_cat: Dict[str, float] = defaultdict(float)
    by_month_cat: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t.txn_type == "EXPENSE":
            by_cat[t.category] += float(t.debit)
            by_month_cat[t.txn_date.strftime("%Y-%m")][t.category] += float(t.debit)

    top_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
    months = sorted(by_month_cat.keys())
    cur = user.currency

    recurring = db.query(RecurringPayment).filter(RecurringPayment.user_id == user.id).all()
    alerts = db.query(AnomalyAlert).filter(AnomalyAlert.user_id == user.id).all()
    health = compute_financial_health_score(user.id, db)

    facts = [
        f"Period analyzed: {period_str} ({len(txns)} verified transactions)",
        f"Total Income: {cur} {total_inc:,.2f} | Net Expenses: {cur} {net_exp:,.2f} | Net Cash Flow: {cur} {net_cf:,.2f}",
        f"Observed Savings Rate: {savings_rate:.1f}% | Financial Health Score: {health['overall_score']}/100"
    ]

    # Deterministic intent routing for exact mathematical answers
    if any(k in q for k in ["food", "dining", "grocery", "groceries", "swiggy", "zomato"]):
        food_spend = by_cat.get("Food and Dining", 0.0)
        groc_spend = by_cat.get("Groceries", 0.0)
        latest_m = months[-1] if months else "N/A"
        last_m_food = by_month_cat[latest_m].get("Food and Dining", 0.0) if months else 0.0
        answer = (
            f"Across the full period ({period_str}), you spent **{cur} {food_spend:,.2f}** on **Food and Dining** "
            f"and **{cur} {groc_spend:,.2f}** on **Groceries** (Combined: {cur} {food_spend + groc_spend:,.2f}). "
            f"In the latest month ({latest_m}), Food and Dining accounted for **{cur} {last_m_food:,.2f}**."
        )
    elif any(k in q for k in ["recurring", "subscription", "emi", "fixed", "bills"]):
        if not recurring:
            answer = "No recurring payments or multi-month subscriptions were detected in your transaction history yet."
        else:
            total_rec_mo = sum(float(r.monthly_equivalent) for r in recurring if r.category != "Salary and Income")
            items_str = ", ".join([f"**{r.merchant}** ({cur} {float(r.typical_amount):,.0f} {r.frequency.lower()})" for r in recurring[:6]])
            answer = (
                f"I detected **{len(recurring)} recurring payment patterns** with an estimated monthly expense equivalent of "
                f"**{cur} {total_rec_mo:,.2f}/month**. Key recurring items include: {items_str}."
            )
    elif any(k in q for k in ["flag", "unusual", "anomaly", "review", "alert", "why was"]):
        if not alerts:
            answer = "There are currently **0 unusual transactions** flagged for review."
        else:
            top_a = alerts[0]
            t_obj = db.query(Transaction).filter(Transaction.id == top_a.transaction_id).first()
            t_desc = f"{t_obj.merchant} ({cur} {abs(float(t_obj.signed_amount)):,.2f} on {t_obj.txn_date})" if t_obj else "Transaction"
            answer = (
                f"There are **{len(alerts)} transactions flagged for review** (none are labeled as confirmed fraud). "
                f"For example, **{t_desc}** was flagged via `{top_a.detection_method}`: *{top_a.explanation}*"
            )
    elif any(k in q for k in ["increase", "changed", "trend", "compare"]):
        if len(months) < 2:
            answer = f"Only one month ({months[0]}) of data is available, so month-over-month category increases cannot be calculated yet."
        else:
            m_prev, m_curr = months[-2], months[-1]
            diffs = []
            for c_name in set(by_month_cat[m_prev].keys()) | set(by_month_cat[m_curr].keys()):
                p_val = by_month_cat[m_prev].get(c_name, 0.0)
                c_val = by_month_cat[m_curr].get(c_name, 0.0)
                diffs.append((c_name, c_val - p_val, p_val, c_val))
            diffs.sort(key=lambda x: x[1], reverse=True)
            top_inc = diffs[0]
            answer = (
                f"Comparing **{m_curr}** against **{m_prev}**, **{top_inc[0]}** increased the most by "
                f"**+{cur} {top_inc[1]:,.2f}** (from {cur} {top_inc[2]:,.2f} to {cur} {top_inc[3]:,.2f})."
            )
    elif any(k in q for k in ["savings rate", "health", "score", "save"]):
        answer = (
            f"Your observed **Savings Rate** is **{savings_rate:.1f}%** (Formula: `({cur} {total_inc:,.2f} Income - "
            f"{cur} {net_exp:,.2f} Net Expenses) / {cur} {total_inc:,.2f} Income × 100`). "
            f"Your overall **Financial Health Score** is **{health['overall_score']}/100** ({health['policy_applied']})."
        )
    elif any(k in q for k in ["budget", "cut", "reduce", "improve", "stay within"]):
        sugg_list = health.get("improvement_suggestions", [])
        if sugg_list:
            answer = "Based on your observed transaction patterns and configured budgets: " + " ".join(sugg_list[:2])
        else:
            top_c = top_cats[0] if top_cats else ("Other", 0.0)
            answer = (
                f"Your highest spending category is **{top_c[0]}** at **{cur} {top_c[1]:,.2f}** ({top_c[1] / net_exp * 100:.1f}% of net spend). "
                f"Setting a category budget 10% below this level in the Budget Planner would save approximately {cur} {top_c[1] * 0.10:,.0f} over an equivalent period."
            )
    else:
        # Default: Where did most of my money go?
        top3_str = ", ".join([f"**{c}** ({cur} {v:,.2f}, {v / net_exp * 100:.1f}%)" for c, v in top_cats[:3]]) if net_exp > 0 else "No expenses"
        answer = (
            f"During **{period_str}**, your total net spending was **{cur} {net_exp:,.2f}** against **{cur} {total_inc:,.2f}** in income "
            f"(Net Cash Flow: **{cur} {net_cf:,.2f}**). Most of your money went to: {top3_str}."
        )

    engine_label = "DETERMINISTIC_GROUNDING_ENGINE"

    # Optional Local Ollama Enhancement (strictly local, zero external cloud)
    if use_local_llm and settings.ENABLE_LOCAL_LLM:
        try:
            prompt = (
                f"You are FinSight AI, a grounded financial assistant. Answer the user's question ONLY using these verified facts:\n"
                f"Facts: {facts}\nDeterministic Calculation Result: {answer}\nUser Question: {question}\n"
                f"Keep your response concise, educational, and never invent numbers."
            )
            with httpx.Client(timeout=4.0) as client:
                resp = client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False}
                )
                if resp.status_code == 200:
                    llm_text = resp.json().get("response", "").strip()
                    if llm_text:
                        answer = llm_text
                        engine_label = f"LOCAL_OLLAMA ({settings.OLLAMA_MODEL}) + DETERMINISTIC_FACTS"
        except Exception:
            pass

    return {
        "answer": answer,
        "grounding_facts": facts,
        "engine_used": engine_label,
        "period_referenced": period_str,
        "disclaimer": "Educational budgeting guidance based strictly on imported records. Not investment, tax, or legal advice."
    }
