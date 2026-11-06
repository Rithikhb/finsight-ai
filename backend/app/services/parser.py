import io
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
import fitz  # PyMuPDF
from sqlalchemy.orm import Session
from ..models import Transaction
from .intelligence import categorize_single_transaction, extract_clean_merchant

DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y",
    "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%Y/%m/%d",
    "%d.%m.%Y", "%d-%b-%y", "%d/%m/%y"
]


def parse_decimal(val: Any) -> Optional[Decimal]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in {"nan", "none", "-", "null", ""}:
        return Decimal("0.00")
    # Handle accounting parentheses e.g. (1,200.50) or trailing Dr/Cr
    is_neg = False
    if (s.startswith("(") and s.endswith(")")) or s.upper().endswith("DR"):
        is_neg = True
    s_clean = re.sub(r"[^\d.-]", "", s)
    if not s_clean or s_clean in {"-", "."}:
        return None
    try:
        d = Decimal(s_clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return -abs(d) if is_neg else d
    except InvalidOperation:
        return None


def parse_flexible_date(val: Any) -> Optional[date]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    # Strip timestamp if present
    s_short = s.split(" ")[0] if ":" in s else s
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s_short, fmt).date()
        except ValueError:
            continue
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="raise")
        return dt.date()
    except Exception:
        return None


def detect_column_mapping(columns: List[str]) -> Dict[str, Optional[str]]:
    mapping: Dict[str, Optional[str]] = {
        "date": None, "description": None, "debit": None,
        "credit": None, "amount": None, "balance": None
    }
    for col in columns:
        c = str(col).strip().lower()
        if not mapping["date"] and any(k in c for k in ["date", "txn dt", "value dt", "timestamp"]):
            mapping["date"] = col
        elif not mapping["description"] and any(k in c for k in ["desc", "narration", "particular", "remark", "merchant", "details","name"]):
            mapping["description"] = col
        elif not mapping["debit"] and any(k in c for k in ["debit", "withdrawal", "dr", "paid out", "spend"]):
            mapping["debit"] = col
        elif not mapping["credit"] and any(k in c for k in ["credit", "deposit", "cr", "paid in", "income"]):
            mapping["credit"] = col
        elif not mapping["balance"] and any(k in c for k in ["balance", "closing", "running bal", "bal"]):
            mapping["balance"] = col
        elif not mapping["amount"] and any(k in c for k in ["amount", "txn amt", "value"]):
            mapping["amount"] = col
    return mapping


def extract_dataframe_from_pdf(file_bytes: bytes) -> pd.DataFrame:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    extracted_rows = []
    # Regex matching common bank statement lines: Date | Narration | Debit/Credit | Balance
    line_pattern = re.compile(
        r"^(\d{1,2}[-/\s][A-Za-z0-9]{2,3}[-/\s]\d{2,4}|\d{4}-\d{2}-\d{2})\s+(.+?)\s+([+-]?[\d,]+\.\d{2})\s+([+-]?[\d,]+\.\d{2})?$"
    )

    for page in doc:
        # First try structured table detection in PyMuPDF
        tables = page.find_tables()
        if tables and tables.tables:
            for tbl in tables.tables:
                df_tbl = tbl.to_pandas()
                if len(df_tbl.columns) >= 3:
                    extracted_rows.extend(df_tbl.to_dict(orient="records"))
            if extracted_rows:
                continue

        # Fallback: line-by-line text extraction
        text = page.get_text("text")
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            m = line_pattern.match(line)
            if m:
                d_str, desc, amt1, amt2 = m.groups()
                # Heuristic: if desc has CR/CREDIT/SALARY/DEPOSIT, treat amt1 as credit
                is_cr = any(k in desc.upper() for k in ["SALARY", "CREDIT", "NEFT CR", "REFUND", "INTEREST", "CR/"])
                extracted_rows.append({
                    "Date": d_str,
                    "Description": desc,
                    "Debit": "0.00" if is_cr else amt1,
                    "Credit": amt1 if is_cr else "0.00",
                    "Balance": amt2 if amt2 else ""
                })
    doc.close()
    if not extracted_rows:
        raise ValueError("No structured transaction table found in PDF. If this is a scanned image PDF, enable OCR or upload CSV/XLSX.")
    return pd.DataFrame(extracted_rows)


def reconcile_running_balances(rows: List[Dict[str, Any]]) -> Tuple[str, str]:
    """
    Validates running balances across chronological or reverse-chronological statement rows.
    Never silently alters values; reports exact row discrepancy if found.
    """
    valid_bal_rows = [r for r in rows if r.get("balance") is not None and not r.get("validation_errors")]
    if len(valid_bal_rows) < 2:
        return (
            "UNVERIFIABLE_PARTIAL",
            "Running balance column is missing or contains fewer than 2 rows; mathematical balance reconciliation skipped."
        )

    # Test chronological order: Bal[i] = Bal[i-1] + Credit[i] - Debit[i]
    chrono_mismatches = []
    for i in range(1, len(valid_bal_rows)):
        prev_bal = Decimal(str(valid_bal_rows[i - 1]["balance"]))
        curr_bal = Decimal(str(valid_bal_rows[i]["balance"]))
        credit = Decimal(str(valid_bal_rows[i]["credit"]))
        debit = Decimal(str(valid_bal_rows[i]["debit"]))
        expected = (prev_bal + credit - debit).quantize(Decimal("0.01"))
        if abs(curr_bal - expected) > Decimal("0.02"):
            chrono_mismatches.append((valid_bal_rows[i]["temp_id"], float(expected), float(curr_bal)))

    if not chrono_mismatches:
        return (
            "VERIFIED",
            f"All {len(valid_bal_rows)} chronological running balances mathematically reconciled (Opening + Credits - Debits = Closing)."
        )

    # Test reverse-chronological order (newest at top): Bal[i-1] = Bal[i] + Credit[i-1] - Debit[i-1]
    rev_mismatches = []
    for i in range(1, len(valid_bal_rows)):
        newer_bal = Decimal(str(valid_bal_rows[i - 1]["balance"]))
        older_bal = Decimal(str(valid_bal_rows[i]["balance"]))
        credit = Decimal(str(valid_bal_rows[i - 1]["credit"]))
        debit = Decimal(str(valid_bal_rows[i - 1]["debit"]))
        expected_newer = (older_bal + credit - debit).quantize(Decimal("0.01"))
        if abs(newer_bal - expected_newer) > Decimal("0.02"):
            rev_mismatches.append((valid_bal_rows[i - 1]["temp_id"], float(expected_newer), float(newer_bal)))

    if not rev_mismatches:
        return (
            "VERIFIED",
            f"All {len(valid_bal_rows)} reverse-chronological running balances mathematically reconciled."
        )

    first_err = chrono_mismatches[0]
    return (
        "DISCREPANCY_DETECTED",
        f"Balance mismatch detected at row #{first_err[0]}: expected {first_err[1]:,.2f} based on prior balance, but statement shows {first_err[2]:,.2f}. Please review flagged rows before confirming import."
    )


def parse_and_validate_statement(
    file_bytes: bytes,
    filename: str,
    user_id: int,
    account_id: int,
    db: Session
) -> Dict[str, Any]:
    ext = filename.lower().split(".")[-1]
    if ext == "csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif ext in {"xlsx", "xls"}:
        df = pd.read_excel(io.BytesIO(file_bytes))
    elif ext == "pdf":
        df = extract_dataframe_from_pdf(file_bytes)
    else:
        raise ValueError(f"Unsupported file extension '.{ext}'. Supported formats: CSV, XLSX, PDF.")

    if df.empty:
        raise ValueError("The uploaded statement contains no rows.")

    col_map = detect_column_mapping(list(df.columns))
    if not col_map["date"] or not col_map["description"]:
        raise ValueError(
            f"Could not automatically detect required Date and Description columns. Found columns: {list(df.columns)}"
        )

    # Fetch existing transactions for duplicate detection
    existing_txns = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.account_id == account_id
    ).all()
    existing_signatures = {
        (t.txn_date.isoformat(), float(t.signed_amount), t.description.strip().lower()[:40])
        for t in existing_txns
    }
    seen_in_file = set()

    preview_rows = []
    valid_count = 0
    correction_count = 0
    dup_count = 0

    for idx, row in df.iterrows():
        errors = []
        raw_date = str(row.get(col_map["date"], "")).strip()
        parsed_date = parse_flexible_date(row.get(col_map["date"]))
        if not parsed_date:
            errors.append(f"Invalid date: '{raw_date}'")

        raw_desc = str(row.get(col_map["description"], "")).strip()
        if not raw_desc or raw_desc.lower() == "nan":
            raw_desc = "Unknown Transaction"
            errors.append("Missing transaction description")

        debit_val = Decimal("0.00")
        credit_val = Decimal("0.00")

        if col_map["debit"] or col_map["credit"]:
            d_parsed = parse_decimal(row.get(col_map["debit"])) if col_map["debit"] else Decimal("0.00")
            c_parsed = parse_decimal(row.get(col_map["credit"])) if col_map["credit"] else Decimal("0.00")
            if d_parsed is None or c_parsed is None:
                errors.append("Non-numeric debit or credit value")
            else:
                debit_val = abs(d_parsed)
                credit_val = abs(c_parsed)
        elif col_map["amount"]:
            amt_parsed = parse_decimal(row.get(col_map["amount"]))
            if amt_parsed is None:
                errors.append("Invalid numeric amount")
            elif amt_parsed < 0:
                debit_val = abs(amt_parsed)
            else:
                credit_val = amt_parsed
        else:
            errors.append("No Debit, Credit, or Amount column detected")

        if debit_val > 0 and credit_val > 0:
            errors.append("Both Debit and Credit are positive on the same row")
        if debit_val == 0 and credit_val == 0 and not errors:
            errors.append("Zero-value transaction requires confirmation")

        signed_amount = credit_val - debit_val
        bal_parsed = parse_decimal(row.get(col_map["balance"])) if col_map["balance"] else None

        merchant = extract_clean_merchant(raw_desc)
        cat_info = categorize_single_transaction(
            description=raw_desc,
            merchant=merchant,
            signed_amount=float(signed_amount),
            user_id=user_id,
            db=db
        )

        # Duplicate check (against DB and within same batch)
        date_key = parsed_date.isoformat() if parsed_date else raw_date
        sig = (date_key, float(signed_amount), raw_desc.lower()[:40])
        is_dup = False
        dup_reason = None
        if sig in existing_signatures:
            is_dup = True
            dup_reason = "Matches an already imported transaction in this account (Date + Amount + Description)."
        elif sig in seen_in_file:
            is_dup = True
            dup_reason = "Identical transaction row appears earlier in this same file."
        seen_in_file.add(sig)

        if errors:
            correction_count += 1
        else:
            valid_count += 1
        if is_dup:
            dup_count += 1

        extraction_conf = 0.55 if errors else (0.98 if bal_parsed is not None else 0.90)

        preview_rows.append({
            "temp_id": int(idx) + 1,
            "txn_date": parsed_date.isoformat() if parsed_date else None,
            "raw_date": raw_date,
            "description": raw_desc,
            "merchant": merchant,
            "debit": float(debit_val),
            "credit": float(credit_val),
            "signed_amount": float(signed_amount),
            "balance": float(bal_parsed) if bal_parsed is not None else None,
            "category": cat_info["category"],
            "txn_type": cat_info["txn_type"],
            "extraction_confidence": extraction_conf,
            "categorization_confidence": cat_info["confidence"],
            "classification_source": cat_info["source"],
            "validation_errors": errors,
            "is_duplicate_candidate": is_dup,
            "duplicate_reason": dup_reason,
            "include_in_import": (len(errors) == 0 and not is_dup)
        })

    recon_status, recon_details = reconcile_running_balances(preview_rows)

    return {
        "filename": filename,
        "account_id": account_id,
        "total_rows_discovered": len(preview_rows),
        "valid_rows_count": valid_count,
        "rows_requiring_correction": correction_count,
        "duplicate_candidates_count": dup_count,
        "reconciliation_status": recon_status,
        "reconciliation_details": recon_details,
        "rows": preview_rows
    }